"""Moving Babel's Library to another folder or drive.

If a file `relocate.json` sits next to the `app` folder, Babel's Library finishes a move the first time it starts there:

    {"from": "C:\\Users\\me\\Documents\\Babel's Library", "library": "@/Library"}

1. Before the database opens, the old `library_data` (database, covers, window settings) is copied across.
2. Once the server is running, every file in the old library folder is moved into the new one (shown as a job
   with progress at the top of the window), and paths are saved in the portable form used on Windows and Linux.
"""
import json
import os
import shutil
import time


def _marker(root):
    return os.path.join(root, "relocate.json")


def copy_data_if_pending(root, data_dir):
    """Step 1. Returns the move settings when a move is under way, else None."""
    m = _marker(root)
    if not os.path.exists(m):
        return None
    try:
        with open(m, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print("[inkwell] relocate.json unreadable:", e)
        return None
    old_data = os.path.join(cfg.get("from") or "", "library_data")
    if not os.path.exists(os.path.join(data_dir, "library.db")):
        if os.path.isdir(old_data):
            print(f"[inkwell] copying library data from {old_data}")
            shutil.copytree(old_data, data_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.tmp", "Crashpad", "GPUCache", "Code Cache", "ShaderCache"))
        else:
            print("[inkwell] old library_data not found; starting a fresh library")
    return cfg


def finish(srv_log):
    """Step 2, run in the background after the server starts."""
    import files
    import importers
    import store

    root = store.ROOT
    m = _marker(root)
    if not os.path.exists(m):
        return
    with open(m, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("stage") == "done":
        return
    old_root = cfg.get("old_library") or store.expand_root(store.get_settings().get("library_folder"))
    new_root = store.expand_root(cfg.get("library") or "@/Library")
    cfg["old_library"] = old_root
    cfg["stage"] = "moving"
    with open(m, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    def job():
        os.makedirs(new_root, exist_ok=True)
        store.materialize_paths()       # current paths become full paths first
        store.set_settings({"library_folder": new_root})
        rows = [(i, p) for i, p, _, _ in store.all_file_paths() if p and os.path.isabs(p) and files.inside(p, old_root)]
        importers.JOB["total"] = len(rows)
        moved = failed = 0
        for item_id, p in rows:
            importers.JOB["current"] = os.path.basename(p)
            dest = os.path.join(new_root, os.path.relpath(p, old_root))
            try:
                if os.path.exists(p):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if os.path.exists(dest) and os.path.getsize(dest) != os.path.getsize(p):
                        dest = files.unique_path(os.path.dirname(dest), os.path.basename(dest))
                    if not os.path.exists(dest):
                        shutil.move(p, dest)
                    else:
                        os.remove(p)
                if os.path.exists(dest):
                    store.update_item(item_id, {"file_path": dest})
                    moved += 1
            except OSError as e:
                failed += 1
                print("[inkwell] couldn't move", p, e)
            importers.JOB["done"] += 1
            importers.JOB["added"] = moved
        # anything else in the old folder (subtitles, album art, files Babel's Library doesn't track)
        if os.path.isdir(old_root):
            for dirpath, _, names in os.walk(old_root):
                for n in names:
                    src = os.path.join(dirpath, n)
                    dest = os.path.join(new_root, os.path.relpath(src, old_root))
                    try:
                        if not os.path.exists(dest):
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            shutil.move(src, dest)
                    except OSError as e:
                        print("[inkwell] couldn't move", src, e)
            for dirpath, dirs, names in sorted(os.walk(old_root), key=lambda t: -len(t[0])):
                try:
                    if not os.listdir(dirpath):
                        os.rmdir(dirpath)
                except OSError:
                    pass
        store.compact_paths()
        cfg["stage"] = "done"
        cfg["finished_at"] = time.time()
        with open(m, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        # leave a note in the old install so it isn't used by mistake
        try:
            old_app = cfg.get("from")
            if old_app and os.path.isdir(old_app):
                with open(os.path.join(old_app, "MOVED.txt"), "w", encoding="utf-8") as f:
                    f.write(f"Babel's Library now lives at {root}\nIts library is at {new_root}\nThis old copy can be deleted.\n")
        except OSError:
            pass
        importers.JOB["message"] = (f"Moved your library to {new_root}: {moved} files"
                                    + (f", {failed} couldn't be moved (see Settings → library folder)" if failed else ""))

    try:
        importers.start_job("Moving your library", job)
    except ValueError:
        srv_log("Library move will continue after the current import finishes.", "import")
