from app.services.ocr_service import OCRLine, OCRService, normalize_ocr_text


def test_normalize_ocr_text_preserves_order_and_removes_empty_lines() -> None:
    lines = [
        OCRLine("  第二行  ", top=20, left=0),
        OCRLine("", top=30, left=0),
        OCRLine("第一行", top=10, left=0),
    ]
    assert normalize_ocr_text(sorted(lines, key=lambda line: line.top)) == "第一行\n第二行"


def test_extract_paddleocr_v2_shape() -> None:
    raw = [
        [
            [[[0, 20], [100, 20], [100, 40], [0, 40]], ("第二行", 0.9)],
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("第一行", 0.95)],
        ]
    ]
    lines = OCRService._extract_lines(raw)
    assert [line.text for line in lines] == ["第一行", "第二行"]


def test_extract_paddleocr_v3_shape() -> None:
    raw = [{"rec_texts": ["题目", "选项 A"], "rec_scores": [0.9, 0.8]}]
    lines = OCRService._extract_lines(raw)
    assert [line.text for line in lines] == ["题目", "选项 A"]
