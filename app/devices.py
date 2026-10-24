"""Phones and e-readers plugged in over USB (MTP), e.g. "This PC\\GoColor7\\Internal shared storage\\Books".

Windows shows these in File Explorer but gives them no drive letter, so ordinary file access can't see them.
devices.ps1 reaches them through the Windows Shell; files are copied off the device (never changed on it)
into a temporary folder and imported from there.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import files
import store

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "devices.ps1")
PREFIXES = ("this pc\\", "computer\\", "my computer\\", "::")


def is_device_path(p):
    if not p or not sys.platform.startswith("win"):
        return False
    q = p.strip().replace("/", "\\")
    return q.lower().startswith(PREFIXES) and not os.path.isdir(q)


def _run(cfg, on_line=None, timeout=120):
    if not sys.platform.startswith("win"):
        raise ValueError("Devices without a drive letter can only be read on Windows.")
    fd, cpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
                              "-File", SCRIPT, cpath], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=flags, encoding="utf-8", errors="replace")
        last = None
        start = time.time()
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("ok") is False:
                p.kill()
                raise ValueError(msg.get("error") or "Couldn't read the device.")
            if on_line:
                on_line(msg)
            last = msg
            if timeout and not on_line and time.time() - start > timeout:
                p.kill()
                raise ValueError("The device took too long to answer.")
        p.wait()
        if last is None:
            err = (p.stderr.read() or "").strip().splitlines()
            raise ValueError("Couldn't read the device." + (f" ({err[-1]})" if err else ""))
        return last
    finally:
        try:
            os.remove(cpath)
        except OSError:
            pass


def exts():
    return sorted({e.lower() for e in files.SUPPORTED})


def browse(path=""):
    return _run({"mode": "browse", "path": path or ""}).get("folders") or []


def preview(path):
    lst = _run({"mode": "list", "path": path, "exts": exts()}, timeout=300).get("files") or []
    counts = {}
    for f in lst:
        k = files.kind_for_ext(os.path.splitext(f["rel"])[1])
        counts[k] = counts.get(k, 0) + 1
    return {"folder": path, "total": len(lst), "by_kind": counts, "maybe_new": len(lst), "inside_library": False, "device": True}


def import_from(path):
    """Import job: copy each file off the device, add it to the library, then delete the temporary copy."""
    import importers
    job = importers.JOB
    tmp = os.path.join(store.DATA_DIR, "device_import", str(int(time.time())))
    os.makedirs(tmp, exist_ok=True)
    job["current"] = "Reading the device…"

    def on_line(msg):
        if "total" in msg:
            job["total"] = msg["total"]
        elif "rel" in msg:
            job["current"] = os.path.basename(msg["rel"])
            if msg.get("ok") and os.path.exists(msg["path"]):
                try:
                    _, new = importers._srv().import_file(msg["path"], os.path.basename(msg["path"]), origin="folder scan",
                                                          move=True, quiet=True)
                    job["added" if new else "skipped"] += 1
                except Exception as e:
                    job["errors"] += 1
                    print("[inkwell] device import error", msg["rel"], e)
            else:
                job["errors"] += 1
            job["done"] += 1
    try:
        _run({"mode": "copy", "path": path, "dest": tmp, "exts": exts()}, on_line=on_line, timeout=0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
