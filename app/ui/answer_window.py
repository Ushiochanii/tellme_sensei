"""Frameless, always-on-top answer window with cancellable-job controls."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.analysis import AnalysisMode
from app.pipeline import PipelineResult
from app.settings.repository import SettingsRepository
from app.ui.answer_window_placement import place_answer_window
from app.ui.theme import (
    TEXT_ACCENT,
    VISION_ACCENT,
    answer_window_stylesheet,
    mode_icon,
)

logger = logging.getLogger(__name__)


class _TitleBar(QWidget):
    """Small custom title bar that makes the frameless window draggable."""

    moved = Signal()



    def __init__(
        self,
        title: str,
        close_callback,
        mode: AnalysisMode = AnalysisMode.TEXT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self.setObjectName("answerTitleBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 8, 8)
        layout.setSpacing(8)
        self.mode_icon = QLabel()
        self.mode_icon.setFixedSize(24, 24)
        layout.addWidget(self.mode_icon)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("answerTitleLabel")
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        close_button = QToolButton()
        close_button.setText("×")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(close_callback)
        layout.addWidget(close_button)
        self.close_button = close_button
        self.set_mode(mode)

    def set_mode(self, mode: AnalysisMode) -> None:
        is_vision = mode is AnalysisMode.VISION
        self.title_label.setText("Vision Analysis" if is_vision else "Text / OCR Analysis")
        self.mode_icon.setPixmap(mode_icon("vision" if is_vision else "text", VISION_ACCENT if is_vision else TEXT_ACCENT))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            self.moved.emit()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class AnswerWindow(QWidget):
    """Display OCR/AI output and control the active processing job."""

    reanalyze_requested = Signal()
    stop_requested = Signal()
    recapture_requested = Signal()
    closed = Signal()

    def __init__(
        self,
        settings_repository: SettingsRepository | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_repository = settings_repository or SettingsRepository()
        self._geometry_restored = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(360, 420)
        self.resize(560, 640)
        self._restore_saved_geometry()
        self._ocr_text = ""
        self._answer_text = ""
        self._vision_mode = False
        self._closed_emitted = False
        self._auto_watch_active = False
        self._auto_watch_generation: int | None = None
        self._auto_watch_roi: QRect | None = None
        self._auto_watch_screen = None
        self._auto_watch_user_moved = False
        self._skip_geometry_save = False
        self._auto_watch_previous_geometry: QRect | None = None
        self._auto_watch_previous_geometry_restored = False

        self.setObjectName("answerWindow")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow_color = QColor(Qt.GlobalColor.black)
        shadow_color.setAlpha(38)
        shadow.setColor(shadow_color)
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        surface = QFrame(self)
        surface.setObjectName("answerSurface")
        self.answer_surface = surface
        root.addWidget(surface)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(14, 12, 14, 12)
        surface_layout.setSpacing(10)

        self.title_bar = _TitleBar("Text / OCR Analysis", self.close, parent=self)
        self.title_bar.moved.connect(self._mark_auto_watch_user_moved)
        surface_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(4, 0, 4, 0)
        body_layout.setSpacing(10)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setProperty("state", "ready")
        body_layout.addWidget(self.status_label)

        ocr_card = QFrame()
        ocr_card.setObjectName("ocrCard")
        self.ocr_card = ocr_card
        ocr_layout = QVBoxLayout(ocr_card)
        ocr_layout.setContentsMargins(14, 12, 14, 14)
        ocr_layout.setSpacing(8)
        self.ocr_section_label = self._section_label("Recognized Question")
        ocr_layout.addWidget(self.ocr_section_label)
        self.ocr_edit = QPlainTextEdit()
        self.ocr_edit.setObjectName("ocrEdit")
        self.ocr_edit.setReadOnly(True)
        self.ocr_edit.setPlaceholderText("Recognized text will appear here.")
        self.ocr_edit.setMaximumHeight(145)
        ocr_layout.addWidget(self.ocr_edit)
        body_layout.addWidget(ocr_card)

        answer_card = QFrame()
        answer_card.setObjectName("answerCard")
        answer_layout = QVBoxLayout(answer_card)
        answer_layout.setContentsMargins(14, 12, 14, 14)
        answer_layout.setSpacing(8)
        self.answer_section_label = self._section_label("Answer")
        self.answer_section_label.setObjectName("answerSectionTitle")
        answer_layout.addWidget(self.answer_section_label)
        self.answer_edit = QPlainTextEdit()
        self.answer_edit.setObjectName("answerEdit")
        self.answer_edit.setReadOnly(True)
        self.answer_edit.setPlaceholderText("The analysis will appear here.")
        self.answer_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        answer_layout.addWidget(self.answer_edit, 1)
        body_layout.addWidget(answer_card, 1)
        surface_layout.addWidget(body, 1)

        footer = QWidget()
        footer.setObjectName("answerFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 8, 10, 8)
        footer_layout.setSpacing(7)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("copyButton")
        self.retry_button = QPushButton("Retry")
        self.retry_button.setObjectName("retryButton")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.recapture_button = QPushButton("Recapture")
        self.recapture_button.setObjectName("recaptureButton")
        close_button = QPushButton("Close")
        close_button.setObjectName("closeActionButton")
        self.close_action_button = close_button
        self.copy_button.clicked.connect(self.copy_answer)
        self.retry_button.clicked.connect(self.reanalyze_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.recapture_button.clicked.connect(self.recapture_requested.emit)
        close_button.clicked.connect(self.close)
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.stop_button.setVisible(False)
        self.recapture_button.setVisible(False)
        footer_layout.addWidget(self.copy_button)
        footer_layout.addWidget(self.retry_button)
        footer_layout.addWidget(self.stop_button)
        footer_layout.addWidget(self.recapture_button)
        footer_layout.addWidget(close_button)
        footer_layout.addStretch(1)
        footer_layout.addWidget(QSizeGrip(footer))
        surface_layout.addWidget(footer)

        self.setStyleSheet(answer_window_stylesheet())
        self.set_mode(AnalysisMode.TEXT)
        self.set_status("等待处理")

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def show_processing(self) -> None:
        self._skip_geometry_save = False
        self.set_mode(AnalysisMode.TEXT)
        self._answer_text = ""
        self.answer_edit.clear()
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.recapture_button.setVisible(False)
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(True)
        self.set_status("正在识别题目...")
        self.show_at_current_screen()

    def begin_auto_watch(self, mode: AnalysisMode | str, generation: int, roi_hint: QRect | None = None, screen=None) -> None:
        """Enter session-only Auto Watch presentation without changing saved geometry."""
        self._auto_watch_previous_geometry = QRect(self.geometry())
        self._auto_watch_previous_geometry_restored = self._geometry_restored
        self._auto_watch_active = True
        self._auto_watch_generation = generation
        self._auto_watch_roi = QRect(roi_hint) if isinstance(roi_hint, QRect) else None
        self._auto_watch_screen = screen
        self._auto_watch_user_moved = False
        self._skip_geometry_save = True
        self.set_mode(mode)
        self._ocr_text = ""
        self._answer_text = ""
        self.ocr_edit.clear(); self.answer_edit.clear()
        self._disable_auto_watch_job_controls()
        self.set_status("Auto Watch · Analyzing…")
        self._place_auto_watch_window()

    def show_auto_watch_analyzing(self, generation: int) -> None:
        if not self._auto_watch_active or generation < self._auto_watch_generation:
            return
        self._auto_watch_generation = generation
        self._disable_auto_watch_job_controls()
        self.set_status("New question detected · Analyzing…" if self._answer_text or self._ocr_text else "Auto Watch · Analyzing…")
        self._place_auto_watch_window()

    def show_auto_watch_result(self, generation: int, result) -> None:
        if not self._auto_watch_active or generation < self._auto_watch_generation:
            return
        self._auto_watch_generation = generation
        if self._vision_mode:
            self.answer_edit.setPlainText(str(result))
            self._answer_text = str(result)
        elif isinstance(result, PipelineResult):
            self.set_ocr_text(result.ocr.text)
            self._answer_text = result.answer
            self.answer_edit.setPlainText(result.answer)
        else:
            ocr = getattr(result, "ocr", None)
            if ocr is not None:
                self.set_ocr_text(ocr.text)
            self._answer_text = str(getattr(result, "answer", result))
            self.answer_edit.setPlainText(self._answer_text)
        self.set_status("完成")
        self.copy_button.setEnabled(bool(self._answer_text))
        self._disable_auto_watch_job_controls()

    def show_auto_watch_error(self, generation: int, message: str) -> None:
        if not self._auto_watch_active or generation < self._auto_watch_generation:
            return
        self._auto_watch_generation = generation
        if not self._answer_text:
            self.answer_edit.setPlainText(f"AI 解析失败。\n{message}")
        self.set_status(f"失败：{message}")
        self._disable_auto_watch_job_controls()

    def show_auto_watch_cancelled(self, generation: int) -> None:
        if not self._auto_watch_active or generation < self._auto_watch_generation:
            return
        self._auto_watch_generation = generation
        self.set_status("Analysis cancelled")
        self._disable_auto_watch_job_controls()

    def end_auto_watch(self) -> None:
        if self._auto_watch_previous_geometry is not None:
            self.setGeometry(self._auto_watch_previous_geometry)
            self._geometry_restored = self._auto_watch_previous_geometry_restored
        self._auto_watch_previous_geometry = None
        self._auto_watch_active = False
        self._auto_watch_generation = None
        self._auto_watch_roi = None
        self._auto_watch_screen = None
        self._auto_watch_user_moved = False
        self._skip_geometry_save = False
        self.stop_button.setVisible(False); self.stop_button.setEnabled(False)
        self.retry_button.setVisible(True)
        self.recapture_button.setVisible(False); self.recapture_button.setEnabled(False)
        self.set_retry_enabled()

    def _disable_auto_watch_job_controls(self) -> None:
        self.stop_button.setVisible(False); self.stop_button.setEnabled(False)
        self.retry_button.setVisible(False); self.retry_button.setEnabled(False)
        self.recapture_button.setVisible(False); self.recapture_button.setEnabled(False)

    def _mark_auto_watch_user_moved(self) -> None:
        if self._auto_watch_active:
            self._auto_watch_user_moved = True

    def _place_auto_watch_window(self) -> None:
        if self._auto_watch_roi is None:
            self.show()
            return
        screen = self._auto_watch_screen or QGuiApplication.primaryScreen()
        if screen is None:
            self.show()
            return
        self.show()
        self.adjustSize()
        current = self.geometry()
        available = screen.availableGeometry()
        if not self._auto_watch_user_moved or not current.intersects(available):
            self.setGeometry(place_answer_window(current, self._auto_watch_roi, available, 12))

    def show_vision_processing(self) -> None:
        self._skip_geometry_save = False
        self.set_mode(AnalysisMode.VISION)
        self._answer_text = ""
        self.answer_edit.clear()
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.recapture_button.setVisible(False)
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(True)
        self.set_status("正在分析截图...")
        self.show_at_current_screen()

    def set_mode(self, mode: AnalysisMode | str) -> None:
        """Show only the UI relevant to the selected analysis pipeline."""

        self._vision_mode = mode is AnalysisMode.VISION or str(mode) in {
            AnalysisMode.VISION.value,
            "AnalysisMode.VISION",
        }
        self.ocr_section_label.setVisible(not self._vision_mode)
        self.ocr_edit.setVisible(not self._vision_mode)
        self.ocr_card.setVisible(not self._vision_mode)
        self.title_bar.set_mode(AnalysisMode.VISION if self._vision_mode else AnalysisMode.TEXT)
        if self._vision_mode:
            self._ocr_text = ""
            self.ocr_edit.clear()

    def set_ocr_processing(self) -> None:
        self.set_status("正在识别题目...")
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(True)

    def show_at_current_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        self.show()
        if screen is not None and not self._geometry_restored:
            available = screen.availableGeometry()
            self.move(available.right() - self.width() - 18, available.top() + 40)
        self.raise_()
        self.activateWindow()

    def _restore_saved_geometry(self) -> None:
        geometry = self._settings_repository.load().get("answer_window_geometry")
        if not isinstance(geometry, dict):
            return
        rect = QRect(
            geometry["x"],
            geometry["y"],
            max(360, geometry["width"]),
            max(420, geometry["height"]),
        )
        screens = QGuiApplication.screens()
        if screens and not any(rect.intersects(screen.availableGeometry()) for screen in screens):
            return
        self.setGeometry(rect)
        self._geometry_restored = True

    def _save_geometry(self) -> None:
        rect = self.geometry()
        try:
            self._settings_repository.update(
                {
                    "answer_window_geometry": {
                        "x": rect.x(),
                        "y": rect.y(),
                        "width": rect.width(),
                        "height": rect.height(),
                    }
                }
            )
        except (OSError, ValueError):
            logger.exception("failed to save answer window geometry")

    def set_status(self, status: str) -> None:
        mapping = {
            "等待处理": ("●  Ready", "ready"),
            "正在识别题目...": ("◌  Recognizing text…", "busy"),
            "正在请求 AI...": ("◌  Analyzing…", "busy"),
            "正在分析截图...": ("◌  Analyzing image…", "busy"),
            "正在取消...": ("◌  Cancelling…", "busy"),
            "已取消": ("■  Cancelled", "cancelled"),
            "完成": ("✓  Analysis completed", "complete"),
            "答案已复制": ("✓  Copied", "complete"),
        }
        if status.startswith("失败："):
            text, state = "!  Analysis failed", "error"
        else:
            text, state = mapping.get(status, (status, "busy"))
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def set_ocr_text(self, text: str) -> None:
        self._ocr_text = text
        self.ocr_edit.setPlainText(text)

    def set_ai_processing(self) -> None:
        self._answer_text = ""
        self.set_status("正在请求 AI...")
        self.answer_edit.clear()
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.recapture_button.setVisible(False)
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(True)

    def set_vision_ai_processing(self) -> None:
        self._answer_text = ""
        self.set_status("正在分析截图...")
        self.answer_edit.clear()
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.recapture_button.setVisible(False)
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(True)

    def set_cancelling(self) -> None:
        self.set_status("正在取消...")
        self.stop_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.recapture_button.setVisible(False)

    def show_cancelled(self) -> None:
        self._answer_text = ""
        self.answer_edit.setPlainText("已取消，未生成 AI 答案。")
        self.set_status("已取消")
        self.stop_button.setVisible(False)
        self.stop_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(self._vision_mode or bool(self._ocr_text))
        self.recapture_button.setVisible(True)
        self.recapture_button.setEnabled(True)

    def set_result(self, answer: str) -> None:
        self._answer_text = answer
        self.answer_edit.setPlainText(answer)
        self.set_status("完成")
        self.stop_button.setVisible(False)
        self.stop_button.setEnabled(False)
        self.recapture_button.setVisible(False)
        self.copy_button.setEnabled(bool(answer))
        self.retry_button.setEnabled(self._vision_mode or bool(self._ocr_text))

    def show_error(self, message: str) -> None:
        self._answer_text = ""
        self.answer_edit.setPlainText(f"AI 解析失败。\n{message}")
        self.set_status(f"失败：{message}")
        self.stop_button.setVisible(False)
        self.stop_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.recapture_button.setVisible(False)
        self.retry_button.setEnabled(self._vision_mode or bool(self._ocr_text))

    def set_retry_enabled(self, enabled: bool | None = None) -> None:
        source_available = self._vision_mode or bool(self._ocr_text)
        self.retry_button.setEnabled(source_available if enabled is None else enabled and source_available)

    def copy_answer(self) -> None:
        if not self._answer_text:
            return
        QApplication.clipboard().setText(self._answer_text)
        self.set_status("答案已复制")

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.key() == Qt.Key.Key_Escape and self.stop_button.isVisible() and self.stop_button.isEnabled():
            self.stop_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not self._skip_geometry_save:
            self._save_geometry()
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()
        super().closeEvent(event)
