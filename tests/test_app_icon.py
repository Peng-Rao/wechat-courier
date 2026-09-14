from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "build" / "app_icon_preview.png"
ICON = ROOT / "assets" / "app.ico"
EXPECTED_RGB_SHA256 = "0963b33899e02bee0a99e8d5cefa8c045925f716a40c8ce57b429a3bd510811e"
EXPECTED_ICON_SIZES = {
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


def test_app_icon_preview_only_rounds_the_existing_portrait_alpha():
    with Image.open(PREVIEW) as source:
        preview = source.convert("RGBA")

    assert preview.size == (256, 256)
    assert hashlib.sha256(preview.convert("RGB").tobytes()).hexdigest() == (
        EXPECTED_RGB_SHA256
    )

    alpha = preview.getchannel("A")
    assert [alpha.getpixel(point) for point in ((0, 0), (255, 0), (0, 255), (255, 255))] == [
        0,
        0,
        0,
        0,
    ]
    assert alpha.getpixel((128, 128)) == 255
    assert any(0 < value < 255 for value in alpha.tobytes())

    first_half_opaque_on_left = next(
        y for y in range(preview.height) if alpha.getpixel((0, y)) >= 128
    )
    assert 44 <= first_half_opaque_on_left <= 47


def test_app_ico_contains_all_required_rounded_frames():
    with Image.open(ICON) as icon:
        assert icon.format == "ICO"
        assert icon.info["sizes"] == EXPECTED_ICON_SIZES

        for size in EXPECTED_ICON_SIZES:
            frame = icon.ico.getimage(size).convert("RGBA")
            width, height = size
            assert frame.getpixel((0, 0))[3] == 0
            assert frame.getpixel((width - 1, 0))[3] == 0
            assert frame.getpixel((0, height - 1))[3] == 0
            assert frame.getpixel((width - 1, height - 1))[3] == 0
            assert frame.getpixel((width // 2, height // 2))[3] == 255
