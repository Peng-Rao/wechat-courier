from PIL import Image, ImageDraw
import pytest

from tests.manual_window_restore_rendering import compare_colors


@pytest.mark.parametrize("dark", [False, True])
def test_color_gate_rejects_whiteout_even_when_scene_is_nonblank(dark):
    image = Image.new("RGB", (400, 300), (32, 32, 35) if dark else (245, 245, 247))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 140), fill=(238, 238, 239) if dark else (37, 38, 42))
    draw.rectangle((100, 180, 220, 220), fill=(248, 124, 64))
    assert compare_colors(image, image.copy(), dark)["brand"]["retained"] == 1
    washed = Image.blend(image, Image.new("RGB", image.size, "white"), 0.6)
    with pytest.raises(AssertionError):
        compare_colors(image, washed, dark)


def test_recreated_frame_allows_only_one_extra_edge_pixel():
    image = Image.new("RGB", (400, 300), (32, 32, 35))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 140), fill=(238, 238, 239))
    draw.rectangle((100, 180, 220, 220), fill=(248, 124, 64))
    extra = Image.new("RGB", (400, 301))
    extra.paste(image, (0, 0))
    with pytest.raises(AssertionError):
        compare_colors(image, extra, True)
    assert compare_colors(image, extra, True, border_rounding=1)["text"]["retained"] == 1
    with pytest.raises(AssertionError):
        compare_colors(image, extra.resize((400, 305)), True, border_rounding=1)
