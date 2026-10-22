from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.services.ocr_service import TesseractOCRService


class StubTesseract:
    class Output:
        DICT = "dict"

    def __init__(self):
        self.received = None

    def image_to_data(self, image, lang, config, output_type):
        self.received = image
        assert lang == "eng"
        assert config == "--oem 1 --psm 6"
        assert output_type == "dict"
        return {
            "text": ["Question", "stem"],
            "conf": ["98", "97"],
            "left": [5, 45],
            "top": [5, 5],
            "width": [35, 25],
            "height": [10, 10],
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 1],
        }


def test_tesseract_receives_preprocessed_grayscale_crop_and_maps_boxes(monkeypatch):
    engine = StubTesseract()
    service = TesseractOCRService()
    monkeypatch.setattr(service, "_get_engine", lambda: engine)
    monkeypatch.setattr(service, "_option_marker", staticmethod(lambda image, text, box: None))

    # Portrait screenshot: 20% top status-bar area must be cropped before OCR.
    image = Image.new("RGB", (120, 300), (255, 0, 0))
    rows = service.extract(image)

    assert isinstance(engine.received, np.ndarray)
    assert engine.received.shape == (240, 120)
    assert engine.received.dtype == np.uint8
    assert rows[0]["text"] == "Question"
    assert rows[0]["confidence"] == 0.98
    # OCR y=5 maps back to original-image y=60+5=65.
    assert rows[0]["bbox"][0][1] == 65.0
    assert rows[0]["bbox"][2][1] == 75.0
    assert rows[1]["text"] == "stem"
