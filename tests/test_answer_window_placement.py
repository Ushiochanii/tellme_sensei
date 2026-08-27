from PySide6.QtCore import QRect

from app.ui.answer_window_placement import place_answer_window


def test_places_right_before_other_directions() -> None:
    result = place_answer_window(QRect(0, 0, 80, 60), QRect(100, 100, 40, 40), QRect(0, 0, 300, 300), 10)
    assert result == QRect(150, 100, 80, 60)


def test_places_left_when_right_primary_axis_does_not_fit() -> None:
    result = place_answer_window(QRect(0, 0, 80, 60), QRect(250, 100, 40, 40), QRect(0, 0, 300, 300), 10)
    assert result == QRect(160, 100, 80, 60)


def test_places_down_when_horizontal_primary_axes_do_not_fit() -> None:
    result = place_answer_window(QRect(0, 0, 250, 60), QRect(100, 50, 40, 40), QRect(0, 0, 300, 300), 10)
    assert result == QRect(50, 100, 250, 60)


def test_places_up_when_other_primary_axes_do_not_fit() -> None:
    result = place_answer_window(QRect(0, 0, 250, 60), QRect(100, 250, 40, 40), QRect(0, 0, 300, 300), 10)
    assert result == QRect(50, 180, 250, 60)


def test_fallback_uses_corner_with_smallest_overlap() -> None:
    screen = QRect(0, 0, 200, 200)
    roi = QRect(40, 40, 140, 140)
    result = place_answer_window(QRect(0, 0, 80, 80), roi, screen, 10)
    assert result == QRect(0, 0, 80, 80)
    assert result.intersected(roi).width() * result.intersected(roi).height() == 1600


def test_clamps_to_negative_available_geometry() -> None:
    screen = QRect(-500, -300, 200, 150)
    result = place_answer_window(QRect(0, 0, 300, 200), QRect(-450, -260, 180, 100), screen, 10)
    assert result == screen
