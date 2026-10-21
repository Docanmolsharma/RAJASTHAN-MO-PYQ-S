from PIL import Image
import numpy as np

from app.services.ocr_service import PaddleOCRService


class StubEngine:
    def __init__(self):
        self.received = None

    def ocr(self, image, cls=True):
        self.received = image
        assert cls is True
        return [[
            ([[5, 5], [80, 5], [80, 25], [5, 25]], ("Question text", 0.98))
        ]]


def test_pil_image_converted_to_bgr_array_before_ocr():
    engine = StubEngine()
    service = PaddleOCRService()
    service._engine = engine
    image = Image.new("RGB", (120, 50), (255, 0, 0))
    rows = service.extract(image)

    assert isinstance(engine.received, np.ndarray)
    assert engine.received.shape == (50, 120, 3)
    assert engine.received.dtype == np.uint8
    assert engine.received.flags["C_CONTIGUOUS"]
    assert engine.received[0, 0].tolist() == [0, 0, 255]
    assert rows[0]["text"] == "Question text"
    assert rows[0]["confidence"] == 0.98
