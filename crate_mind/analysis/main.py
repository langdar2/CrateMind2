import os
import time
import traceback

from crate_mind.analysis import db, diff, features, scan


def run_cycle(conn, music_dir: str) -> None:
    fs_entries = scan.scan_music_dir(music_dir)
    fs_paths = set(fs_entries.keys())
    db_paths = db.all_track_paths(conn)

    for deleted_path in diff.find_deleted(db_paths, fs_paths):
        db.delete_track(conn, deleted_path)
        print(f"Removed (deleted from disk): {deleted_path}")

    for path, (mtime, size) in fs_entries.items():
        existing_row = db.get_track_row(conn, path)
        result = diff.classify_file(mtime, size, existing_row)
        if result == diff.DiffResult.UNCHANGED:
            continue

        try:
            audio_16k, audio_44k = features.load_audio_for_analysis(path)
            extracted = features.extract_features(audio_16k, audio_44k)
            db.upsert_track(conn, path, mtime, size, status="ok")
            db.upsert_features(conn, path, extracted)
            print(f"Analyzed: {path}")
        except Exception as e:
            db.upsert_track(conn, path, mtime, size, status="failed", error_message=str(e))
            db.delete_features(conn, path)
            print(f"Failed to analyze: {path}")
            traceback.print_exc()


def main() -> None:
    music_dir = os.environ.get("MUSIC_DIR", "/music")
    db_path = os.environ.get("DB_PATH", "/data/library.db")
    interval = int(os.environ.get("SCAN_INTERVAL_SECONDS", "1800"))

    conn = db.get_connection(db_path)
    db.reset_failed_without_reason(conn)

    while True:
        print("Starting scan cycle...")
        run_cycle(conn, music_dir)
        print(f"Cycle complete. Sleeping {interval}s.")
        time.sleep(interval)


if __name__ == "__main__":
    main()
