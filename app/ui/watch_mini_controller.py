"""Small interactive controller positioned outside a watched ROI."""
from __future__ import annotations
from PySide6.QtCore import QRect, Signal, Qt
from PySide6.QtWidgets import QFrame, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout
from app.analysis import AnalysisMode
from app.auto_watch.models import MonitorState
from app.ui.theme import watch_mini_controller_stylesheet

def place_mini_controller(global_roi: QRect, available: QRect, size, margin=8) -> QRect:
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

class WatchMiniController(QWidget):
    analyze_now_requested = Signal(); pause_requested = Signal(); resume_requested = Signal(); stop_requested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("watchMiniController")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setStyleSheet(watch_mini_controller_stylesheet())
        self.setAttribute(Qt.WA_TranslucentBackground); self._closing_from_session = False; self._paused = False
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self.surface = QFrame(self); self.surface.setObjectName("watchMiniSurface")
        surface_layout = QVBoxLayout(self.surface); surface_layout.setContentsMargins(12, 9, 12, 9); surface_layout.setSpacing(6)
        self.status_dot = QLabel("●"); self.status_dot.setObjectName("watchMiniStatusDot")
        self.status_label = QLabel("Arming"); self.status_label.setObjectName("watchMiniStatus")
        self.mode_label = QLabel("Text / OCR"); self.mode_label.setObjectName("watchMiniMode")
        self.generation_label = QLabel("G0"); self.generation_label.setObjectName("watchMiniGeneration")
        self.analysis_label = QLabel("Ready for changes"); self.analysis_label.setObjectName("watchMiniAnalysis")
        status_row = QHBoxLayout(); status_row.setSpacing(6)
        for label in (self.status_dot, self.status_label, self.mode_label, self.generation_label): status_row.addWidget(label)
        status_row.addStretch(1); surface_layout.addLayout(status_row); surface_layout.addWidget(self.analysis_label)
        self.analyze_button = QPushButton("Analyze Now"); self.analyze_button.setObjectName("watchMiniAnalyze")
        self.pause_button = QPushButton("Pause"); self.pause_button.setObjectName("watchMiniPause")
        self.stop_button = QPushButton("Stop"); self.stop_button.setObjectName("watchMiniStop")
        self.analyze_button.clicked.connect(self.analyze_now_requested); self.pause_button.clicked.connect(self._toggle_pause); self.stop_button.clicked.connect(self.stop_requested)
        button_row = QHBoxLayout(); button_row.setSpacing(6)
        for button in (self.analyze_button, self.pause_button, self.stop_button): button_row.addWidget(button)
        surface_layout.addLayout(button_row); layout.addWidget(self.surface)
        self.surface.adjustSize(); super().adjustSize(); self._sync_surface_geometry()

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
        labels = {"WATCHING": "Watching", "PAUSED": "Paused", "CHANGING": "Changing", "ARMING": "Arming", "STOPPED": "Stopped"}
        self.status_label.setText(labels.get(name, name.title())); self.pause_button.setText("Resume" if self._paused else "Pause")
        self.status_dot.setProperty("monitorState", name)
        self.status_dot.style().unpolish(self.status_dot); self.status_dot.style().polish(self.status_dot)
    def set_analysis_state(self, state):
        name = getattr(state, "name", str(state)).lower()
        labels = {"idle": "Ready for changes", "accepted": "Waiting to analyze", "delay_schedule": "Waiting to analyze",
                  "started": "Analyzing…", "running": "Analyzing…", "finished": "Last analysis completed",
                  "result": "Last analysis completed", "cancelled": "Analysis cancelled", "error": "Analysis failed"}
        self.analysis_label.setText(labels.get(name, str(state)))
    def set_generation(self, generation): self.generation_label.setText(f"G{generation}")
    def set_mode(self, mode): self.mode_label.setText("Vision" if AnalysisMode(mode) is AnalysisMode.VISION else "Text / OCR")
    def request_stop(self): self.stop_requested.emit()
    def _toggle_pause(self):
        (self.resume_requested if self._paused else self.pause_requested).emit()
    def close_from_session(self): self._closing_from_session = True; self.close()
    def closeEvent(self, event):
        if not self._closing_from_session: self.stop_requested.emit()
        self._closing_from_session = False
        super().closeEvent(event)
    def mousePressEvent(self, event): super().mousePressEvent(event)
