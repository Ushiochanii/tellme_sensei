"""In-memory image composition for Context + Question Vision analysis."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter


def compose_context_question_image(context_image: QImage, question_image: QImage) -> QImage:
    """Stack two screenshots with labels and a separator without touching disk."""

    context_image = _validated_copy(context_image, "context_image")
    question_image = _validated_copy(question_image, "question_image")

    margin = 16
    label_height = 32
    separator_height = 8
    width = max(context_image.width(), question_image.width()) + margin * 2
    height = (
        margin
        + label_height
        + context_image.height()
        + separator_height
        + label_height
        + question_image.height()
        + margin
    )
    composite = QImage(width, height, QImage.Format.Format_RGBA8888)
    composite.fill(QColor("white"))

    painter = QPainter(composite)
    try:
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont()
        font.setBold(True)
        painter.setFont(font)

        y = margin
        painter.fillRect(QRect(margin, y, width - margin * 2, label_height), QColor("#e8eef8"))
        if QGuiApplication.instance() is not None:
            painter.setPen(QColor("#16345c"))
            painter.drawText(
                QRect(margin + 8, y, width - margin * 2 - 16, label_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "CONTEXT",
            )
        y += label_height
        painter.drawImage(QPoint(margin, y), context_image)
        y += context_image.height()

        painter.fillRect(QRect(margin, y, width - margin * 2, separator_height), QColor("#8094af"))
        y += separator_height

        painter.fillRect(QRect(margin, y, width - margin * 2, label_height), QColor("#f5ead6"))
        if QGuiApplication.instance() is not None:
            painter.setPen(QColor("#674613"))
            painter.drawText(
                QRect(margin + 8, y, width - margin * 2 - 16, label_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "QUESTION",
            )
        y += label_height
        painter.drawImage(QPoint(margin, y), question_image)
    finally:
        painter.end()
    return composite


def _validated_copy(image: QImage, name: str) -> QImage:
    if not isinstance(image, QImage) or image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError(f"{name} must be a non-empty QImage")
    return image.copy()


__all__ = ["compose_context_question_image"]
