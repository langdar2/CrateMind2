import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from crate_mind.analysis.diff import DiffResult, classify_file


def test_classify_file_new_when_no_existing_row():
    assert classify_file(1.0, 100, None) == DiffResult.NEW


def test_classify_file_changed_when_mtime_or_size_differ():
    row = {"mtime": 1.0, "size": 100, "status": "ok"}
    assert classify_file(2.0, 100, row) == DiffResult.CHANGED
    assert classify_file(1.0, 200, row) == DiffResult.CHANGED


def test_classify_file_unchanged_when_ok_and_untouched():
    row = {"mtime": 1.0, "size": 100, "status": "ok"}
    assert classify_file(1.0, 100, row) == DiffResult.UNCHANGED


def test_classify_file_retries_failed_or_pending_even_if_untouched():
    for status in ("failed", "pending"):
        row = {"mtime": 1.0, "size": 100, "status": status}
        assert classify_file(1.0, 100, row) == DiffResult.CHANGED


if __name__ == "__main__":
    test_classify_file_new_when_no_existing_row()
    test_classify_file_changed_when_mtime_or_size_differ()
    test_classify_file_unchanged_when_ok_and_untouched()
    test_classify_file_retries_failed_or_pending_even_if_untouched()
    print("All diff tests passed.")
