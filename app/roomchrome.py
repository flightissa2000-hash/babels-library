"""The browser window's own controls: a native bar above the page (back, forward, reload, home, address/search, saved
passwords, history), plus history recording and saving/filling passwords.

The bar is made of Windows controls, not web page content, so no website can see, restyle or click it. Pages talk
to it only to offer a login that was just typed (window.chrome.webview.postMessage); saved passwords go back to a page
only when you press the key button, and only to the site they were saved for.
"""
import json
import time
from urllib.parse import urlparse

import browser

BASE = "http://localhost:8765"
START = BASE + "/browser.html"

# watches login forms: when a password is submitted, tells the window (which then offers to save it)
CAPTURE_JS = r"""(()=>{if(window.__babelPw)return;window.__babelPw=1;
const send=(root)=>{root=root||document;const pw=[...root.querySelectorAll('input[type=password]')].find(i=>i.value);if(!pw)return;
const ins=[...root.querySelectorAll('input')];let user='';for(let i=ins.indexOf(pw)-1;i>=0;i--){const t=(ins[i].type||'text').toLowerCase();
if(['text','email','tel'].includes(t)&&ins[i].value){user=ins[i].value;break}}
if(!user){const u=document.querySelector('input[autocomplete=username],input[type=email],input[name*=user i],input[name*=login i],input[name*=email i]');if(u&&u.value)user=u.value}
try{window.chrome.webview.postMessage({babelLogin:1,username:user,password:pw.value})}catch(e){}};
document.addEventListener('submit',e=>send(e.target),true);
document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('button,input[type=submit],[role=button]');if(b){const f=b.form||b.closest('form');setTimeout(()=>send(f),0)}},true);
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target&&e.target.type==='password')send(e.target.form)},true);})();"""

FILL_JS = r"""((u,p)=>{const vis=(e)=>e&&e.offsetParent!==null;
const pws=[...document.querySelectorAll('input[type=password]')];const pw=pws.find(vis)||pws[0];
const set=(el,v)=>{if(!el)return;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,v);
el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))};
let user=null;if(pw){const ins=[...document.querySelectorAll('input')];for(let i=ins.indexOf(pw)-1;i>=0;i--){const t=(ins[i].type||'text').toLowerCase();
if(['text','email','tel'].includes(t)&&vis(ins[i])){user=ins[i];break}}}
user=user||[...document.querySelectorAll('input[autocomplete=username],input[type=email],input[name*=user i],input[name*=login i],input[name*=email i],input[type=text]')].find(vis);
if(u&&user)set(user,u);if(pw)set(pw,p);return (pw?2:0)+(user?1:0)})"""


class RoomChrome:
    """Builds the bar on a pywebview window's form (called on the window's UI thread once WebView2 is ready)."""

    def __init__(self, edge, WinForms):
        from System.Drawing import Color, Font, FontStyle, Size
        self.edge, self.W = edge, WinForms
        self.core = edge.webview.CoreWebView2
        self.form = edge.form
        self._offered = {}
        # night-blue bar, buttons that light up under the pointer, the address in a framed field with a search mark
        dark, ink, mid = Color.FromArgb(22, 28, 44), Color.FromArgb(236, 240, 250), Color.FromArgb(36, 46, 70)
        hover, field = Color.FromArgb(58, 74, 110), Color.FromArgb(246, 248, 252)
        self.accent = Color.FromArgb(255, 107, 74)
        self.plain = mid
        bar = WinForms.TableLayoutPanel()
        bar.Dock = WinForms.DockStyle.Top
        bar.Height = 52
        bar.BackColor = dark
        bar.Padding = WinForms.Padding(8, 8, 8, 8)
        cols = [("◀", "Back (Alt+Left)", self.back), ("▶", "Forward (Alt+Right)", self.forward), ("⟳", "Reload (F5)", self.reload),
                ("⌂", "Start page", self.home), None, ("W", "Look it up on Wikipedia", self.wiki),
                ("🔑", "Fill in a saved password for this site", self.fill), ("☰", "History and saved passwords", self.manage)]
        bar.ColumnCount = len(cols)
        bar.RowCount = 1
        self.buttons = {}
        for i, c in enumerate(cols):
            if c is None:
                bar.ColumnStyles.Add(WinForms.ColumnStyle(WinForms.SizeType.Percent, 100))
                box = WinForms.Panel()                         # the field: a light frame around the text box
                box.Dock = WinForms.DockStyle.Fill
                box.BackColor = field
                box.Margin = WinForms.Padding(10, 0, 10, 0)
                box.Padding = WinForms.Padding(34, 7, 12, 4)
                mark = WinForms.Label()
                mark.Text = "⌕"
                mark.Font = Font("Segoe UI Symbol", 13)
                mark.ForeColor = Color.FromArgb(120, 130, 150)
                mark.AutoSize = True
                mark.Location = self._point(9, 4)
                tb = WinForms.TextBox()
                tb.Dock = WinForms.DockStyle.Fill
                tb.Font = Font("Segoe UI", 12)
                tb.BorderStyle = getattr(WinForms.BorderStyle, "None")   # (None is a Python keyword)
                tb.BackColor = field
                tb.ForeColor = Color.FromArgb(22, 28, 44)
                tb.KeyDown += self._keydown
                tb.Enter += lambda s, e: self.form.BeginInvoke(self.W.MethodInvoker(lambda: s.SelectAll()))
                box.Controls.Add(tb)
                box.Controls.Add(mark)
                self.address = tb
                bar.Controls.Add(box, i, 0)
                continue
            text, tip, fn = c
            bar.ColumnStyles.Add(WinForms.ColumnStyle(WinForms.SizeType.Absolute, 44))
            b = WinForms.Button()
            b.Text = text
            b.Dock = WinForms.DockStyle.Fill
            b.FlatStyle = WinForms.FlatStyle.Flat
            b.FlatAppearance.BorderSize = 0
            b.FlatAppearance.MouseOverBackColor = hover
            b.BackColor, b.ForeColor = mid, ink
            b.Font = Font("Georgia", 13, FontStyle.Bold) if text == "W" else Font("Segoe UI Symbol", 12, FontStyle.Bold)
            b.Margin = WinForms.Padding(2, 0, 2, 0)
            b.Cursor = WinForms.Cursors.Hand
            b.Click += (lambda f: (lambda s, e: f()))(fn)
            WinForms.ToolTip().SetToolTip(b, tip)
            self.buttons[text] = b
            bar.Controls.Add(b, i, 0)
        self.form.Controls.Add(bar)
        edge.webview.BringToFront()          # the page fills what the bar leaves
        self.form.KeyPreview = True
        self.core.SourceChanged += lambda s, e: self._source()
        self.core.DocumentTitleChanged += lambda s, e: self._title()
        self.core.NavigationCompleted += lambda s, e: self._loaded(e)
        self.core.WebMessageReceived += self._message
        self.core.AddScriptToExecuteOnDocumentCreatedAsync(CAPTURE_JS)
        self._source()

    # ---- buttons
    def back(self):
        if self.core.CanGoBack:
            self.core.GoBack()

    def forward(self):
        if self.core.CanGoForward:
            self.core.GoForward()

    def reload(self):
        self.core.Reload()

    def home(self):
        self.core.Navigate(START)

    def manage(self):
        self.core.Navigate(START + "#history")

    @staticmethod
    def _point(x, y):
        from System.Drawing import Point
        return Point(x, y)

    _wiki_next = False    # the W button was pressed with nothing typed: the next search goes to Wikipedia

    def wiki(self):
        text = self.address.Text.strip()
        if text and text != self.url():
            self._editing, self._wiki_next = False, False
            self.core.Navigate(browser.to_url(text, wiki=True))
            return
        self._wiki_next = True
        self._editing = True
        self.address.Text = ""
        self.address.Focus()
        self.buttons["W"].BackColor = self.accent        # lit: Enter searches Wikipedia

    _editing = False      # you're typing in the address bar: page changes don't overwrite it

    def _keydown(self, s, e):
        k = e.KeyCode
        if k == self.W.Keys.Enter:
            e.SuppressKeyPress = True
            url = browser.to_url(self.address.Text, wiki=self._wiki_next)
            self._wiki_next = False
            self.buttons["W"].BackColor = self.plain
            self._editing = False
            if url:
                self.core.Navigate(url)
                self.edge.webview.Focus()
        elif k == self.W.Keys.Escape:
            e.SuppressKeyPress = True
            self._editing = False
            self._source()
        else:
            self._editing = True

    # ---- page events
    def url(self):
        return str(self.core.Source or "")

    def _source(self):
        u = self.url()
        if not self._editing:
            self.address.Text = "" if u.startswith(START) else u
        site = browser.site_of(u) if u.startswith("http") and not u.startswith(BASE) else ""
        has = bool(site and browser.logins(site=site))
        self.buttons["🔑"].BackColor = self.accent if has else self.plain
        self.buttons["◀"].Enabled = bool(self.core.CanGoBack)
        self.buttons["▶"].Enabled = bool(self.core.CanGoForward)

    def _title(self):
        t = str(self.core.DocumentTitle or "")
        self.form.Text = "Babel's Library · " + (t or "Browser")
        browser.visit(self.url(), t)

    def _loaded(self, e):
        self._source()
        if e.IsSuccess:
            browser.visit(self.url(), str(self.core.DocumentTitle or ""))

    # ---- passwords
    def _message(self, s, e):
        try:
            msg = json.loads(str(e.WebMessageAsJson))
        except Exception:
            return
        if not isinstance(msg, dict) or not msg.get("babelLogin"):
            return
        src = str(e.Source or "")
        if not src.startswith(("https://", "http://")) or src.startswith(BASE):
            return
        site, user, pw = browser.site_of(src), str(msg.get("username") or "")[:200], str(msg.get("password") or "")[:500]
        if not site or not pw:
            return
        key = (site, user, pw)
        if time.time() - self._offered.get(key, 0) < 60 or browser.known(site, user, pw):
            return                      # just asked, or saved already
        self._offered[key] = time.time()
        existing = [l for l in browser.logins(site=site) if l["username"] == user]
        q = (f"Update the saved password for {user or 'this login'} on {site}?" if existing
             else f"Save the password for {user or 'this login'} on {site}?\n\nIt's kept encrypted for your Windows account on this computer.")
        W = self.W
        if W.MessageBox.Show(self.form, q, "Babel's Library · passwords", W.MessageBoxButtons.YesNo, W.MessageBoxIcon.Question) == W.DialogResult.Yes:
            browser.save_login(src.split("?")[0], user, pw)
            self._source()

    def fill(self):
        u = self.url()
        site = browser.site_of(u) if u.startswith("http") and not u.startswith(BASE) else ""
        W = self.W
        found = browser.logins(site=site) if site else []
        if not found:
            if W.MessageBox.Show(self.form, f"No saved passwords for {site or 'this page'}.\n\nOpen the password list (you can import passwords from another browser there)?",
                                 "Babel's Library · passwords", W.MessageBoxButtons.YesNo, W.MessageBoxIcon.Information) == W.DialogResult.Yes:
                self.core.Navigate(START + "#passwords")
            return
        if len(found) == 1:
            return self._fill(found[0])
        menu = W.ContextMenuStrip()
        for l in found:
            item = menu.Items.Add(l["username"] or "(no username)")
            item.Click += (lambda lg: (lambda s, e: self._fill(lg)))(l)
        b = self.buttons["🔑"]
        menu.Show(b, 0, b.Height)

    def _fill(self, login):
        if browser.site_of(self.url()) != login["site"]:
            return                      # the page changed site meanwhile: never fill another site's password
        pw = browser.reveal(login["id"])
        self.core.ExecuteScriptAsync(f"{FILL_JS}({json.dumps(login['username'] or '')},{json.dumps(pw)})")
        browser.used(login["id"])
