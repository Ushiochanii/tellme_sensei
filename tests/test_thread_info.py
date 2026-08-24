from app import thread_info


def test_thread_info_does_not_require_qt_for_standalone_worker(monkeypatch) -> None:
    monkeypatch.setattr(thread_info, "QThread", None)

    value = thread_info.current_thread_info()

    assert "python_id=" in value
    assert "qt_object=<unavailable>" in value
    assert "qt_name=<python-only>" in value
