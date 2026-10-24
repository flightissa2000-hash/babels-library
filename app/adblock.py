"""Ad blocking for the reading window (manga sites and your own search sites).

Three public lists, kept on C: (the library drive is flaky) and refreshed once a week:
  StevenBlack's unified hosts list (ad, tracker and malware domains),
  EasyList (ad servers, plus the "##" rules that hide ad boxes on any site) and EasyPrivacy (trackers).
A short built-in list of pop-under networks works before the first download and when offline.

desktop.py asks blocked(host, top) for every request the reading window makes and refuses the ad ones; it also
refuses pop-ups to other sites, and injects hide_css() so the empty spaces the ads leave behind disappear.
"""
import os
import re
import threading
import time
import urllib.request

DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "adblock")
LISTS = {
    "hosts.txt": "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "easylist.txt": "https://easylist.to/easylist/easylist.txt",
    "easyprivacy.txt": "https://easylist.to/easylist/easyprivacy.txt",
    "peterlowe.txt": "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=0&mimetype=plaintext",
    "ublock.txt": "https://ublockorigin.github.io/uAssets/filters/filters.txt",
    "adguard.txt": "https://filters.adtidy.org/extension/ublock/filters/2_without_easylist.txt",
    "annoyances.txt": "https://secure.fanboy.co.nz/fanboy-annoyance.txt",
}
# lists whose "##" rules are used to hide ad boxes (and, for annoyances, cookie banners and newsletter pop-ups)
COSMETIC = ("easylist.txt", "ublock.txt", "adguard.txt", "annoyances.txt")
WEEK = 7 * 86400

# the networks behind most pop-unders, redirects and banner ads on reading sites
CORE = """doubleclick.net googlesyndication.com googleadservices.com adservice.google.com googletagservices.com
adnxs.com criteo.com criteo.net taboola.com outbrain.com popads.net popcash.net propellerads.com propellerclick.com
exoclick.com exosrv.com juicyads.com adsterra.com adsterratools.com hilltopads.net hilltopads.com trafficjunky.net
trafficstars.com tsyndicate.com clickadu.com onclickads.net onclicka.com onclkds.com adcash.com admaven.com
ad-maven.com richpush.co monetag.com a-ads.com bidvertiser.com revcontent.com mgid.com adskeeper.com zedo.com
yieldmo.com pubmatic.com rubiconproject.com openx.net casalemedia.com amazon-adsystem.com moatads.com
scorecardresearch.com quantserve.com outbrainimg.com 33across.com sharethrough.com smartadserver.com adform.net
teads.tv undertone.com media.net adsrvr.org bidswitch.net 3lift.com lijit.com sovrn.com gumgum.com
adtrafficquality.google pagead2.googlesyndication.com securepubads.g.doubleclick.net ads.pubmatic.com
popunder.net popmyads.com clickaine.com ero-advertising.com plugrush.com realsrv.com dsp.wtf""".split()

_lock = threading.Lock()
_domains = set(CORE)
_selectors = []
_site_sels = {}       # site -> its own ad-box rules ("example.com##.promo")
_updated = 0.0
_loading = False


def _path(name):
    return os.path.join(DIR, name)


def _parse_hosts(text, out):
    for line in text.splitlines():
        if line.startswith(("0.0.0.0 ", "127.0.0.1 ")):
            d = line.split()[1].strip().lower()
            if d not in ("0.0.0.0", "localhost", "localhost.localdomain", "local", "broadcasthost"):
                out.add(d)


_NET = re.compile(r"^\|\|([a-z0-9.-]+\.[a-z]{2,})\^(?:\$(.*))?$")
_BAD_SEL = re.compile(r":-abp-|:has-text|:style|:matches-|:xpath|:upward|:remove|:watch-attr|:min-text|\{")


def _parse_easylist(text, out, sels, site_sels=None):
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "!@[":
            continue
        if site_sels is not None and "##" in line and not line.startswith("##"):
            where, sel = line.split("##", 1)
            if sel and not _BAD_SEL.search(sel) and "#" not in where and "~" not in where and "/" not in where:
                for d in where.split(","):
                    d = d.strip().lower()
                    if d and "*" not in d:
                        site_sels.setdefault(d, []).append(sel)
            continue
        m = _NET.match(line)
        if m:
            opts = m.group(2) or ""
            # rules limited to some sites, or to some request types only, would block too much as whole domains
            if "domain=" not in opts and not re.search(r"(^|,)~?(script|image|stylesheet|xmlhttprequest|media|font|object|ping|other|websocket)\b", opts):
                out.add(m.group(1))
        elif sels is not None and line.startswith("##") and not _BAD_SEL.search(line):
            sels.append(line[2:])


def _load():
    """Read the downloaded lists from disk into memory."""
    global _domains, _selectors, _site_sels, _updated
    doms, sels, site_sels, newest = set(CORE), [], {}, 0.0
    for name in LISTS:
        p = _path(name)
        if not os.path.exists(p):
            continue
        newest = max(newest, os.path.getmtime(p))
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if name in ("hosts.txt", "peterlowe.txt"):
            _parse_hosts(text, doms)
        else:
            cos = name in COSMETIC
            _parse_easylist(text, doms, sels if cos else None, site_sels if cos else None)
    sels = list(dict.fromkeys(sels))
    with _lock:
        _domains, _selectors, _site_sels, _updated = doms, sels, site_sels, newest


def _download():
    os.makedirs(DIR, exist_ok=True)
    got = 0
    for name, url in LISTS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BabelsLibrary/1.0 (adblock list update)"})
            data = urllib.request.urlopen(req, timeout=60).read()
            if len(data) < 10000:
                raise ValueError("list came back nearly empty")
            tmp = _path(name + ".part")
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, _path(name))
            got += 1
        except Exception as e:
            print(f"[inkwell] ad-block list {name} not updated: {e}")
    return got


def start():
    """Load what's on disk now; fetch fresh lists in the background when they're missing or a week old."""
    global _loading
    if _loading:
        return
    _loading = True

    def run():
        global _loading
        try:
            _load()
            stale = [n for n in LISTS if not os.path.exists(_path(n)) or time.time() - os.path.getmtime(_path(n)) > WEEK]
            if stale and _download():
                _load()
                print(f"[inkwell] ad-block lists updated: {len(_domains):,} blocked sites, {len(_selectors):,} ad-box rules")
        finally:
            _loading = False
    threading.Thread(target=run, daemon=True, name="adblock").start()


def _site(host):
    """example.co.uk / www.example.com -> the part that names the site, for first-party checks."""
    parts = host.split(".")
    n = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "ac", "or", "ne", "go") else 2
    return ".".join(parts[-n:])


def blocked(host, top=""):
    """Should a request to host be refused, on a page from top? The page's own site is never blocked."""
    if not host:
        return False
    host = host.lower().rstrip(".")
    if top and _site(host) == _site(top.lower()):
        return False
    d = _domains
    parts = host.split(".")
    return any(".".join(parts[i:]) in d for i in range(len(parts) - 1))


def hide_css():
    """The generic ad-box hiding rules, as a script that adds them to every page (in chunks, so one selector the
    browser doesn't understand only loses its own chunk)."""
    sels = _selectors
    chunks = [",".join(sels[i:i + 400]) + "{display:none!important}" for i in range(0, len(sels), 400)]
    css = "\n".join(chunks).replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return ("(()=>{const s=document.createElement('style');s.id='babel-adblock';s.textContent=`" + css + "`;"
            "const put=()=>{if(!document.getElementById('babel-adblock'))(document.head||document.documentElement).appendChild(s)};"
            "put();document.addEventListener('DOMContentLoaded',put);})();")


# YouTube serves its ads from its own servers, so blocking ad sites can't touch them. This takes the ads out of the
# player's data before the player reads it (the page's JSON and its fetches), skips any that still start (muted, at
# the end, skip pressed), hides the ad boxes in the feed, and dismisses the "ad blockers" nag so the video carries on.
YOUTUBE_JS = r"""(()=>{if(!/(^|\.)youtube(-nocookie)?\.com$/.test(location.hostname)||window.__babelYT)return;window.__babelYT=1;
const KEYS=['adPlacements','adSlots','playerAds','adBreakHeartbeatParams','adSlotRenderer'];
const prune=(o,d=0)=>{if(!o||typeof o!=='object'||d>6)return o;for(const k of KEYS)if(k in o)delete o[k];
 if(o.playerResponse)prune(o.playerResponse,d+1);if(Array.isArray(o))o.forEach(x=>prune(x,d+1));
 else if(o.contents||o.onResponseReceivedActions||o.onResponseReceivedEndpoints)strip(o);return o};
const strip=(o)=>{try{const walk=(x,d)=>{if(!x||typeof x!=='object'||d>14)return;if(Array.isArray(x)){for(let i=x.length-1;i>=0;i--){const y=x[i];
 if(y&&typeof y==='object'&&(y.adSlotRenderer||(y.richItemRenderer&&y.richItemRenderer.content&&y.richItemRenderer.content.adSlotRenderer)||y.promotedSparklesWebRenderer||y.compactPromotedVideoRenderer))x.splice(i,1);else walk(y,d+1)}}
 else for(const k in x)walk(x[k],d+1)};walk(o,0)}catch(e){}};
const P=JSON.parse;JSON.parse=function(){const r=P.apply(this,arguments);try{if(r&&typeof r==='object'&&(r.adPlacements||r.playerAds||r.adSlots||r.playerResponse||r.contents))prune(r)}catch(e){}return r};
for(const name of ['ytInitialPlayerResponse','ytInitialData']){let v;try{Object.defineProperty(window,name,{configurable:true,get(){return v},set(x){v=prune(x)}})}catch(e){}}
const F=window.fetch;window.fetch=async function(input,init){const res=await F.apply(this,arguments);try{const u=typeof input==='string'?input:(input&&input.url)||'';
 if(/\/youtubei\/v1\/(player|next|browse|search|reel)/.test(u)){const t=await res.clone().text();const j=prune(P(t));
 return new Response(JSON.stringify(j),{status:res.status,statusText:res.statusText,headers:res.headers})}}catch(e){}return res};
const css=document.createElement('style');css.textContent=`ytd-ad-slot-renderer,ytd-in-feed-ad-layout-renderer,ytd-promoted-sparkles-web-renderer,ytd-promoted-video-renderer,ytd-banner-promo-renderer,ytd-statement-banner-renderer,ytd-display-ad-renderer,ytd-companion-slot-renderer,ytd-action-companion-ad-renderer,ytd-player-legacy-desktop-watch-ads-renderer,#player-ads,#masthead-ad,.ytp-ad-overlay-container,.ytp-ad-image-overlay,.ytp-featured-product,ytd-rich-item-renderer:has(ytd-ad-slot-renderer),ytd-rich-section-renderer:has(ytd-statement-banner-renderer),ytm-promoted-sparkles-web-renderer,ytm-companion-ad-renderer,ytm-promoted-video-renderer,ad-slot-renderer,ytm-rich-item-renderer:has(ad-slot-renderer),tp-yt-paper-dialog:has(ytd-enforcement-message-view-model),ytd-enforcement-message-view-model{display:none!important}`;
const put=()=>{if(!css.isConnected)(document.head||document.documentElement).appendChild(css)};put();document.addEventListener('DOMContentLoaded',put);
setInterval(()=>{put();const p=document.querySelector('.html5-video-player');const v=document.querySelector('video');
 if(p&&v&&(p.classList.contains('ad-showing')||p.classList.contains('ad-interrupting'))){v.muted=true;try{v.playbackRate=16}catch(e){}if(isFinite(v.duration)&&v.duration>0)v.currentTime=v.duration-0.05}
 else if(v&&v.playbackRate===16){v.playbackRate=1;v.muted=false}
 document.querySelectorAll('.ytp-ad-skip-button,.ytp-ad-skip-button-modern,.ytp-skip-ad-button,.ytp-ad-skip-button-slot button,.ytm-skip-ad-button,button[class*=skip-ad]').forEach(b=>b.click());
 const nag=document.querySelector('ytd-enforcement-message-view-model');if(nag){const d=nag.closest('tp-yt-paper-dialog');if(d)d.remove();document.querySelector('tp-yt-iron-overlay-backdrop')?.remove();if(v&&v.paused&&!v.ended)v.play().catch(()=>{})}
},300)})();"""


def youtube_js():
    return YOUTUBE_JS


def hide_css_for(host):
    """The ad-box rules written for this one site (and its parent domains), as a script like hide_css()."""
    host = (host or "").lower()
    parts = host.split(".")
    sels = []
    for i in range(len(parts) - 1):
        sels += _site_sels.get(".".join(parts[i:]), [])
    if not sels:
        return ""
    css = (",".join(dict.fromkeys(sels)) + "{display:none!important}").replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return ("(()=>{if(document.getElementById('babel-adblock-site'))return;const s=document.createElement('style');s.id='babel-adblock-site';s.textContent=`" + css + "`;"
            "(document.head||document.documentElement).appendChild(s)})();")


def status():
    return {"domains": len(_domains), "selectors": len(_selectors), "site_rules": sum(len(v) for v in _site_sels.values()), "updated": _updated, "loading": _loading}
