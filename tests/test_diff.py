import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crate_mind.analysis.diff import classify_file, find_deleted, DiffResult


def test_new_file_has_no_existing_row():
    result = classify_file(mtime=100.0, size=2048, existing_row=None)
    assert result == DiffResult.NEW


def test_changed_file_has_different_mtime():
    existing = {"mtime": 100.0, "size": 2048, "status": "ok"}
    result = classify_file(mtime=200.0, size=2048, existing_row=existing)
    assert result == DiffResult.CHANGED


def test_changed_file_has_different_size():
    existing = {"mtime": 100.0, "size": 2048, "status": "ok"}
    result = classify_file(mtime=100.0, size=4096, existing_row=existing)
    assert result == DiffResult.CHANGED


def test_unchanged_file_matches_existing_row():
    existing = {"mtime": 100.0, "size": 2048, "status": "ok"}
    result = classify_file(mtime=100.0, size=2048, existing_row=existing)
    assert result == DiffResult.UNCHANGED


def test_previously_failed_file_is_unchanged_if_still_same():
    existing = {"mtime": 100.0, "size": 2048, "status": "failed"}
    result = classify_file(mtime=100.0, size=2048, existing_row=existing)
    assert result == DiffResult.UNCHANGED


def test_find_deleted_returns_paths_missing_from_filesystem():
    db_paths = {"/music/a.mp3", "/music/b.mp3", "/music/c.mp3"}
    fs_paths = {"/music/a.mp3", "/music/c.mp3"}
    assert find_deleted(db_paths, fs_paths) == {"/music/b.mp3"}


def test_find_deleted_returns_empty_set_when_nothing_removed():
    db_paths = {"/music/a.mp3"}
    fs_paths = {"/music/a.mp3"}
    assert find_deleted(db_paths, fs_paths) == set()


if __name__ == "__main__":
    test_new_file_has_no_existing_row()
    test_changed_file_has_different_mtime()
    test_changed_file_has_different_size()
    test_unchanged_file_matches_existing_row()
    test_previously_failed_file_is_unchanged_if_still_same()
    test_find_deleted_returns_paths_missing_from_filesystem()
    test_find_deleted_returns_empty_set_when_nothing_removed()
    print("All diff tests passed.")
