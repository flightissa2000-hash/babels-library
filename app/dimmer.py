"""Dimming the screen while the sleep screen is up, and putting it back after.

Laptop screens: Windows' own brightness (WMI). Monitors on a cable: the monitor's own brightness setting, over
DDC/CI (dxva2), the same thing the buttons on the monitor change. What the brightness was before is written to
%LOCALAPPDATA%\\BabelsLibrary\\dimmed.json first, so if the app closes or crashes while dimmed, the next start puts
it back (restore_leftover). Monitors that don't answer are simply left alone (the page dims itself as well)."""
import ctypes
import json
import os
import subprocess
import threading
from ctypes import wintypes

STATE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "dimmed.json")
_lock = threading.Lock()


class _PHYS(ctypes.Structure):
    _fields_ = [("hPhysicalMonitor", wintypes.HANDLE), ("szPhysicalMonitorDescription", wintypes.WCHAR * 128)]


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
