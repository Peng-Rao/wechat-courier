"""Extract the approved PDF's original monogram paths, without editing the PDF.

Run with Python providing pypdf, pypdfium2 and Pillow:
    python scripts/extract_fuge_logo.py SOURCE.pdf
"""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject, RectangleObject
import pypdfium2 as pdfium


SOURCE_SHA256 = "611790aec1ee835d24029747792e1ecb94b1ee6a8b8dde184367015ff600bc42"
ICON_SIZES = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]


def extract_logo(source: Path) -> Image.Image:
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Use the approved original PDF; its vector selection is source-specific.")
    reader = PdfReader(BytesIO(data))
    original = reader.pages[0]
    operations = ContentStream(original.get_contents(), reader).operations
    # The first monogram consists of these two filled paths; text and borders
    # are separate operations. Retain their original transforms and RGB fill.
    paths = operations[426:462]
    if sum(operator == b"f" for _, operator in paths) != 2:
        raise ValueError("The PDF no longer contains the approved two monogram paths.")

    left, bottom, right, top = (815.8828, 1716.851, 1027.5058, 1915.801)
    side = (right - left) / 0.875
    center_x, center_y = (left + right) / 2, (bottom + top) / 2
    writer = PdfWriter()
    page = writer.add_blank_page(width=side, height=side)
    page.mediabox = RectangleObject((center_x - side / 2, center_y - side / 2,
                                    center_x + side / 2, center_y + side / 2))
    page[NameObject("/Resources")] = original["/Resources"].clone(writer)
    stream = ContentStream(None, writer)
    stream.operations = operations[3:5] + operations[13:14] + paths
    page[NameObject("/Contents")] = writer._add_object(stream)
    isolated = BytesIO()
    writer.write(isolated)
    with pdfium.PdfDocument(isolated.getvalue()) as document:
        rendered_page = document[0]
        try:
            bitmap = rendered_page.render(scale=2048 / side, fill_color=(0, 0, 0, 0))
            try:
                coverage = bitmap.to_pil().convert("RGBA").getchannel("A")
                rgb = tuple(round(float(value) * 255) for value in operations[13][0])
                logo = Image.new("RGBA", (512, 512), (*rgb, 0))
                logo.putalpha(coverage.resize(logo.size, Image.Resampling.BOX))
            finally:
                bitmap.close()
        finally:
            rendered_page.close()
    return logo


def resize_logo(logo: Image.Image, size: tuple[int, int]) -> Image.Image:
    # Resize coverage separately so tiny icons retain the PDF's flat fill;
    # premultiplied RGBA interpolation otherwise introduces colored fringes.
    resized = Image.new("RGBA", size, logo.getpixel((0, 0)))
    resized.putalpha(logo.getchannel("A").resize(size, Image.Resampling.BOX))
    return resized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "assets")
    args = parser.parse_args()
    logo = extract_logo(args.source)
    args.output.mkdir(parents=True, exist_ok=True)
    logo.save(args.output / "fuge-logo.png")
    for size in (64, 256):
        resize_logo(logo, (size, size)).save(args.output / f"fuge-logo-{size}.png")
    frames = [resize_logo(logo, size) for size in ICON_SIZES]
    logo.save(args.output / "app.ico", sizes=ICON_SIZES, append_images=frames)
    print("Extracted original paths to transparent 64/256/512 PNGs and a seven-size ICO.")


if __name__ == "__main__":
    main()
