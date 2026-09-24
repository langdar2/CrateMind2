from enum import Enum


class DiffResult(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


def classify_file(mtime: float, size: int, existing_row: dict | None) -> DiffResult:
    if existing_row is None:
        return DiffResult.NEW
    if existing_row["mtime"] != mtime or existing_row["size"] != size:
        return DiffResult.CHANGED
    return DiffResult.UNCHANGED


def find_deleted(db_paths: set, fs_paths: set) -> set:
    return db_paths - fs_paths
