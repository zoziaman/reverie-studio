from io import BytesIO

from PIL import Image

from pipeline.image_pipeline import _minimal_png_bytes


def test_minimal_png_bytes_is_valid_png():
    payload = _minimal_png_bytes()

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")

    img = Image.open(BytesIO(payload))
    assert img.size == (1, 1)
    assert img.getpixel((0, 0)) == (0, 0, 0)
