"""Small interactive controller positioned outside a watched ROI."""
from __future__ import annotations
import sys
from collections.abc import Iterable
from PySide6.QtCore import QRect, Signal, Qt
from PySide6.QtWidgets import QFrame, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout
from app.analysis import AnalysisMode
from app.auto_watch.models import MonitorState
from app.localization import DEFAULT_INTERFACE_LANGUAGE, normalize_language, tr
from app.ui.theme import watch_mini_controller_stylesheet

def _place_mini_controller_single(global_roi: QRect, available: QRect, size, margin=8) -> QRect:
    w, h = size.width(), size.height()
    raw = [QRect(global_roi.left(), global_roi.bottom()+margin, w,h), QRect(global_roi.left(), global_roi.top()-margin-h,w,h),
            QRect(global_roi.right()+margin, global_roi.top(),w,h), QRect(global_roi.left()-margin-w,global_roi.top(),w,h)]

    def clamp(rect):
        if available.width() <= 0 or available.height() <= 0:
            return QRect()
        clamped_w, clamped_h = min(w, available.width()), min(h, available.height())
        x = max(available.left(), min(rect.left(), available.right() - clamped_w + 1))
        y = max(available.top(), min(rect.top(), available.bottom() - clamped_h + 1))
        return QRect(x, y, clamped_w, clamped_h)

    candidates = [clamp(rect) for rect in raw]
    for candidate in candidates:
        if not candidate.intersects(global_roi):
            return candidate
    areas = [candidate.intersected(global_roi).width() * candidate.intersected(global_roi).height()
             for candidate in candidates]
    return candidates[areas.index(min(areas))]


def place_mini_controller_avoiding(avoid_rois: Iterable[QRect], available: QRect, size, margin=8) -> QRect:
    """Place the mini controller outside actual watched ROIs where possible."""
    rois = tuple(roi for roi in avoid_rois if isinstance(roi, QRect) and not roi.isEmpty())
    if not rois:
        return _place_mini_controller_single(QRect(), available, size, margin)
    if len(rois) == 1:
        return _place_mini_controller_single(rois[0], available, size, margin)

    width, height = size.width(), size.height()
    screen = available.normalized()
    max_x = screen.right() - width + 1
    max_y = screen.bottom() - height + 1

    def clamp(x, y):
        if screen.width() <= 0 or screen.height() <= 0:
            return QRect()
        return QRect(
            max(screen.left(), min(x, max_x)),
            max(screen.top(), min(y, max_y)),
            min(width, screen.width()),
            min(height, screen.height()),
        )

    candidates = []
    for roi in rois:
        candidates.extend(
            (
                clamp(roi.right() + 1 + margin, roi.top()),
                clamp(roi.left() - margin - width, roi.top()),
                clamp(roi.left(), roi.bottom() + 1 + margin),
                clamp(roi.left(), roi.top() - margin - height),
            )
        )

    def overlap(candidate):
        return sum(candidate.intersected(roi).width() * candidate.intersected(roi).height() for roi in rois)

    for candidate in candidates:
        if overlap(candidate) == 0:
            return candidate
    return min(candidates, key=overlap)


def place_mini_controller(global_roi: QRect, available: QRect, size, margin=8) -> QRect:
    """Backward-compatible single-ROI placement entry point."""

    if not isinstance(global_roi, QRect):
        return place_mini_controller_avoiding(global_roi, available, size, margin)
    return _place_mini_controller_single(global_roi, available, size, margin)

class WatchMiniController(QWidget):
    analyze_now_requested = Signal(); pause_requested = Signal(); resume_requested = Signal(); stop_requested = Signal()
    def __init__(self, parent=None, interface_language: str = DEFAULT_INTERFACE_LANGUAGE):
        super().__init__(parent); self.setObjectName("watchMiniController")
        self._interface_language = normalize_language(
            interface_language, default=DEFAULT_INTERFACE_LANGUAGE
        )
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setStyleSheet(watch_mini_controller_stylesheet())
        self.setAttribute(Qt.WA_TranslucentBackground); self._closing_from_session = False; self._paused = False
        self._analysis_mode_label = "Text / OCR"
        self._region_mode = "Single Region"
        self._generation = 0
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self.surface = QFrame(self); self.surface.setObjectName("watchMiniSurface")
        surface_layout = QVBoxLayout(self.surface); surface_layout.setContentsMargins(12, 9, 12, 9); surface_layout.setSpacing(6)
        self.status_dot = QLabel("●"); self.status_dot.setObjectName("watchMiniStatusDot")
        self.status_label = QLabel(self._tr("watch.status_arming")); self.status_label.setObjectName("watchMiniStatus")
        self.mode_label = QLabel("Text / OCR"); self.mode_label.setObjectName("watchMiniMode")
        # Expose the existing compact mode label under a region-aware name so
        # pair mode can be inspected without adding another controller row.
        self.region_mode_label = self.mode_label
        self.generation_label = QLabel("G0"); self.generation_label.setObjectName("watchMiniGeneration")
        self.analysis_label = QLabel(self._tr("watch.analysis_ready")); self.analysis_label.setObjectName("watchMiniAnalysis")
        status_row = QHBoxLayout(); status_row.setSpacing(6)
        for label in (self.status_dot, self.status_label, self.mode_label, self.generation_label): status_row.addWidget(label)
        status_row.addStretch(1); surface_layout.addLayout(status_row); surface_layout.addWidget(self.analysis_label)
        self.analyze_button = QPushButton(self._tr("watch.analyze_now")); self.analyze_button.setObjectName("watchMiniAnalyze")
        self.pause_button = QPushButton(self._tr("watch.pause")); self.pause_button.setObjectName("watchMiniPause")
        self.stop_button = QPushButton(self._tr("watch.stop")); self.stop_button.setObjectName("watchMiniStop")
        self.analyze_button.clicked.connect(self.analyze_now_requested); self.pause_button.clicked.connect(self._toggle_pause); self.stop_button.clicked.connect(self.stop_requested)
        button_row = QHBoxLayout(); button_row.setSpacing(6)
        for button in (self.analyze_button, self.pause_button, self.stop_button): button_row.addWidget(button)
        surface_layout.addLayout(button_row); layout.addWidget(self.surface)
        self.surface.adjustSize(); super().adjustSize(); self._sync_surface_geometry()

    def _tr(self, key: str, **values: object) -> str:
        return tr(key, self._interface_language, **values)

    def adjustSize(self):  # noqa: N802 - Qt API name
        super().adjustSize()
        if hasattr(self, "surface"):
            self._sync_surface_geometry()

    def _sync_surface_geometry(self):
        self.surface.setGeometry(self.rect())
    def show_for(self, screen, global_roi):
        self.adjustSize(); available = screen.availableGeometry(); self.setGeometry(place_mini_controller(global_roi, available, self.size())); self.show()
    def set_monitor_state(self, state):
        name = getattr(state, "name", str(state)); self._paused = name == "PAUSED"
        labels = {
            "WATCHING": self._tr("watch.status_watching"),
            "PAUSED": self._tr("watch.status_paused"),
            "CHANGING": self._tr("watch.status_changing"),
            "ARMING": self._tr("watch.status_arming"),
            "STOPPED": self._tr("watch.status_stopped"),
        }
        self.status_label.setText(labels.get(name, name.title()))
        self.pause_button.setText(
            self._tr("watch.resume" if self._paused else "watch.pause")
        )
        self.status_dot.setProperty("monitorState", name)
        self.status_dot.style().unpolish(self.status_dot); self.status_dot.style().polish(self.status_dot)
    def set_analysis_state(self, state):
        name = getattr(state, "name", str(state)).lower()
        labels = {
            "idle": self._tr("watch.analysis_ready"),
            "accepted": self._tr("watch.analysis_waiting"),
            "delay_schedule": self._tr("watch.analysis_waiting"),
            "started": self._tr("watch.analysis_analyzing"),
            "running": self._tr("watch.analysis_analyzing"),
            "context_ocr": self._tr("watch.analysis_context"),
            "question_ocr": self._tr("watch.analysis_question"),
            "finished": self._tr("watch.analysis_completed"),
            "result": self._tr("watch.analysis_completed"),
            "cancelled": self._tr("watch.analysis_cancelled"),
            "error": self._tr("watch.analysis_failed"),
        }
        self.analysis_label.setText(labels.get(name, str(state)))
    def set_generation(self, generation):
        self._generation = generation
        if self._region_mode == "Context + Question":
            self.generation_label.setText(
                self._tr("watch.generation_pair", generation=generation)
            )
        else:
            self.generation_label.setText(f"G{generation}")
    def set_mode(self, mode, region_mode=None):
        self._analysis_mode_label = "Vision" if AnalysisMode(mode) is AnalysisMode.VISION else "Text / OCR"
        if region_mode is not None:
            self.set_region_mode(region_mode)
        else:
            self._refresh_mode_label()

    def set_region_mode(self, region_mode):
        name = str(region_mode or "Single Region")
        if name.lower() in {"context_question", "context + question", "pair", "dual"}:
            self._region_mode = "Context + Question"
        else:
            self._region_mode = "Single Region"
        self.set_generation(self._generation)
        self._refresh_mode_label()

    def _refresh_mode_label(self):
        analysis = getattr(self, "_analysis_mode_label", self.mode_label.text())
        region = getattr(self, "_region_mode", "Single Region")
        self.mode_label.setText(
            analysis if region == "Single Region" else f"{analysis} · {region}"
        )

    def show_for_regions(self, screen, global_rois):
        self.adjustSize()
        available = screen.availableGeometry()
        self.setGeometry(place_mini_controller_avoiding(global_rois, available, self.size()))
        self.show()

    def set_pair_mode(self, enabled=True):
        self.set_region_mode("Context + Question" if enabled else "Single Region")

    @property
    def region_mode(self):
        return self._region_mode

    def request_stop(self): self.stop_requested.emit()
    def _toggle_pause(self):
        (self.resume_requested if self._paused else self.pause_requested).emit()
    def close_from_session(self): self._closing_from_session = True; self.close()
    def closeEvent(self, event):
        if not self._closing_from_session: self.stop_requested.emit()
        self._closing_from_session = False
        super().closeEvent(event)
    def mousePressEvent(self, event): super().mousePressEvent(event)
