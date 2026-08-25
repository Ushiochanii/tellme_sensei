"""Frameless, always-on-top answer window with cancellable-job controls."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
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
from app.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)


class _TitleBar(QWidget):
    """Small custom title bar that makes the frameless window draggable."""

    def __init__(self, title: str, close_callback, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 6, 6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleLabel")
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        close_button = QToolButton()
        close_button.setText("×")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(close_callback)
        layout.addWidget(close_button)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
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
        self.resize(450, 600)
        self._restore_saved_geometry()
        self._ocr_text = ""
        self._answer_text = ""
        self._vision_mode = False
        self._closed_emitted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = _TitleBar("AI 学习助手", self.close, self)
        root.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 10, 14, 8)
        body_layout.setSpacing(6)

        self.status_label = QLabel("状态：等待处理")
        self.status_label.setObjectName("statusLabel")
        body_layout.addWidget(self.status_label)

        self.ocr_section_label = self._section_label("识别题目")
        body_layout.addWidget(self.ocr_section_label)
        self.ocr_edit = QPlainTextEdit()
        self.ocr_edit.setReadOnly(True)
        self.ocr_edit.setPlaceholderText("截图后将在这里显示 OCR 文本。")
        self.ocr_edit.setMaximumHeight(150)
        body_layout.addWidget(self.ocr_edit)

        body_layout.addWidget(self._section_label("AI 解析"))
        self.answer_edit = QPlainTextEdit()
        self.answer_edit.setReadOnly(True)
        self.answer_edit.setPlaceholderText("正在等待 AI 解析……")
        self.answer_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        body_layout.addWidget(self.answer_edit, 1)
        root.addWidget(body, 1)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 6, 8)
        self.copy_button = QPushButton("复制答案")
        self.retry_button = QPushButton("重新分析")
        self.stop_button = QPushButton("停止")
        self.recapture_button = QPushButton("重新截图")
        close_button = QPushButton("关闭")
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
        root.addWidget(footer)

        self.setStyleSheet(
            """
            AnswerWindow { background: #f7f8fa; border: 1px solid #8b95a5; }
            #titleLabel { font-size: 15px; font-weight: 600; color: #000000; }
            #closeButton { color: #000000; border: none; font-size: 20px; padding: 0 7px; }
            #closeButton:hover { background: #d9534f; }
            _TitleBar { background: #ffffff; }
            #statusLabel { color: #335c8a; font-weight: 600; }
            QPlainTextEdit { background: #ffffff; color: #000000; border: 1px solid #d4d9e1; border-radius: 4px; padding: 5px; }
            QPushButton { min-height: 28px; padding: 2px 10px; }
            """
        )

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(f"▼ {text}")
        label.setStyleSheet("font-weight: 600; color: #344054; margin-top: 4px;")
        return label

    def show_processing(self) -> None:
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

    def show_vision_processing(self) -> None:
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
        self.status_label.setText(f"状态：{status}")

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
        self._save_geometry()
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()
        super().closeEvent(event)
