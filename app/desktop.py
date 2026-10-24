"""Babel's Library desktop app: runs the library in its own window plus a small desktop widget.

Start with:  pythonw app/desktop.py   (Windows, no console)   or   python3 app/desktop.py

Uses pywebview (native window via Microsoft Edge WebView2 on Windows). If pywebview isn't
installed it falls back to Edge/Chrome "app mode" windows, which still have no browser tabs or address bar.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = int(os.environ.get("INKWELL_PORT", "8765"))
BASE = f"http://localhost:{PORT}"
# lets the video player switch between audio languages in a file (video.audioTracks)
# Music plays in the main window even while it's hidden behind the widget, so that window must not be slowed down
# when out of sight, and it must be allowed to start playback without being clicked first.
_flags = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
for _f in ("--enable-blink-features=AudioVideoTracks", "--autoplay-policy=no-user-gesture-required",
           "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
           "--disable-backgrounding-occluded-windows", "--disable-features=CalculateNativeWinOcclusion"):
    if _f.split("=")[0] not in _flags:
        _flags += " " + _f
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = _flags.strip()


def already_running():
    try:
        with urllib.request.urlopen(BASE + "/api/status", timeout=1.5):
            return True
    except Exception:
        return False


def poke_running_instance():
    req = urllib.request.Request(BASE + "/api/desktop/open-main", data=b'{"fullscreen": false}',
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def running_root():
    try:
        with urllib.request.urlopen(BASE + "/api/status", timeout=1.5) as r:
            return json.loads(r.read()).get("app_root") or "?"
    except Exception:
        return None


_here_root = os.path.dirname(HERE)
_other = running_root()
if _other and os.path.normcase(os.path.abspath(_other)) != os.path.normcase(_here_root) and \
        (_other != "?" or os.path.exists(os.path.join(_here_root, "relocate.json"))):
    # an Babel's Library from another folder (e.g. the copy this one was moved from) is running: close it and take over
    try:
        urllib.request.urlopen(urllib.request.Request(BASE + "/api/desktop/widget", data=b'{"action": "quit"}',
                                                      headers={"Content-Type": "application/json"}, method="POST"), timeout=3)
    except Exception:
        pass
    for _ in range(20):
        time.sleep(0.5)
        if not already_running():
            break
elif _other:
    # second launch: just bring the existing Babel's Library window forward
    poke_running_instance()
    sys.exit(0)

import store  # noqa: E402
import server  # noqa: E402

# Log to a file when there's no console (pythonw)
class _SafeLog:
    """inkwell.log lives on the data drive. If that drive drops out, writing must never raise: a failing print
    inside an error handler would kill the request (empty response) or the background thread that printed."""

    def __init__(self, path):
        self.path, self.f = path, None
        self._lock = threading.Lock()

    def write(self, s):
        with self._lock:
            for _ in range(2):
                try:
                    if self.f is None:
                        self.f = open(self.path, "a", encoding="utf-8", buffering=1)
                    return self.f.write(s)
                except (OSError, ValueError):
                    try:
                        self.f and self.f.close()
                    except Exception:
                        pass
                    self.f = None  # reopen on the next write (the drive may be back)
            return len(s)

    def flush(self):
        try:
            self.f and self.f.flush()
        except (OSError, ValueError):
            self.f = None

    def isatty(self):
        return False


if sys.stdout is None or not hasattr(sys.stdout, "write") or os.path.basename(sys.executable).lower().startswith("pythonw"):
    sys.stdout = sys.stderr = _SafeLog(os.path.join(store.DATA_DIR, "inkwell.log"))

server.start_background()
ICON = os.path.join(HERE, "static", "icon.ico" if os.name == "nt" else "icon.png")


_CACHE_DIRS = {"Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache", "GraphiteDawnCache", "DawnGraphiteCache",
               "DawnWebGPUCache", "GPUPersistentCache", "Crashpad", "BrowserMetrics", "component_crx_cache",
               "extensions_crx_cache", "CacheStorage", "ScriptCache"}


def webview_profile():
    """The window's browser profile lives on the system drive, not next to the library: if the library is on a USB
    drive that drops out, a profile there takes the whole WebView2 browser down with it (the window goes black).
    The old profile's saved page data is carried over once; caches are left behind."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    storage = os.path.join(base, "BabelsLibrary", "webview")
    old = os.path.join(store.DATA_DIR, "webview")
    if not os.path.isdir(storage) and os.path.isdir(old):
        try:
            shutil.copytree(old, storage, ignore=lambda d, names: [n for n in names if n in _CACHE_DIRS])
            print("[inkwell] window profile moved to", storage)
        except Exception as e:
            print("[inkwell] couldn't carry the window profile over (starting a fresh one):", e)
    os.makedirs(storage, exist_ok=True)
    return storage


def widget_geometry(screen_w, screen_h):
    s = store.get_settings()
    w, h = int(s.get("widget_w") or 340), int(s.get("widget_h") or 520)
    corner = s.get("widget_corner") or "top-right"
    m = 24
    pos = {
        "top-left": (m, m + 10),
        "top-right": (screen_w - w - m, m + 10),
        "bottom-left": (m, screen_h - h - m - 48),
        "bottom-right": (screen_w - w - m, screen_h - h - m - 48),
    }
    if corner == "custom" and s.get("widget_x") is not None:
        x, y = int(s["widget_x"]), int(s["widget_y"])
    else:
        x, y = pos.get(corner, pos["top-right"])
    return x, y, w, h


# --------------------------------------------------------------------------------------
# Native windows with pywebview
# --------------------------------------------------------------------------------------
class NativeDesktop:
    """One Babel's Library, two forms: the full window or the small desktop widget. Only one is shown at a time."""
    mode = "native"

    def __init__(self, webview):
        self.wv = webview
        self.main = None
        self.widget = None
        self.form = "full"
        self._fs = False
        self._move_t = None
        self.screen = (1920, 1080)
        try:
            import news            # the Gazette reads sites that refuse plain downloads through the browser engine
            news.PAGE_HTML = lambda url: self._browser().page_html(url)
        except Exception as e:
            print("[inkwell] news reader:", e)
        try:
            sc = webview.screens[0]
            self.screen = (sc.width, sc.height)
        except Exception:
            pass

    # ---- windows (both created once; we only show/hide them)
    def create_main(self, hidden=False, park=False, start_fullscreen=False):
        """park=True (starting as the widget): the main window holds the music player, and WebView2 doesn't start
        its page until the window has been shown once. So it opens minimised, loads, then hides itself."""
        s = store.get_settings()
        self._fs = (start_fullscreen or bool(s.get("main_fullscreen"))) and not (hidden or park)
        self._parked = park
        kw = dict(width=1360, height=860, min_size=(760, 520), fullscreen=self._fs,
                  background_color="#1e140c", text_select=True, zoomable=True)
        if park:
            try:
                self.main = self.wv.create_window("Babel's Library", BASE + "/", hidden=False, minimized=True, maximized=False, **kw)
            except TypeError:
                self.main = self.wv.create_window("Babel's Library", BASE + "/", hidden=False, x=-32000, y=-32000, **kw)
            done = {"v": False}
            def _park():
                if done["v"]:
                    return
                done["v"] = True
                if self.form == "widget":
                    try:
                        self.main.hide()
                    except Exception as e:
                        print("[inkwell] couldn't park the main window:", e)
            self.main.events.loaded += _park
        else:
            self.main = self.wv.create_window("Babel's Library", BASE + "/", hidden=hidden, maximized=not self._fs, **kw)
        self.main.events.closed += self._quit
        return self.main

    def create_widget(self, hidden=True):
        x, y, w, h = widget_geometry(*self.screen)
        self.widget = self.wv.create_window(
            "Babel's Library", BASE + "/widget.html", width=w, height=h, x=x, y=y, hidden=hidden,
            frameless=True, easy_drag=False, on_top=False,  # a normal window: others can sit in front of it
            resizable=True, min_size=(260, 300), background_color="#1e140c", focus=False, text_select=True)
        self.widget.events.moved += self._widget_moved
        self.widget.events.resized += self._widget_resized
        self.widget.events.closed += self._quit
        return self.widget

    def _quit(self):
        os._exit(0)

    # ---- mini reader: a normal window with the full reader, opened from the widget ----
    def mini_size(self):
        """Just big enough for a two-page comic spread: page height fills the window, two ~2:3 pages side by side,
        plus the toolbar and the page-turn arrows."""
        sw, sh = self.screen
        h = max(560, min(int(sh * 0.8), 940))
        page_h = h - 120                      # title bar, toolbar, margins
        w = int(2 * page_h * 0.66) + 160      # two pages + arrows and gaps
        return min(w, sw - 40), min(h, sh - 60)

    def open_reader(self, item_id):
        url = f"{BASE}/?read={int(item_id)}&mini=1"
        w, h = self.mini_size()
        sw, sh = self.screen
        if getattr(self, "mini", None) is not None:
            try:
                if getattr(self, "_mini_fs", False):
                    self.mini.toggle_fullscreen()
                    self._mini_fs = False
                self.mini.restore()
                self.mini.resize(w, h)
                self.mini.move(max(0, (sw - w) // 2), max(0, (sh - h) // 2))
                self.mini.load_url(url)
                self.mini.show()
                return
            except Exception:
                self.mini = None
        self._mini_fs = False
        self.mini = self.wv.create_window(
            "Babel's Library reader", url, width=w, height=h,
            x=max(0, (sw - w) // 2), y=max(0, (sh - h) // 2), resizable=True, min_size=(520, 420),
            background_color="#1e140c", text_select=True, zoomable=True)
        self.mini.events.closed += self._mini_closed

    def _mini_closed(self):
        self.mini = None

    def close_reader(self):
        if getattr(self, "mini", None) is not None:
            try:
                self.mini.destroy()
            except Exception:
                pass
            self.mini = None

    def toggle_reader_fullscreen(self):
        if getattr(self, "mini", None) is not None:
            self.mini.toggle_fullscreen()
            self._mini_fs = not getattr(self, "_mini_fs", False)

    # ---- reading room: manga sites (MANGA Plus, VIZ, AniList...) run on JavaScript and refuse to sit inside the app's
    # page, so they get a browser window of their own. It shares the app's WebView2 profile, so sign-ins are kept.
    _inapp_lock = threading.Lock()

    def _browser(self):
        """The one in-app browser (two bar commands arriving together must not make two)."""
        with self._inapp_lock:
            if getattr(self, "inapp", None) is None:
                import inapp
                self.inapp = inapp.InApp(self)
            return self.inapp

    def browser_view(self, d):
        """The in-app browser (inapp.py): a bar command from the library page."""
        self._browser().command(d)

    def snap(self):
        """The library window's inside, exactly as it is on screen (websites and videos included), as a PNG data URL."""
        import base64
        from System import Func, Object
        from System.Drawing import Bitmap, Graphics, Point
        from System.Drawing.Imaging import ImageFormat
        from System.IO import MemoryStream
        form = self.main.native
        rect = form.Invoke(Func[Object](lambda: form.RectangleToScreen(form.ClientRectangle)))
        bmp = Bitmap(rect.Width, rect.Height)
        g = Graphics.FromImage(bmp)
        try:
            g.CopyFromScreen(Point(rect.X, rect.Y), Point(0, 0), bmp.Size)
            ms = MemoryStream()
            bmp.Save(ms, ImageFormat.Png)
            return "data:image/png;base64," + base64.b64encode(bytes(ms.ToArray())).decode()
        finally:
            g.Dispose()
            bmp.Dispose()

    def save_web(self, url, days=None):
        """Save a web page (sent from the phone's browser) into the library as an article."""
        import news
        return self._browser().capture(news.real_url(url), days)      # a Google News link: the story's own address is kept

    def open_web(self, url, title=""):
        # with the library window up, pages open in its own browser view; as the widget, in a window of their own
        if self.form == "full" and self.main is not None:
            try:
                self.main.evaluate_js("window.Browser && Browser.open(" + json.dumps(url) + ")")
                return
            except Exception as e:
                print("[inkwell] in-app browser unavailable:", e)
        sw, sh = self.screen
        w, h = min(1280, sw - 80), min(int(sh * 0.9), sh - 60)
        name = ROOM_TITLE + (title or "Browser")
        try:
            import adblock
            from urllib.parse import urlparse
            _room_sites.add(adblock._site((urlparse(url).hostname or "").lower()))
        except Exception:
            pass
        if getattr(self, "web", None) is not None:
            try:
                self.web.load_url(url)
                self.web.set_title(name)
                self.web.restore()
                self.web.show()
                return
            except Exception:
                self.web = None
        self.web = self.wv.create_window(name, url, width=w, height=h, x=max(0, (sw - w) // 2), y=max(0, (sh - h) // 2 - 10),
                                         resizable=True, min_size=(480, 400), background_color="#1e140c", text_select=True, zoomable=True)
        self.web.events.closed += self._web_closed

    def _web_closed(self):
        self.web = None

    def _locked(self):
        return bool(store.get_settings().get("widget_locked"))

    def _widget_moved(self, x, y):
        if self.form != "widget":
            return
        s = store.get_settings()
        if s.get("widget_locked") and s.get("widget_x") is not None:
            # pinned: put it straight back where it was pinned
            if (int(x), int(y)) != (int(s["widget_x"]), int(s["widget_y"])):
                threading.Timer(0.05, lambda: self.widget.move(int(s["widget_x"]), int(s["widget_y"]))).start()
            return
        def save():
            store.set_settings({"widget_x": int(x), "widget_y": int(y), "widget_corner": "custom"})
        if self._move_t:
            self._move_t.cancel()
        self._move_t = threading.Timer(0.6, save)
        self._move_t.start()

    def _widget_resized(self, w, h):
        if self.form != "widget":
            return
        s = store.get_settings()
        if s.get("widget_locked"):
            if (int(w), int(h)) != (int(s["widget_w"]), int(s["widget_h"])):
                threading.Timer(0.05, lambda: self.widget.resize(int(s["widget_w"]), int(s["widget_h"]))).start()
            return
        store.set_settings({"widget_w": int(w), "widget_h": int(h)})

    # ---- switching forms
    def to_widget(self):
        if self.widget is None:
            self.create_widget(hidden=True)
            time.sleep(0.8)
        if self.main is not None and self._fs:
            self.main.toggle_fullscreen()
            self._fs = False
        x, y, w, h = widget_geometry(*self.screen)
        self.form = "widget"
        self.widget.resize(w, h)
        self.widget.move(x, y)
        self.widget.show()
        if self.main is not None:
            self.main.hide()
        try:
            self.widget.evaluate_js("window.inkwellRefresh && window.inkwellRefresh()")
        except Exception:
            pass

    def player_cmd(self, cmd):
        """Music always plays in the main window (it keeps running while hidden); the widget sends it commands."""
        if self.main is None:
            return False
        try:
            self.main.evaluate_js("window.inkwellCmd && window.inkwellCmd(" + json.dumps(cmd) + ")")
            return True
        except Exception as e:
            print("[inkwell] player command failed:", e)
            return False

    def _take_music(self, win):
        """Pause music in the window that's going away and return its player state (JSON text)."""
        if win is None:
            return None
        try:
            st = win.evaluate_js("window.inkwellHandoff ? window.inkwellHandoff() : null")
            return st if isinstance(st, str) and '"tracks":[{' in st else None
        except Exception:
            return None

    def _give_music(self, win, st):
        if not st or win is None:
            return
        try:
            win.events.loaded.wait(10)
            win.evaluate_js("window.inkwellResume && window.inkwellResume(" + json.dumps(st) + ")")
        except Exception as e:
            print("[inkwell] music handoff failed:", e)

    def open_main(self, read_id=None, fullscreen=True):
        self.form = "full"
        if self.main is None:
            self.create_main(hidden=False)
            time.sleep(1.2)
        else:
            self.main.show()
            self.main.restore()
            if getattr(self, "_parked", False):
                self._parked = False
                try:
                    self.main.maximize()
                except Exception:
                    pass
        if fullscreen and not self._fs:
            self.main.toggle_fullscreen()
            self._fs = True
        if self.widget is not None:
            self.widget.hide()
        if read_id:
            self.main.events.loaded.wait(10)
            self.main.evaluate_js(f"window.inkwellOpenItem && window.inkwellOpenItem({int(read_id)})")
        else:
            try:
                self.main.evaluate_js("window.loadItems && loadItems()")
            except Exception:
                pass

    def toggle_fullscreen(self):
        if self.main:
            self.main.toggle_fullscreen()
            self._fs = not self._fs

    def pick_folder(self):
        win = self.main if self.form == "full" else self.widget
        win = win or self.main or self.widget
        if win is None:
            return None
        kind = getattr(getattr(self.wv, "FileDialog", None), "FOLDER", None) or getattr(self.wv, "FOLDER_DIALOG", 20)
        res = win.create_file_dialog(kind)
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res

    def widget_action(self, action, value=None):
        if action in ("show", "to_widget"):
            self.to_widget()
        elif action == "lock":
            upd = {"widget_locked": bool(value)}
            if value and self.widget is not None:
                try:
                    upd.update({"widget_x": int(self.widget.x), "widget_y": int(self.widget.y),
                                "widget_w": int(self.widget.width), "widget_h": int(self.widget.height), "widget_corner": "custom"})
                except Exception:
                    pass
            store.set_settings(upd)
        elif action == "snap":
            if self._locked():
                return
            store.set_settings({"widget_corner": value})
            if self.widget is not None and self.form == "widget":
                x, y, w, h = widget_geometry(*self.screen)
                self.widget.resize(w, h)
                self.widget.move(x, y)
        elif action == "quit":
            os._exit(0)

    def run(self):
        # opening Babel's Library from nothing always shows the full window, full screen; the widget is a click away
        self.form = "full"
        self.create_main(park=False, start_fullscreen=True)
        self.create_widget(hidden=True)
        storage = webview_profile()
        kw = {"private_mode": False, "storage_path": storage}
        if os.path.exists(ICON):
            kw["icon"] = ICON
        try:
            self.wv.start(**kw)
        except TypeError:
            kw.pop("icon", None)
            self.wv.start(**kw)
        os._exit(0)


# --------------------------------------------------------------------------------------
# Fallback: Edge / Chrome "app mode" windows (no tabs, no address bar)
# --------------------------------------------------------------------------------------
def find_browser():
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for name in ("msedge", "microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome", "brave-browser", "vivaldi"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    return next((c for c in cands if c and os.path.exists(c)), None)


class AppModeDesktop:
    mode = "appmode"

    def __init__(self, exe):
        self.exe = exe
        self.profile = os.path.join(store.DATA_DIR, "app-window")

    def _spawn(self, url, extra):
        subprocess.Popen([self.exe, f"--app={url}", f"--user-data-dir={self.profile}", "--no-first-run", "--enable-blink-features=AudioVideoTracks",
                          "--no-default-browser-check", *extra])

    def open_main(self, read_id=None, fullscreen=True):
        url = BASE + "/" + (f"?read={int(read_id)}" if read_id else "")
        self._spawn(url, ["--start-fullscreen"] if fullscreen else ["--start-maximized"])

    def toggle_fullscreen(self):
        pass

    def widget_action(self, action, value=None):
        if action in ("show", "to_widget"):
            self.open_widget()
        elif action == "lock":
            store.set_settings({"widget_locked": bool(value)})
        elif action == "quit":
            os._exit(0)

    def open_reader(self, item_id):
        self._spawn(f"{BASE}/?read={int(item_id)}&mini=1", ["--window-size=1100,840"])

    def close_reader(self):
        pass

    def open_widget(self):
        x, y, w, h = widget_geometry(1920, 1080)
        self._spawn(BASE + "/widget.html", [f"--window-size={w},{h}", f"--window-position={x},{y}"])

    def run(self):
        if store.get_settings().get("start_mode") == "widget":
            self.open_widget()
        else:
            self.open_main(fullscreen=False)
        # keep the library server alive while the windows are open
        while True:
            time.sleep(3600)


def linux_backend_ok():
    """pywebview on Linux needs GTK WebKit (python3-gi + gir1.2-webkit2) or Qt WebEngine."""
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False
        try:
            import gi
            for v in ("4.1", "4.0"):
                try:
                    gi.require_version("WebKit2", v)
                    from gi.repository import WebKit2  # noqa: F401
                    return True
                except (ValueError, ImportError):
                    continue
        except ImportError:
            pass
        for mod in ("PyQt6.QtWebEngineWidgets", "PyQt5.QtWebEngineWidgets", "PySide6.QtWebEngineWidgets"):
            try:
                __import__(mod)
                return True
            except ImportError:
                continue
        return False
    return True


def refresh_shortcuts():
    """Windows: (re)make the Desktop / Start menu shortcuts once after a rename or move."""
    if os.name != "nt":
        return
    mark = os.path.join(HERE, ".shortcuts-babel")
    if os.path.exists(mark):
        return
    try:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(HERE, "make-shortcuts.ps1"),
                          "-Pythonw", pyw if os.path.exists(pyw) else sys.executable, "-AppDir", os.path.dirname(HERE)],
                         creationflags=0x08000000)
        with open(mark, "w") as f:
            f.write("made")
    except Exception as e:
        print("[babel] shortcuts not updated:", e)


ROOM_TITLE = "Babel's Library · "      # the reading window's title starts with this (NativeDesktop.open_web)
_room_sites = set()                    # sites you opened in it: never blocked, even when a list names them
_ab_on = {"v": True, "at": 0.0}


def _adblock_on():
    if time.time() - _ab_on["at"] > 5:   # settings are read at most every few seconds, not on every request
        _ab_on["v"], _ab_on["at"] = bool(store.get_settings().get("adblock", True)), time.time()
    return _ab_on["v"]


def install_adblock():
    """Ad blocking in the reading window: pywebview already passes every request a window makes through Python,
    so its WebView2 handlers are wrapped to refuse ad and tracker requests, pop-ups to other sites, and to hide ad
    boxes. Other windows (the library itself) are left alone."""
    try:
        from urllib.parse import urlparse
        from webview.platforms import edgechromium as ec
        import adblock
    except Exception as e:
        print("[inkwell] ad blocking unavailable:", e)
        return
    adblock.start()
    E = ec.EdgeChrome
    orig_req, orig_new, orig_ready = E.on_web_resource_request, E.on_new_window_request, E.on_webview_ready
    room = lambda self: str(getattr(self.pywebview_window, "title", "") or "").startswith(ROOM_TITLE)
    host = lambda u: (urlparse(str(u or "")).hostname or "").lower()

    def on_request(self, sender, args):
        if room(self) and _adblock_on():
            try:
                h, top = host(args.Request.Uri), host(self.url)
                going = getattr(getattr(self, "room_chrome", None), "nav_host", "")   # the page you're going to
                if h != going and adblock._site(h) not in _room_sites and adblock.blocked(h, top):
                    args.Response = sender.Environment.CreateWebResourceResponse(None, 403, "Blocked", "")
                    return
            except Exception as e:
                print("[inkwell] ad-block check failed:", e)
        return orig_req(self, sender, args)

    def on_new_window(self, sender, args):
        if room(self) and _adblock_on():
            try:
                h, top = host(args.get_Uri()), host(self.url)
                # a link you clicked that wants a new tab opens here instead (one tab); pop-ups a page opens by
                # itself, and anything to an ad network, are dropped
                if adblock.blocked(h, top) or (top and adblock._site(h) != adblock._site(top) and not args.IsUserInitiated):
                    args.set_Handled(True)
                    return
            except Exception as e:
                print("[inkwell] pop-up check failed:", e)
        if room(self):                      # one tab: the new page opens in this window
            args.set_Handled(True)
            sender.Navigate(str(args.get_Uri()))
            return
        return orig_new(self, sender, args)

    def on_ready(self, sender, args):
        # added before pywebview starts loading the page, so it applies to the first page too
        if room(self) and args.IsSuccess and _adblock_on():
            try:
                sender.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(adblock.hide_css())
            except Exception as e:
                print("[inkwell] ad-box hiding unavailable:", e)
        orig_ready(self, sender, args)
        if room(self) and args.IsSuccess:
            try:
                import roomchrome
                self.room_chrome = roomchrome.RoomChrome(self, ec.WinForms)
                self.room_chrome.nav_host = ""

                def starting(s, e):
                    self.room_chrome.nav_host = host(e.Uri)
                sender.CoreWebView2.NavigationStarting += starting
            except Exception as e:
                import traceback
                traceback.print_exc()
                print("[inkwell] browser bar unavailable:", e)

    orig_done = E.on_navigation_completed

    def on_done(self, sender, args):
        # the first page can start loading before the script above is registered: add the rules once it's loaded
        # (the script skips pages that already have them)
        r = orig_done(self, sender, args)
        if room(self) and _adblock_on():
            try:
                self.webview.CoreWebView2.ExecuteScriptAsync(adblock.hide_css())
            except Exception as e:
                print("[inkwell] ad-box hiding unavailable:", e)
        return r

    orig_notify = E.on_script_notify

    def on_notify(self, sender, args):
        # the browser bar's login messages are handled in roomchrome.py; pywebview's own handler can't read them
        try:
            if room(self) and '"babelLogin"' in str(args.get_WebMessageAsJson()):
                return
        except Exception:
            pass
        return orig_notify(self, sender, args)

    E.on_web_resource_request, E.on_new_window_request, E.on_webview_ready = on_request, on_new_window, on_ready
    E.on_navigation_completed, E.on_script_notify = on_done, on_notify


def main():
    refresh_shortcuts()
    try:
        import webview  # pywebview
        if not linux_backend_ok():
            raise RuntimeError("no GTK WebKit or Qt WebEngine for pywebview")
        desk = NativeDesktop(webview)
        if sys.platform == "win32":
            install_adblock()
    except Exception as e:
        print("[inkwell] pywebview not available (", e, ") — using app-mode windows")
        exe = find_browser()
        if not exe:
            import webbrowser
            webbrowser.open(BASE)
            while True:
                time.sleep(3600)
        desk = AppModeDesktop(exe)
    server.DESKTOP = desk
    desk.run()


if __name__ == "__main__":
    main()
