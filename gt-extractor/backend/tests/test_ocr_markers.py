from PIL import Image, ImageDraw

from app.services.ocr_service import TesseractOCRService


def make_badge(color):
    image = Image.new("RGB", (120, 40), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 5, 35, 32), radius=8, fill=color)
    draw.text((16, 10), "A", fill="white")
    return image


def test_green_option_badge_detected():
    image = make_badge((35, 170, 80))
    box = [[16, 10], [25, 10], [25, 24], [16, 24]]
    assert TesseractOCRService._option_marker(image, "A. Option text", box) == "green"


def test_red_option_badge_detected():
    image = make_badge((220, 45, 55))
    box = [[16, 10], [25, 10], [25, 24], [16, 24]]
    assert TesseractOCRService._option_marker(image, "A. Option text", box) == "red"


def test_neutral_option_has_no_marker():
    image = make_badge((220, 220, 220))
    box = [[16, 10], [25, 10], [25, 24], [16, 24]]
    assert TesseractOCRService._option_marker(image, "A. Option text", box) is None
