import os
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".aiff", ".alac"}


def scan_music_dir(root: str) -> dict:
    """Returns {absolute_path: (mtime, size)} for every audio file under root."""
    found = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, name)
            stat = os.stat(full_path)
            found[full_path] = (stat.st_mtime, stat.st_size)
    return found
