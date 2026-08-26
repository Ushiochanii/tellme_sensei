"""Small visual theme primitives for the Full floating controller."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QPushButton


# Soft blue/lavender palette used only by the v0.7.1 controller in Phase 1.
BACKGROUND = "#eef4ff"
PANEL = "#f8fbff"
TEXT = "#172b63"
SECONDARY_TEXT = "#60739a"
TEXT_ACCENT = "#2f6fe4"
VISION_ACCENT = "#6546d8"
BORDER = "#c9d8f7"
SUCCESS = "#20a35a"
DANGER = "#c85b68"
CARD = "#fbfdff"
CARD_BORDER = "#d6e2f8"
FOCUS_BORDER = "#8bb2f2"

RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 18

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 20

FONT_SMALL = 10
FONT_BODY = 12
FONT_TITLE = 16


def answer_window_stylesheet() -> str:
    """Return the AnswerWindow stylesheet using the shared visual tokens."""

    return f"""
    QWidget#answerWindow {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #edf5ff, stop:1 #f1edff);
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_LG}px;
    }}
    QWidget#answerTitleBar {{
        background: rgba(255, 255, 255, 150);
        border-bottom: 1px solid rgba(201, 216, 247, 180);
        border-top-left-radius: {RADIUS_LG}px;
        border-top-right-radius: {RADIUS_LG}px;
    }}
    QLabel#answerTitleLabel {{
        color: {TEXT};
        font-size: {FONT_TITLE}px;
        font-weight: 700;
    }}
    QToolButton#closeButton {{
        color: {SECONDARY_TEXT};
        background: transparent;
        border: none;
        border-radius: {RADIUS_SM}px;
        font-size: 20px;
        padding: 2px 8px;
    }}
    QToolButton#closeButton:hover {{
        color: {DANGER};
        background: rgba(216, 113, 126, 35);
    }}
    QLabel#statusLabel {{
        color: {SECONDARY_TEXT};
        background: rgba(255, 255, 255, 155);
        border: 1px solid rgba(201, 216, 247, 170);
        border-radius: {RADIUS_MD}px;
        padding: 8px 12px;
        font-size: {FONT_BODY}px;
        font-weight: 600;
    }}
    QLabel#statusLabel[state="ready"], QLabel#statusLabel[state="complete"] {{ color: {SUCCESS}; }}
    QLabel#statusLabel[state="error"] {{ color: {DANGER}; }}
    QFrame#ocrCard, QFrame#answerCard {{
        background: rgba(255, 255, 255, 190);
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS_LG}px;
    }}
    QFrame#answerCard {{
        background: rgba(255, 255, 255, 220);
        border-color: #c9d8f7;
    }}
    QLabel#sectionTitle {{
        color: {SECONDARY_TEXT};
        font-size: {FONT_BODY}px;
        font-weight: 700;
    }}
    QLabel#answerSectionTitle {{ color: {TEXT}; }}
    QPlainTextEdit#ocrEdit, QPlainTextEdit#answerEdit {{
        background: {CARD};
        color: {TEXT};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS_MD}px;
        padding: 10px;
        selection-background-color: #cfe0ff;
        selection-color: {TEXT};
        font-size: 13px;
    }}
    QPlainTextEdit#answerEdit {{ border-color: #c7d8f8; font-size: 14px; }}
    QPlainTextEdit#ocrEdit:focus, QPlainTextEdit#answerEdit:focus {{ border-color: {FOCUS_BORDER}; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 9px;
        margin: 4px 2px 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: #b9c9e6;
        min-height: 28px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #9fb6de; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QPushButton#copyButton, QPushButton#retryButton, QPushButton#recaptureButton,
    QPushButton#closeActionButton, QPushButton#stopButton {{
        min-height: 30px;
        padding: 4px 13px;
        border-radius: {RADIUS_MD}px;
        font-size: {FONT_SMALL + 2}px;
    }}
    QPushButton#copyButton, QPushButton#retryButton {{
        color: {TEXT}; background: rgba(255, 255, 255, 205); border: 1px solid {CARD_BORDER};
    }}
    QPushButton#copyButton:hover, QPushButton#retryButton:hover {{
        background: #eef5ff; border-color: {TEXT_ACCENT};
    }}
    QPushButton#recaptureButton {{
        color: {VISION_ACCENT}; background: rgba(239, 234, 255, 210); border: 1px solid #c7b8f4;
    }}
    QPushButton#recaptureButton:hover {{ background: #e9e0ff; border-color: {VISION_ACCENT}; }}
    QPushButton#stopButton {{
        color: {DANGER}; background: rgba(255, 241, 244, 210); border: 1px solid #efc5cc;
    }}
    QPushButton#stopButton:hover {{ background: #ffe7eb; border-color: {DANGER}; }}
    QPushButton#closeActionButton {{
        color: {SECONDARY_TEXT}; background: transparent; border: 1px solid transparent;
    }}
    QPushButton#closeActionButton:hover {{ background: rgba(255, 255, 255, 150); border-color: {CARD_BORDER}; }}
    QPushButton:disabled {{ color: #9aa8c2; background: rgba(242, 245, 252, 130); border-color: #dce4f2; }}
    QSizeGrip {{ width: 10px; height: 10px; }}
    """


def controller_stylesheet() -> str:
    """Return the controller-only stylesheet; other windows stay untouched."""

    return f"""
    QWidget#mainController {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #edf5ff, stop:1 #f1edff);
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_LG}px;
    }}
    QLabel#titleLabel {{
        color: {TEXT};
        font-size: {FONT_TITLE}px;
        font-weight: 700;
    }}
    QLabel#statusLabel {{
        color: {SECONDARY_TEXT};
        background: rgba(255, 255, 255, 150);
        border: 1px solid rgba(201, 216, 247, 180);
        border-radius: {RADIUS_MD}px;
        padding: 7px 10px;
    }}
    QLabel#statusLabel[state="ready"] {{ color: {SUCCESS}; }}
    QLabel#statusLabel[state="busy"] {{ color: {SECONDARY_TEXT}; }}
    QPushButton#textModeButton, QPushButton#visionModeButton {{
        color: {TEXT};
        background: rgba(255, 255, 255, 170);
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
        padding: 12px 10px;
        font-size: 13px;
        font-weight: 600;
        text-align: center;
    }}
    QPushButton#textModeButton:hover, QPushButton#visionModeButton:hover {{
        background: rgba(255, 255, 255, 230);
        border-color: #9bbcf4;
    }}
    QPushButton#textModeButton:pressed, QPushButton#visionModeButton:pressed {{
        background: rgba(225, 235, 255, 230);
    }}
    QPushButton#textModeButton:disabled, QPushButton#visionModeButton:disabled {{
        color: #9aa8c2;
        background: rgba(242, 245, 252, 150);
        border-color: #dce4f2;
    }}
    QPushButton#textModeButton {{
        border-color: #a9caf7;
        background: rgba(226, 239, 255, 190);
    }}
    QPushButton#textModeButton:hover {{ border-color: {TEXT_ACCENT}; }}
    QPushButton#visionModeButton {{
        border-color: #c7b8f4;
        background: rgba(238, 230, 255, 190);
    }}
    QPushButton#visionModeButton:hover {{ border-color: {VISION_ACCENT}; }}
    QPushButton#settingsButton {{
        color: {SECONDARY_TEXT};
        background: transparent;
        border: none;
        padding: 4px;
        font-size: 15px;
    }}
    QPushButton#settingsButton:hover {{
        color: {TEXT_ACCENT};
        background: rgba(255, 255, 255, 150);
        border-radius: {RADIUS_SM}px;
    }}
    """


def mode_icon(kind: str, color: str, size: int = 24) -> QPixmap:
    """Draw a tiny platform-independent mode mark without external assets."""

    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 2)
    painter.setPen(pen)
    if kind == "vision":
        painter.drawEllipse(2, 6, size - 4, size - 12)
        painter.setBrush(QColor(color))
        painter.drawEllipse(size // 2 - 3, size // 2 - 3, 6, 6)
    else:
        arm = 5
        painter.drawLine(3, 3, 3 + arm, 3)
        painter.drawLine(3, 3, 3, 3 + arm)
        painter.drawLine(size - 3, 3, size - 3 - arm, 3)
        painter.drawLine(size - 3, 3, size - 3, 3 + arm)
        painter.drawLine(3, size - 3, 3 + arm, size - 3)
        painter.drawLine(3, size - 3, 3, size - 3 - arm)
        painter.drawLine(size - 3, size - 3, size - 3 - arm, size - 3)
        painter.drawLine(size - 3, size - 3, size - 3, size - 3 - arm)
    painter.end()
    return pixmap


def settings_icon(color: str = SECONDARY_TEXT, size: int = 18) -> QPixmap:
    """Draw a small gear mark without relying on platform icon themes."""

    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.7))
    center = size / 2
    painter.translate(center, center)
    for angle in range(0, 360, 45):
        painter.save()
        painter.rotate(angle)
        painter.drawRoundedRect(QRectF(-2, -center + 1, 4, 5), 1, 1)
        painter.restore()
    painter.drawEllipse(QRectF(-center + 4, -center + 4, size - 8, size - 8))
    painter.setBrush(QColor("transparent"))
    painter.drawEllipse(QRectF(-2.5, -2.5, 5, 5))
    painter.end()
    return pixmap


class ModeButton(QPushButton):
    """Compact glass card with a centered icon, title, and shortcut pill."""

    def __init__(self, title: str, shortcut: str, icon: QPixmap, accent: str, *, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._shortcut = shortcut
        self._icon = icon
        self._accent = QColor(accent)
        self.setText(f"{title}\n{shortcut}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(108)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_shortcut(self, shortcut: str) -> None:
        self._shortcut = shortcut
        self.setText(f"{self._title}\n{shortcut}")
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = self._accent
        if not self.isEnabled():
            accent = QColor("#aab6cc")
        gradient = QLinearGradient(outer.topLeft(), outer.bottomRight())
        gradient.setColorAt(0.0, QColor(255, 255, 255, 215))
        gradient.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 38))
        painter.setBrush(gradient)
        border = QColor(accent)
        border.setAlpha(95 if self.isEnabled() else 45)
        if self.underMouse() and self.isEnabled():
            border.setAlpha(180)
        painter.setPen(QPen(border, 1.2))
        painter.drawRoundedRect(outer, 15, 15)

        icon_size = self._icon.size()
        painter.drawPixmap(
            int((self.width() - icon_size.width()) / 2),
            12,
            self._icon,
        )
        text_color = QColor(TEXT if self.isEnabled() else "#9aa8c2")
        painter.setPen(text_color)
        title_font = QFont(self.font())
        title_font.setPointSize(12)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(QRectF(4, 43, self.width() - 8, 22), Qt.AlignmentFlag.AlignCenter, self._title)

        pill = QRectF(10, self.height() - 34, self.width() - 20, 24)
        pill_color = QColor(255, 255, 255, 150 if self.isEnabled() else 90)
        painter.setBrush(pill_color)
        pill_border = QColor(accent)
        pill_border.setAlpha(80 if self.isEnabled() else 35)
        painter.setPen(QPen(pill_border, 1))
        painter.drawRoundedRect(pill, 9, 9)
        shortcut_font = QFont(self.font())
        shortcut_font.setPointSize(9)
        painter.setFont(shortcut_font)
        painter.setPen(QColor(accent if self.isEnabled() else "#9aa8c2"))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self._shortcut)
        painter.end()
