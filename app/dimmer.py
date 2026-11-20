"""Dimming the screen while the sleep screen is up, and putting it back after.

Laptop screens: Windows' own brightness (WMI). Monitors on a cable: the monitor's own brightness setting, over
DDC/CI (dxva2), the same thing the buttons on the monitor change. What the brightness was before is written to
%LOCALAPPDATA%\\BabelsLibrary\\dimmed.json first, so if the app closes or crashes while dimmed, the next start puts
it back (restore_leftover). Monitors that don't answer are simply left alone (the page dims itself as well).

Linux: monitors over DDC/CI with ddcutil (sudo apt install ddcutil; your user in the i2c group), laptop screens with
brightnessctl. Without either, the page darkens itself."""
import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
if os.name == "nt":
    from ctypes import wintypes
else:
    wintypes = None

STATE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "dimmed.json")
_lock = threading.Lock()


if os.name == "nt":
    class _PHYS(ctypes.Structure):
        _fields_ = [("hPhysicalMonitor", wintypes.HANDLE), ("szPhysicalMonitorDescription", wintypes.WCHAR * 128)]


# ---- Linux: ddcutil (monitors on a cable) and brightnessctl (laptop screens)
def _run(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def _lx_displays():
    """ddcutil's display numbers that answer DDC/CI"""
    if not shutil.which("ddcutil"):
        return []
    code, out = _run(["ddcutil", "detect", "--brief"], 40)
    return re.findall(r"^Display (\d+)", out, re.M) if code == 0 else []


def _lx_get(n):
    code, out = _run(["ddcutil", "--display", n, "getvcp", "10", "--brief"])
    m = re.search(r"VCP 10 C (\d+) (\d+)", out) if code == 0 else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def _lx_dim(level):
    before = {"lx_ddc": [], "lx_bl": None}
    for n in _lx_displays():
        b = _lx_get(n)
        if b:
            before["lx_ddc"].append({"n": n, "v": b[0]})
    if shutil.which("brightnessctl"):
        code, out = _run(["brightnessctl", "-m"])          # name,class,current,percent,max
        parts = out.strip().split(",") if code == 0 else []
        if len(parts) >= 5 and parts[2].isdigit():
            before["lx_bl"] = int(parts[2])
    if not before["lx_ddc"] and before["lx_bl"] is None:
        return {"ok": False}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(before, f)
    for m in before["lx_ddc"]:
        _run(["ddcutil", "--display", m["n"], "setvcp", "10", str(max(0, int(round(m["v"] * level))))])
    if before["lx_bl"] is not None:
        _run(["brightnessctl", "-q", "set", str(max(1, int(before["lx_bl"] * level)))])
    return {"ok": True, "before": before}


def _lx_restore(before):
    for m in before.get("lx_ddc", []):
        _run(["ddcutil", "--display", m["n"], "setvcp", "10", str(int(m["v"]))])
    if before.get("lx_bl") is not None:
        _run(["brightnessctl", "-q", "set", str(int(before["lx_bl"]))])


def _monitors():
    """[(physical handle, description)] for every monitor (caller must close them with _close)."""
    if os.name != "nt":
        return []
    user32, dxva2 = ctypes.windll.user32, ctypes.windll.dxva2
    hmons = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.EnumDisplayMonitors(None, None, PROC(lambda h, dc, r, l: hmons.append(h) or True), 0)
    out = []
    for h in hmons:
        n = wintypes.DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(h, ctypes.byref(n)) or not n.value:
            continue
        arr = (_PHYS * n.value)()
        if dxva2.GetPhysicalMonitorsFromHMONITOR(h, n.value, arr):
            out += [(arr[i].hPhysicalMonitor, arr[i].szPhysicalMonitorDescription) for i in range(n.value)]
    return out


def _close(mons):
    for h, _ in mons:
        try:
            ctypes.windll.dxva2.DestroyPhysicalMonitor(h)
        except Exception:
            pass


def _ddc_get(h):
    lo, cur, hi = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    if ctypes.windll.dxva2.GetMonitorBrightness(h, ctypes.byref(lo), ctypes.byref(cur), ctypes.byref(hi)):
        return lo.value, cur.value, hi.value
    return None


def _wmi(cmd):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip()
    except Exception:
        return ""


def status():
    mons = _monitors()
    try:
        return [{"name": d, "brightness": _ddc_get(h)} for h, d in mons]
    finally:
        _close(mons)


def dim(level=0.2):
    """Down to `level` of what each screen is at now (at least the monitor's lowest). Remembers what it was."""
    with _lock:
        if os.path.isfile(STATE):
            return {"ok": True, "already": True}
        if os.name != "nt":
            return _lx_dim(level)
        before = {"ddc": [], "wmi": None}
        mons = _monitors()
        try:
            for i, (h, d) in enumerate(mons):
                b = _ddc_get(h)
                if not b:
                    continue
                lo, cur, hi = b
                before["ddc"].append({"i": i, "name": d, "v": cur})
            w = _wmi("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | Select -First 1).CurrentBrightness")
            if w.isdigit():
                before["wmi"] = int(w)
            if not before["ddc"] and before["wmi"] is None:
                return {"ok": False}
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump(before, f)
            for m in before["ddc"]:
                h = mons[m["i"]][0]
                lo, cur, hi = _ddc_get(h) or (0, m["v"], 100)
                ctypes.windll.dxva2.SetMonitorBrightness(h, max(lo, int(round(cur * level))))
            if before["wmi"] is not None:
                _wmi(f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1,{max(0, int(before['wmi'] * level))}) | Out-Null")
            return {"ok": True, "before": before}
        finally:
            _close(mons)


def restore():
    """Back to what it was before dim()."""
    with _lock:
        try:
            with open(STATE, encoding="utf-8") as f:
                before = json.load(f)
        except Exception:
            return {"ok": True, "nothing": True}
        if os.name != "nt":
            _lx_restore(before)
            try:
                os.remove(STATE)
            except OSError:
                pass
            return {"ok": True, "restored": before}
        mons = _monitors()
        try:
            for m in before.get("ddc", []):
                # the same monitor (by its place and name): monitors plugged in or out meanwhile are skipped
                if m["i"] < len(mons) and mons[m["i"]][1] == m["name"]:
                    ctypes.windll.dxva2.SetMonitorBrightness(mons[m["i"]][0], int(m["v"]))
            if before.get("wmi") is not None:
                _wmi(f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1,{int(before['wmi'])}) | Out-Null")
        finally:
            _close(mons)
        try:
            os.remove(STATE)
        except OSError:
            pass
        return {"ok": True, "restored": before}


def restore_leftover():
    """At start: the app closed while the screen was dimmed: put it back."""
    if os.path.isfile(STATE):
        threading.Thread(target=restore, daemon=True).start()
