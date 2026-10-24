"""The browser inside the main window. The bar (back, forward, address, W, passwords) is part of the library page
itself, so it follows the theme; websites show in a second WebView2 laid over the space the page leaves for them
(sites refuse to sit in an iframe). It shares the library window's WebView2 profile, so sign-ins are kept.

The page drives it through /api/browser/view (place, hide, go, back...); it reports back to the page by calling
window.Browser.state(...) whenever the address, title or loading state changes. Websites never see the bar: they
live in their own WebView2 and can only offer a login that was just typed (window.chrome.webview.postMessage).
"""
import json
import re
import secrets
import sys
import time
from urllib.parse import urlparse

import browser
import roomchrome

BASE = roomchrome.BASE

# what the page says about itself (title, site, author, date), read before saving it
META_JS = r"""(()=>{const m=(s)=>{const e=document.querySelector(s);return e?(e.getAttribute('content')||'').trim():''};
const ld=[...document.querySelectorAll('script[type="application/ld+json"]')].map(s=>{try{return JSON.parse(s.textContent)}catch(e){return null}}).flat().filter(Boolean);
const art=ld.find(x=>/Article|Report|Posting/i.test(String(x['@type']||'')))||{};
const who=art.author?[].concat(art.author).map(a=>a&&(a.name||a)).filter(x=>typeof x==='string'):[];
return JSON.stringify({title:m('meta[property="og:title"]')||art.headline||document.title,site:m('meta[property="og:site_name"]')||location.hostname.replace(/^www\./,''),
authors:who.length?who:(m('meta[name="author"]')||m('meta[property="article:author"]')).split(/,| and /).map(s=>s.trim()).filter(s=>s&&!/^https?:/.test(s)),
date:m('meta[property="article:published_time"]')||art.datePublished||m('meta[name="date"]')||'',desc:m('meta[name="description"]')||m('meta[property="og:description"]')})})()"""
# for the saved copy: the article without the site's menus, footers, cookie and newsletter boxes
PRINT_JS = r"""(()=>{const s=document.createElement('style');s.textContent='@media print{body>header,body>footer,nav,aside,iframe,[role=navigation],[role=complementary],[class*=newsletter i],[class*=cookie i],[id*=cookie i],[class*=promo i],[class*=related i],[class*=share i],[class*=social i],[class*=subscribe i]{display:none!important}body{background:#fff!important}}';document.head.appendChild(s);return 1})()"""


def _wait(task, timeout=60):
    """Wait (on a worker thread) for a WebView2 task started on the UI thread."""
    t0 = time.time()
    while not task.IsCompleted:
        if time.time() - t0 > timeout:
            raise TimeoutError("The page took too long.")
        time.sleep(0.15)
    if task.IsFaulted:
        raise RuntimeError(str(task.Exception))
    return task.Result


# a click anywhere in a page tells the bar which half of a split view you're using
FOCUS_JS = r"""addEventListener('pointerdown',()=>{try{window.chrome.webview.postMessage({babelFocus:1})}catch(e){}},true)"""


class InApp:
    def __init__(self, desk, side=False):
        self.desk = desk
        self.side = side           # the right half of a split view (the left half owns it)
        self._other = None
        self.ctl = None            # the WebView2 control with the website
        self.core = None
        self.rect = None           # where the page wants it, in window pixels
        self.cut = []              # parts of the window it must leave uncovered (the floating journal)
        self.shown = False
        self.full = False          # a video went full screen: the site fills the whole window
        self.nav_host = ""
        self.url = ""
        self.title = ""
        self.loading = False
        self._queue = []           # commands that arrived before the view was ready
        self._offers = {}          # token -> (site url, username, password) waiting for "Save" on the bar
        self._offered = {}

    # ---- plumbing
    def _edge(self):
        return self.desk.main.native.browser          # pywebview's EdgeChrome for the library window

    def _ui(self, fn):
        from System.Windows.Forms import MethodInvoker
        form = self.desk.main.native
        form.BeginInvoke(MethodInvoker(fn))

    def _tell(self, kind, data):
        """Tell the library page something (on the UI thread; evaluate_js would wait for itself there)."""
        pane = ',"side"' if self.side else ""
        try:
            self._edge().webview.CoreWebView2.ExecuteScriptAsync(f"window.Browser && Browser.{kind}({json.dumps(data)}{pane})")
        except Exception as e:
            print("[inkwell] browser couldn't update the bar:", e)

    def _side(self):
        if self._other is None:
            self._other = InApp(self.desk, side=True)
        return self._other

    def command(self, d):
        """From the HTTP thread: run one bar command on the window's UI thread (for the split view's right half
        when it says pane: "side")."""
        if d.get("pane") == "side" and not self.side:
            return self._side().command(d)
        if d.get("cmd") == "savepage":
            import threading
            threading.Thread(target=self._save_open_page, args=(d.get("days"),), daemon=True).start()
            return
        self._ui(lambda: self._run(d))

    def _on_ui(self, fn):
        """Run fn on the window's UI thread and hand back what it returns (from a worker thread)."""
        from System import Func, Object
        return self.desk.main.native.Invoke(Func[Object](fn))

    # ---- saving articles for reading offline
    def _save_open_page(self, days=None):
        url = self.url
        try:
            if self.core is None or not url.startswith("http"):
                raise ValueError("Open an article first.")
            r = self.save_page(lambda: self.core, url, days)
            self._ui(lambda: self._tell("saved", r))
        except Exception as e:
            print("[inkwell] couldn't save the page:", e)
            msg = str(e)
            self._ui(lambda: self._tell("saved", {"ok": False, "error": msg}))

    def save_page(self, core_fn, url, days=None):
        """The page as a PDF, filed in the library as an article (sorted and tagged like any other), with its web
        address kept so you can visit it again. core_fn gives the WebView2 showing it (called on the UI thread)."""
        import os
        import re as _re
        import server
        meta = json.loads(_wait(self._on_ui(lambda: core_fn().ExecuteScriptAsync(META_JS))) or '""') or "{}"
        meta = json.loads(meta) if isinstance(meta, str) else meta
        _wait(self._on_ui(lambda: core_fn().ExecuteScriptAsync(PRINT_JS)))
        title = (meta.get("title") or "").strip() or browser.site_of(url)
        site = (meta.get("site") or "").strip()
        title = _re.sub(r"\s*[|–—-]\s*" + _re.escape(site) + r"\s*$", "", title, flags=_re.I) if site else title
        m = _re.search(r"\s+[|–—-]\s+([^|–—-]{2,30})$", title)      # "Gift wrapping - Wikipedia": the site's name, not the title's
        host = (urlparse(url).hostname or "").lower()
        if m and _re.sub(r"[^a-z0-9]", "", m.group(1).lower()) in host.replace(".", ""):
            title = title[: m.start()]
        folder = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "saving")
        os.makedirs(folder, exist_ok=True)
        safe = _re.sub(r'[\\/:*?"<>|]+', " ", title)[:90].strip() or "Article"
        path = os.path.join(folder, f"{safe}.pdf")

        def start():
            core = core_fn()
            ps = core.Environment.CreatePrintSettings()
            ps.ShouldPrintBackgrounds = False
            ps.ShouldPrintHeaderAndFooter = False
            return core.PrintToPdfAsync(path, ps)
        if not _wait(self._on_ui(start), 120) or not os.path.exists(path):
            raise RuntimeError("The page couldn't be printed to a PDF.")
        y = (meta.get("date") or "")[:4]
        info = {"kind": "article", "title": title, "url": url, "journal": site, "authors": [a for a in meta.get("authors") or [] if len(a) < 80][:4],
                "year": int(y) if y.isdigit() else None, "summary": (meta.get("desc") or "").strip() or None,
                "expires_at": time.time() + float(days) * 86400 if days else None}      # kept for 30 days, if that was asked
        iid, new = server.import_file(path, f"{safe}.pdf", origin="web", move=True, meta={k: v for k, v in info.items() if v})
        if os.path.exists(path):
            os.remove(path)
        print(f"[inkwell] Saved from the web: {title} ({url})")
        return {"ok": True, "id": iid, "title": title, "new": new}

    def page_html(self, url, timeout=40):
        """A page as the app's own browser engine sees it (for sites that turn away plain downloads), loaded in a
        hidden view and read back as HTML."""
        from Microsoft.Web.WebView2.WinForms import WebView2
        holder = {}

        def make():
            edge = self._edge()
            ctl = WebView2()
            from System.Drawing import Rectangle
            ctl.Bounds = Rectangle(-6000, -6000, 1200, 1600)        # off the window: never seen
            edge.form.Controls.Add(ctl)
            holder["ctl"] = ctl
            return ctl.EnsureCoreWebView2Async(edge.webview.CoreWebView2.Environment)
        try:
            _wait(self._on_ui(make), 30)
            done = {"v": False}

            def nav():
                core = holder["ctl"].CoreWebView2
                core.NavigationCompleted += lambda s, e: done.update(v=True)
                core.Navigate(url)
            self._on_ui(nav)
            t0 = time.time()
            while not done["v"] and time.time() - t0 < timeout:
                time.sleep(0.2)
            # a site's "checking your connection" page clears by itself in a few seconds in a real browser: wait for it
            # (one that wants a human to solve something never clears, and the reader sends you to the site instead)
            while time.time() - t0 < timeout:
                title = _wait(self._on_ui(lambda: holder["ctl"].CoreWebView2.ExecuteScriptAsync("document.title")), 10) or ""
                if not re.search(r"checking your|just a moment|attention required|verify you are|security check", title, re.I):
                    break
                time.sleep(1.0)
            time.sleep(1.0)
            raw = _wait(self._on_ui(lambda: holder["ctl"].CoreWebView2.ExecuteScriptAsync("document.documentElement.outerHTML")), 20)
            return json.loads(raw) if raw else ""
        finally:
            if holder.get("ctl") is not None:
                self._on_ui(lambda: (holder["ctl"].Parent.Controls.Remove(holder["ctl"]), holder["ctl"].Dispose()) and None)

    def capture(self, url, days=None):
        """Save a page you haven't got open (sent from the phone's browser): loaded in a hidden view, then saved."""
        from Microsoft.Web.WebView2.WinForms import WebView2
        holder = {}

        def make():
            edge = self._edge()
            ctl = WebView2()
            ctl.Visible = True
            from System.Drawing import Rectangle
            ctl.Bounds = Rectangle(-6000, -6000, 1200, 1600)        # off the window: never seen
            edge.form.Controls.Add(ctl)
            holder["ctl"] = ctl
            return ctl.EnsureCoreWebView2Async(edge.webview.CoreWebView2.Environment)
        try:
            _wait(self._on_ui(make), 30)
            done = {"v": False}

            def nav():
                core = holder["ctl"].CoreWebView2
                core.NavigationCompleted += lambda s, e: done.update(v=True)
                core.Navigate(url)
            self._on_ui(nav)
            t0 = time.time()
            while not done["v"] and time.time() - t0 < 45:
                time.sleep(0.2)
            time.sleep(2.5)                     # pages fill in a moment after they say they're loaded
            return self.save_page(lambda: holder["ctl"].CoreWebView2, url, days)
        finally:
            if holder.get("ctl") is not None:
                self._on_ui(lambda: (holder["ctl"].Parent.Controls.Remove(holder["ctl"]), holder["ctl"].Dispose()) and None)

    def _run(self, d):
        if self.core is None:
            self._queue.append(d)
            if self.ctl is None:
                self._create()
            return
        c = d.get("cmd")
        try:
            if c == "place":
                r, dpr = d.get("rect") or {}, float(d.get("dpr") or 1)
                self.rect = tuple(int(round(float(r.get(k, 0)) * dpr)) for k in ("x", "y", "w", "h"))
                self.cut = [tuple(int(round(float(c.get(k, 0)) * dpr)) for k in ("x", "y", "w", "h")) for c in d.get("cut") or []]
                self._apply()
                if d.get("show") is not None:
                    self.shown = bool(d["show"])
                    self._apply()
            elif c == "hide":
                self.shown = False
                self._apply()
            elif c == "freeze":
                self._freeze()
            elif c == "go":
                url = browser.to_url(d.get("text", ""), wiki=bool(d.get("wiki")))
                if url:
                    self.nav_host = (urlparse(url).hostname or "").lower()
                    self.core.Navigate(url)
                    self.shown = True
                    self._apply()
                    self.ctl.Focus()
            elif c == "back" and self.core.CanGoBack:
                self.core.GoBack()
            elif c == "forward" and self.core.CanGoForward:
                self.core.GoForward()
            elif c == "reload":
                self.core.Reload()
            elif c == "stop":
                self.core.Stop()
            elif c == "fill":
                self._fill(d.get("id"))
            elif c == "save":
                self._save(d.get("token"))
            self._state()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("[inkwell] browser command failed:", c, e)

    def _apply(self):
        ctl = self.ctl
        if ctl is None:
            return
        from System.Drawing import Rectangle
        from System.Windows.Forms import DockStyle
        if self.full:
            ctl.Dock = DockStyle.Fill
        else:
            ctl.Dock = getattr(DockStyle, "None")      # (None is a Python keyword)
            if self.rect:
                ctl.Bounds = Rectangle(*self.rect)
        # the floating journal and its bookmark show through: the site view is cut around them (and keeps playing)
        cut = [] if self.full or not self.rect else self.cut
        if cut != getattr(self, "_cut_now", []):
            from System.Drawing import Region
            if cut:
                reg = Region(Rectangle(0, 0, self.rect[2], self.rect[3]))
                for x, y, w, h in cut:
                    reg.Exclude(Rectangle(x - self.rect[0], y - self.rect[1], w, h))
                ctl.Region = reg
            else:
                ctl.Region = None
            self._cut_now = cut
        ctl.Visible = bool(self.shown and (self.rect or self.full))
        if ctl.Visible:
            ctl.BringToFront()

    def _freeze(self):
        """A panel (News, the catalogue, a dialog...) is opening over the browser: the page can't sit under it (the
        website view is always on top), so a picture of it takes its place until the panel closes."""
        if self.ctl is None or not self.ctl.Visible:
            return self._tell("frozen", "")
        import base64
        from System.IO import MemoryStream
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        ms = MemoryStream()
        task = self.core.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Jpeg, ms)

        def done(t):
            def ui():
                try:
                    data = "data:image/jpeg;base64," + base64.b64encode(bytes(ms.ToArray())).decode()
                except Exception:
                    data = ""
                self.shown = False
                self._apply()
                self._tell("frozen", data)
            self._ui(ui)
        from System import Action
        from System.Threading.Tasks import Task
        task.ContinueWith(Action[Task](done))

    # ---- the website's WebView2
    def _create(self):
        from Microsoft.Web.WebView2.WinForms import WebView2
        from System.Drawing import Color
        edge = self._edge()
        self.ctl = ctl = WebView2()
        ctl.Visible = False
        ctl.DefaultBackgroundColor = Color.White
        edge.form.Controls.Add(ctl)
        ctl.CoreWebView2InitializationCompleted += self._ready
        ctl.EnsureCoreWebView2Async(edge.webview.CoreWebView2.Environment)

    def _ready(self, sender, args):
        if not args.IsSuccess:
            print("[inkwell] the in-app browser couldn't start:", args.InitializationException)
            return
        from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
        self.core = core = self.ctl.CoreWebView2
        s = core.Settings
        s.AreDevToolsEnabled = False
        s.IsStatusBarEnabled = True
        core.AddScriptToExecuteOnDocumentCreatedAsync(roomchrome.CAPTURE_JS)
        core.AddScriptToExecuteOnDocumentCreatedAsync(FOCUS_JS)
        try:
            import adblock
            core.AddScriptToExecuteOnDocumentCreatedAsync(adblock.hide_css())
            main = sys.modules["__main__"]
            if not hasattr(main, "_adblock_on") or main._adblock_on():
                core.AddScriptToExecuteOnDocumentCreatedAsync(adblock.youtube_js())     # YouTube's own ads (it only acts on youtube.com)
        except Exception:
            pass
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All)
        core.WebResourceRequested += self._request
        core.NewWindowRequested += self._new_window
        core.NavigationStarting += self._starting
        core.NavigationCompleted += self._completed
        core.SourceChanged += lambda s, e: self._state()
        core.HistoryChanged += lambda s, e: self._state()
        core.DocumentTitleChanged += self._titled
        core.WebMessageReceived += self._message
        core.ContainsFullScreenElementChanged += self._fullscreen
        queued, self._queue = self._queue, []
        for d in queued:
            self._run(d)

    def _request(self, sender, args):
        try:
            # (the app runs desktop.py as __main__: "import desktop" would load it a second time and break every check)
            main = sys.modules["__main__"]
            if hasattr(main, "_adblock_on") and not main._adblock_on():
                return
            import adblock
            h = (urlparse(str(args.Request.Uri)).hostname or "").lower()
            top = (urlparse(self.url).hostname or "").lower()
            if h != self.nav_host and adblock._site(h) not in getattr(main, "_room_sites", ()) and adblock.blocked(h, top):
                args.Response = sender.Environment.CreateWebResourceResponse(None, 403, "Blocked", "")
        except Exception as e:
            print("[inkwell] ad-block check failed:", e)

    def _new_window(self, sender, args):
        """One tab: a link that wants a new tab opens here; pop-ups a page opens by itself are dropped."""
        args.Handled = True
        try:
            import adblock
            u = str(args.Uri)
            h, top = (urlparse(u).hostname or "").lower(), (urlparse(self.url).hostname or "").lower()
            if adblock.blocked(h, top) or (top and adblock._site(h) != adblock._site(top) and not args.IsUserInitiated):
                return
            self.nav_host = h
            sender.Navigate(u)
        except Exception as e:
            print("[inkwell] new-tab request failed:", e)

    def _starting(self, sender, args):
        self.nav_host = (urlparse(str(args.Uri)).hostname or "").lower()
        self.loading = True
        self._state()

    def _completed(self, sender, args):
        self.loading = False
        try:
            import adblock
            self.core.ExecuteScriptAsync(adblock.hide_css())
            site_css = adblock.hide_css_for((urlparse(str(self.core.Source or "")).hostname or "").lower())
            if site_css:
                self.core.ExecuteScriptAsync(site_css)
        except Exception:
            pass
        if args.IsSuccess:
            browser.visit(str(self.core.Source or ""), str(self.core.DocumentTitle or ""))
        self._state()

    def _titled(self, sender, args):
        self.title = str(self.core.DocumentTitle or "")
        browser.visit(str(self.core.Source or ""), self.title)
        self._state()

    def _fullscreen(self, sender, args):
        self.full = bool(self.core.ContainsFullScreenElement)
        self._apply()
        # a full-screen video takes the whole screen; the window goes back to how it was afterwards
        want = self.full
        if want != bool(getattr(self.desk, "_fs", False)) and (want or getattr(self, "_we_fs", False)):
            self._we_fs = want
            import threading
            threading.Thread(target=self.desk.toggle_fullscreen, daemon=True).start()

    def _state(self):
        if self.core is None:
            return
        self.url = str(self.core.Source or "")
        site = browser.site_of(self.url) if self.url.startswith("http") else ""
        self._tell("state", {"url": self.url, "title": str(self.core.DocumentTitle or ""), "back": bool(self.core.CanGoBack),
                             "forward": bool(self.core.CanGoForward), "loading": self.loading, "shown": self.shown, "starred": browser.is_bookmarked(self.url),
                             "site": site, "logins": [{"id": l["id"], "username": l["username"]} for l in browser.logins(site=site)] if site else []})

    # ---- passwords
    def _message(self, sender, args):
        try:
            msg = json.loads(str(args.WebMessageAsJson))
        except Exception:
            return
        if isinstance(msg, dict) and msg.get("babelFocus"):
            return self._tell("focused", {})
        if not isinstance(msg, dict) or not msg.get("babelLogin"):
            return
        src = str(args.Source or "")
        if not src.startswith(("https://", "http://")) or src.startswith(BASE):
            return
        site, user, pw = browser.site_of(src), str(msg.get("username") or "")[:200], str(msg.get("password") or "")[:500]
        if not site or not pw:
            return
        key = (site, user, pw)
        if time.time() - self._offered.get(key, 0) < 60 or browser.known(site, user, pw):
            return
        self._offered[key] = time.time()
        token = secrets.token_urlsafe(12)
        self._offers = {token: (src.split("?")[0], user, pw)}       # only the latest login waits for an answer
        update = any(l["username"] == user for l in browser.logins(site=site))
        self._tell("offerSave", {"token": token, "site": site, "username": user, "update": update})

    def _save(self, token):
        got = self._offers.pop(token or "", None)
        if got:
            browser.save_login(*got)

    def _fill(self, login_id):
        site = browser.site_of(self.url) if self.url.startswith("http") and not self.url.startswith(BASE) else ""
        found = [l for l in browser.logins(site=site)] if site else []
        login = next((l for l in found if str(l["id"]) == str(login_id)), found[0] if len(found) == 1 else None)
        if not login or login["site"] != site:
            return                      # never fill another site's password
        pw = browser.reveal(login["id"])
        self.core.ExecuteScriptAsync(f"{roomchrome.FILL_JS}({json.dumps(login['username'] or '')},{json.dumps(pw)})")
        browser.used(login["id"])
