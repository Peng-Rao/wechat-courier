from pathlib import Path

from PIL import Image


_IMAGE_FORMATS = {"BMP", "DIB", "GIF", "ICO", "JPEG", "PNG", "TIFF", "WEBP"}


def is_image_attachment(path: str | Path) -> bool:
    """Identify native image attachments from their header, without pixel decoding."""
    try:
        with Image.open(path) as image:
            return image.format in _IMAGE_FORMATS
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
