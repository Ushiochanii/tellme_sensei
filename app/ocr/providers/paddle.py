"""PaddleOCR implementation of the generic OCR provider contract."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from app.ocr.profiling import make_profile_run
from app.ocr.types import OCRError, OCRLine, OCRResult
from app.ocr.utils import normalize_ocr_text
from app.thread_info import current_thread_info

logger = logging.getLogger(__name__)


class PaddleOCRProvider:
    """Lazy PaddleOCR wrapper supporting PaddleOCR 2.x and 3.x result shapes."""

    def __init__(self, language: str = "japan", engine: Any | None = None) -> None:
        self.language = language
        self._engine = engine

    def recognize(self, image: str | Path | Any) -> OCRResult:
        """Recognize text from an image path or an image object."""

        if isinstance(image, (str, Path)) and not Path(image).exists():
            raise OCRError(f"图片文件不存在：{image}")

        engine = self._get_engine()
        self._restore_application_logging()
        logger.info("OCR 开始")
        try:
            logger.info("OCR engine call before [%s]", current_thread_info())
            raw = self._run_engine(engine, image)
            logger.info("OCR engine call after [%s]", current_thread_info())
            logger.info("OCR result parsing before [%s]", current_thread_info())
            lines = self._extract_lines(raw)
            logger.info("OCR result parsing after [%s]", current_thread_info())
        except OCRError:
            raise
        except Exception as exc:
            logger.error("OCR 失败: %s", type(exc).__name__)
            raise OCRError("OCR 处理失败，请检查图片格式和 PaddleOCR 安装。") from exc

        normalized = normalize_ocr_text(lines)
        logger.info("OCR 完成（识别行数=%d，文本长度=%d）", len(lines), len(normalized))
        return OCRResult(text=normalized, lines=tuple(lines))

    def recognize_profiled(self, image: str | Path | Any) -> tuple[OCRResult, dict[str, float]]:
        """Run OCR with opt-in timing instrumentation for the diagnostic worker."""

        started = time.perf_counter()
        if isinstance(image, (str, Path)) and not Path(image).exists():
            raise OCRError(f"鍥剧墖鏂囦欢涓嶅瓨鍦細{image}")

        engine_init_ms = 0.0
        if self._engine is None:
            init_started = time.perf_counter()
            engine = self._get_engine()
            engine_init_ms = (time.perf_counter() - init_started) * 1000.0
        else:
            engine = self._get_engine()

        input_started = time.perf_counter()
        prepared_image = self._prepare_image(image)
        input_prepare_ms = (time.perf_counter() - input_started) * 1000.0
        engine_started = time.perf_counter()
        if hasattr(engine, "predict"):
            raw = engine.predict(prepared_image)
        else:
            raw = engine.ocr(prepared_image, cls=False)
        engine_call_ms = (time.perf_counter() - engine_started) * 1000.0

        parse_started = time.perf_counter()
        lines = self._extract_lines(raw)
        result_parse_ms = (time.perf_counter() - parse_started) * 1000.0
        normalize_started = time.perf_counter()
        normalized = normalize_ocr_text(lines)
        normalize_ms = (time.perf_counter() - normalize_started) * 1000.0
        result = OCRResult(text=normalized, lines=tuple(lines))
        timings = make_profile_run(
            1,
            {
                "engine_init_ms": engine_init_ms,
                "input_prepare_ms": input_prepare_ms,
                "engine_call_ms": engine_call_ms,
                "result_parse_ms": result_parse_ms,
                "normalize_ms": normalize_ms,
                "total_ms": (time.perf_counter() - started) * 1000.0,
            },
        )
        return result, {
            key: float(value) for key, value in timings.items() if key != "index"
        }

    @staticmethod
    def _restore_application_logging() -> None:
        """PaddleOCR 2.x raises the root threshold to WARNING during setup."""

        root_logger = logging.getLogger()
        if root_logger.handlers:
            root_logger.setLevel(logging.INFO)

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCRError(
                "未安装 PaddleOCR 依赖，请先执行 python -m pip install -r requirements.txt。"
            ) from exc

        try:
            # PaddleOCR 3.x uses these options; they also avoid unnecessary document analysis.
            self._engine = PaddleOCR(
                lang=self.language,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except TypeError:
            # PaddleOCR 2.x compatibility.
            self._engine = PaddleOCR(use_angle_cls=False, lang=self.language)
        return self._engine

    @staticmethod
    def _run_engine(engine: Any, image: str | Path | Any) -> Any:
        image_arg = PaddleOCRProvider._prepare_image(image)
        if hasattr(engine, "predict"):
            return engine.predict(image_arg)
        return engine.ocr(image_arg, cls=False)

    @staticmethod
    def _prepare_image(image: str | Path | Any) -> Any:
        """Convert Qt QImage/QPixmap-like objects to a detached RGB ndarray."""

        if isinstance(image, Path):
            return str(image)
        if isinstance(image, str):
            return image
        qimage = image.toImage() if hasattr(image, "toImage") else image
        if not (hasattr(qimage, "bits") and hasattr(qimage, "width")):
            return image
        try:
            import numpy as np

            from PySide6.QtGui import QImage

            qimage = qimage.convertToFormat(QImage.Format_RGBA8888)
            width = qimage.width()
            height = qimage.height()
            stride = qimage.bytesPerLine()
            buffer = qimage.bits()
            data = np.frombuffer(buffer, dtype=np.uint8, count=stride * height)
            rgba = data.reshape((height, stride // 4, 4))[:, :width, :]
            return rgba[:, :, :3].copy()
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            raise OCRError("无法将内存截图转换为 OCR 图片格式。") from exc

    @classmethod
    def _extract_lines(cls, raw: Any) -> list[OCRLine]:
        """Extract lines from PaddleOCR 2.x lists or 3.x result objects/dicts."""

        lines: list[OCRLine] = []
        cls._collect_lines(raw, lines)
        lines.sort(key=lambda item: (item.top, item.left))
        return cls._merge_nearby_lines(lines)

    @staticmethod
    def _merge_nearby_lines(lines: list[OCRLine]) -> list[OCRLine]:
        """Group word boxes into visual rows while preserving already grouped OCR lines."""

        if len(lines) < 2 or all(line.top == 0.0 for line in lines):
            return lines

        rows: list[list[OCRLine]] = []
        row_tops: list[float] = []
        for line in lines:
            matching_row = next(
                (
                    index
                    for index, row_top in enumerate(row_tops)
                    if abs(line.top - row_top) <= 12.0
                ),
                None,
            )
            if matching_row is None:
                rows.append([line])
                row_tops.append(line.top)
            else:
                rows[matching_row].append(line)

        merged: list[OCRLine] = []
        for row in sorted(rows, key=lambda items: min(item.top for item in items)):
            row.sort(key=lambda item: item.left)
            text = ""
            confidence_values: list[float] = []
            for item in row:
                text = PaddleOCRProvider._join_fragments(text, item.text)
                if item.confidence is not None:
                    confidence_values.append(item.confidence)
            merged.append(
                OCRLine(
                    text=text.strip(),
                    confidence=(sum(confidence_values) / len(confidence_values))
                    if confidence_values
                    else None,
                    top=min(item.top for item in row),
                    left=min(item.left for item in row),
                )
            )
        return merged

    @staticmethod
    def _join_fragments(previous: str, current: str) -> str:
        if not previous:
            return current
        if not current:
            return previous
        # Add spaces between Latin/number tokens; Chinese/Japanese text stays compact.
        if re.search(r"[A-Za-z0-9]$", previous) and re.match(r"[A-Za-z0-9]", current):
            return f"{previous} {current}"
        if previous[-1].isascii() and current[0].isascii() and previous[-1] not in "([{":
            return f"{previous} {current}"
        return previous + current

    @classmethod
    def _collect_lines(cls, value: Any, output: list[OCRLine], box: Any = None) -> None:
        if value is None:
            return
        if hasattr(value, "json") and callable(value.json):
            try:
                cls._collect_lines(value.json, output, box)
                return
            except Exception:
                pass
        if isinstance(value, dict):
            texts = value.get("rec_texts")
            if texts is None:
                texts = value.get("texts")
            scores = value.get("rec_scores")
            if scores is None:
                scores = value.get("scores")
            if scores is None:
                scores = []
            boxes = value.get("rec_boxes")
            if boxes is None:
                boxes = value.get("boxes")
            if boxes is None:
                boxes = []
            if texts is not None:
                for index, text in enumerate(texts):
                    score = cls._number_at(scores, index)
                    current_box = cls._item_at(boxes, index)
                    output.append(cls._line_from(text, score, current_box))
                return
            if "text" in value:
                output.append(cls._line_from(value["text"], value.get("score"), box))
                return
            for nested in value.values():
                cls._collect_lines(nested, output, box)
            return
        if isinstance(value, (list, tuple)):
            # PaddleOCR 2.x: [box, (text, confidence)].
            if len(value) == 2 and cls._looks_like_box(value[0]) and cls._looks_like_pair(value[1]):
                text, score = value[1][0], value[1][1]
                output.append(cls._line_from(text, score, value[0]))
                return
            for nested in value:
                cls._collect_lines(nested, output, box)
            return
        if hasattr(value, "rec_texts"):
            cls._collect_lines(
                {
                    "rec_texts": getattr(value, "rec_texts", []),
                    "rec_scores": getattr(value, "rec_scores", []),
                    "rec_boxes": getattr(value, "rec_boxes", []),
                },
                output,
                box,
            )

    @staticmethod
    def _line_from(text: Any, score: Any = None, box: Any = None) -> OCRLine:
        top, left = 0.0, 0.0
        if isinstance(box, (list, tuple)) and box:
            try:
                points = box if isinstance(box[0], (list, tuple)) else [box]
                left = min(float(point[0]) for point in points)
                top = min(float(point[1]) for point in points)
            except (TypeError, ValueError, IndexError):
                pass
        try:
            confidence = float(score) if score is not None else None
        except (TypeError, ValueError):
            confidence = None
        return OCRLine(text=str(text).strip(), confidence=confidence, top=top, left=left)

    @staticmethod
    def _looks_like_box(value: Any) -> bool:
        return isinstance(value, (list, tuple)) and len(value) >= 2

    @staticmethod
    def _looks_like_pair(value: Any) -> bool:
        return isinstance(value, (list, tuple)) and len(value) >= 1 and isinstance(value[0], str)

    @staticmethod
    def _item_at(value: Any, index: int) -> Any:
        try:
            return value[index]
        except (IndexError, TypeError, KeyError):
            return None

    @staticmethod
    def _number_at(value: Any, index: int) -> Any:
        return PaddleOCRProvider._item_at(value, index)
