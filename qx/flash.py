"""快讯（第四轮第 1 步，2026-10-27）。规则在 口径.md 第九节，词表在 登记/entities.toml。

每次运行（Actions 每 15 分钟；Cloudflare Worker 建好以后每 5 分钟另取一份，经 /news 取回来并进同一个文件）：
  取每条路的新条目 → 按（路, 链接）去重 → 记"看到时间" seen → 打标签（公司和机构、关键词组、六条线）→ 标"第一次" →
  存 data/news_flash.csv（打上标签的留 400 天；没打上的只留 30 天，够去重和算延迟）。
  页面"快讯"：最近 2 小时最多 20 条，同一件事几条路都有的合成一条；每条路的健康和"发布 → 看到"的实测延迟。
  推送候选：观察名单 ×（融资和信用 或 地缘和政策）的"第一次"；同一件事 1 小时内 3 家以上白名单来源报道（扩散）。回补跑完以前只标不推。
只存标题、链接、发布时间、来源、哪条路、看到时间、标签；不存正文，不转发全文。

"能看到的时间"：实时取到的条目是 seen；回补的条目没有 seen，用发布时间 pub，并标 backfill=1。"第一次"和回放都按这一列排序、截断。
"""
import csv, html, json, os, re, statistics, time, tomllib, urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from qx import store, news as NW

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(store.HERE, "news_flash.csv")
HEALTH = os.path.join(store.HERE, "flash_health.json")
ENT_FILE = os.path.join(ROOT, "登记", "entities.toml")
COLS = ["route", "id", "src", "t", "pub", "seen", "ents", "lines", "first", "backfill"]
KEEP_DAYS, KEEP_UNTAGGED_DAYS = 400, 30   # 打上标签的留 400 天；没打上的只留 30 天（2026-10-28：R6 一天两千多条、九成没标签，全留 data.enc 会到几十 MB）
FIRST_DAYS = 30                     # "第一次"：同一（主体, 线）过去 30 天在白名单来源里没出现过
SPREAD_H, SPREAD_N = 1, 3           # 扩散：同一件事 1 小时内 3 家以上白名单来源
SHOW_H, SHOW_N, SHOW_TOP = 2, 20, 3 # 页面：最近 2 小时、最多 20 条、先显示 3 条
FAIL_STOP, STOP_H = 5, 1            # 一条路连续失败 5 次停 1 小时，页面标红
BJ = timezone(timedelta(hours=8))
UA_NAMED = {"User-Agent": "qx-radar/1.0 (+https://github.com/parker123450/sentiment-monitor)"}

# ---------------------------------------------------------------- 路（2026-10-27 第 0 步实测后登记，见 docs/数据源实测.md）
# kind：rss / tv（TradingView 路透频道网页）/ wscn（华尔街见闻快讯）/ news（面板现有的要闻，qx/news.py 已经取过，这里只并进来）
# src：来源名（白名单按它算）；via：经哪里取到（页面上写"路透 · 经 TradingView"）；ua：named = 实名，panel = 面板现有来源原来的请求头
GN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
ROUTES = [
    dict(id="R6", kind="tv", src="路透", via="TradingView", url="https://www.tradingview.com/news/top-providers/reuters/", ua="named"),
    *[dict(id=f"R3:{s}", kind="rss", src="路透", via="谷歌新闻", url=GN.format(q=urllib.parse.quote(f"when:1h site:reuters.com/{s}")), ua="panel")
      for s in ("markets", "business", "technology", "world")],
    # WSJ 的公开 RSS（feeds.a.dj.com）10-27 实测最新一条在约 637 天前，已经不更新，不用；道琼斯同门的 MarketWatch 是新的
    dict(id="MarketWatch", kind="rss", src="MarketWatch", via="", url="https://feeds.content.dowjones.io/public/rss/mw_topstories", ua="named"),
    dict(id="CNBC:top", kind="rss", src="CNBC", via="", url="https://www.cnbc.com/id/100003114/device/rss/rss.html", ua="named"),
    dict(id="CNBC:markets", kind="rss", src="CNBC", via="", url="https://www.cnbc.com/id/20910258/device/rss/rss.html", ua="named"),
    dict(id="FT", kind="rss", src="金融时报", via="", url="https://www.ft.com/rss/home", ua="named"),
    dict(id="SA", kind="rss", src="Seeking Alpha", via="", url="https://seekingalpha.com/market_currents.xml", ua="named"),
    dict(id="Nikkei", kind="rss", src="日经", via="", url="https://asia.nikkei.com/rss/feed/nar", ua="named", nodate=True),   # RSS 1.0，不带发布时间
    dict(id="R5", kind="wscn", src="华尔街见闻", via="", url=NW.WSCN.format(ch="global"), ua="panel"),
    dict(id="要闻", kind="news", src="", via="谷歌新闻", url="", ua=""),
]
# 一手来源：面板已有的美联储、韩联社、CoinDesk（qx/news.py 的 FEEDS），这里也并进快讯
for _k, (_nm, _u, _keep) in NW.FEEDS.items():
    ROUTES.append(dict(id=f"一手:{_k}", kind="rss", src=_nm, via="", url=_u, ua="panel", keep=_keep))
WHITE = {"路透", "彭博", "华尔街日报", "金融时报", "CNBC", "日经", "MarketWatch", "美联储", "美联储讲话", "韩联社", "SEC"}
SRC_MAP = {"Reuters": "路透", "Bloomberg.com": "彭博", "Bloomberg": "彭博", "WSJ": "华尔街日报", "The Wall Street Journal": "华尔街日报",
           "Financial Times": "金融时报", "CNBC": "CNBC", "Nikkei Asia": "日经", "Yonhap News Agency": "韩联社"}
TV_RE = re.compile(r'\{"id":"(tag:reuters\.com[^"]+)","title":"((?:[^"\\]|\\.)*)","storyPath":"([^"]*)","published":(\d+),"urgency":(\d)')


# ================================================================ 词表和打标签
def bj_day(dt=None):
    return (dt or datetime.now(timezone.utc)).astimezone(BJ).date().isoformat()


def registry(day=None):
    """某一天（北京日期）在用的词表（只增不改：since ≤ day 且没到 until）。"""
    with open(ENT_FILE, "rb") as f:
        R = tomllib.load(f)
    day = day or bj_day()
    ok = lambda x: x.get("since", R.get("since", "")) <= day and (not x.get("until") or day < x["until"])
    return {"ent": [x for x in R.get("entity", []) + R.get("group", []) if ok(x)], "line": [x for x in R.get("line", []) if ok(x)],
            "version": R.get("version"), "since": R.get("since")}


def _alias_re(words):
    """公司和机构的别名：区分大小写，英文按整词。"""
    parts = [re.escape(w) if re.search(r"[^\x00-\x7f]", w) else r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])" for w in words]
    return re.compile("|".join(parts))


def _kw_re(words):
    """六条线的关键词：不分大小写；英文按整词，允许 s / es / d / ed / ing 词尾（bond 配 bonds，repo 不配 reports）；
    词表里以 * 结尾的按词头（refinanc* 配 refinancing）。"""
    def one(w):
        if re.search(r"[^\x00-\x7f]", w):
            return re.escape(w)
        if w.endswith("*"):
            return r"(?<![A-Za-z0-9])" + re.escape(w[:-1])
        return r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?:s|es|d|ed|ing)?(?![A-Za-z0-9])"
    return re.compile("|".join(one(w) for w in words), re.I)


_CACHE = {}


def tagger(day=None):
    reg = registry(day)
    k = (reg["version"], tuple(x["id"] for x in reg["ent"]), tuple(x["id"] for x in reg["line"]))
    if k not in _CACHE:
        _CACHE[k] = ([(x["id"], _alias_re(x["alias"]), bool(x.get("watch"))) for x in reg["ent"]],
                     [(x["id"], _kw_re(x["kw"])) for x in reg["line"]])
    return _CACHE[k]


def tag(title, day=None):
    E, L = tagger(day)
    return [i for i, rx, _ in E if rx.search(title)], [i for i, rx in L if rx.search(title)]


def watch_ids(day=None):
    return {i for i, _, w in tagger(day)[0] if w}


# ================================================================ 取
def _get(url, ua):
    from qx.fetch import get, UA
    return get(url, timeout=25, ua=UA_NAMED if ua == "named" else UA)


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def norm(link):
    """去掉查询串和锚点（谷歌新闻的文章链接本身就是编号，留着）。"""
    if "news.google.com" in link:
        return link.split("?")[0]
    u = urllib.parse.urlsplit(link)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def parse_rss(xml, r):
    out = []
    for it in re.findall(r"<item\b.*?>(.*?)</item>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1].strip()
        title = html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", g("title"))).strip()
        link = html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", g("link"))).strip()
        src = html.unescape(g("source")).strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        if r.get("keep") and not re.search(r["keep"], title, re.I):
            continue
        try:
            pub = parsedate_to_datetime(g("pubDate")).timestamp()
        except Exception:
            if not r.get("nodate"):
                continue
            pub = None                                        # 不带发布时间的源：并进来时用第一次看到的时间
        if title and link.startswith("http"):
            out.append({"id": norm(link), "t": title, "src": SRC_MAP.get(src, src) if r["kind"] == "rss" and r["id"].startswith("R3") else r["src"], "pub": pub})
    return out


def parse_tv(text, r):
    return [{"id": "https://www.tradingview.com" + path, "t": json.loads('"' + t + '"'), "src": r["src"], "pub": int(pub), "urgent": urg == "1"}
            for i, t, path, pub, urg in TV_RE.findall(text)]


def parse_wscn(text, r):
    j = json.loads(text)
    out = []
    for x in (j.get("data") or {}).get("items") or []:
        if (x.get("score") or 1) < NW.WSCN_MIN or re.search(NW.WSCN_DROP, (x.get("title") or "") + (x.get("content_text") or "")):
            continue
        t = (x.get("title") or "").strip() or re.sub(r"\s+", " ", x.get("content_text") or "").strip()[:90]
        body = t + (x.get("content_text") or "")
        src = "华尔街见闻" + ("（转述路透）" if "路透" in body else "（转述彭博）" if "彭博" in body else "")
        if t and x.get("display_time"):
            out.append({"id": f"https://wallstreetcn.com/livenews/{x['id']}", "t": t, "src": src, "pub": x["display_time"]})
    return out


def from_news():
    """面板的要闻（qx/news.py 刚取过的 news.json）：只要白名单来源的英文条目。"""
    nj, _ = NW.load()
    out = []
    for xs in (nj.get("topics") or {}).values():
        for x in xs:
            src = SRC_MAP.get(x.get("src"), x.get("src"))
            if src in WHITE and x.get("lang") == "en":
                out.append({"id": norm(x["url"]), "t": x["t"], "src": src, "pub": datetime.fromisoformat(x["at"]).timestamp()})
    return out


PARSE = {"rss": parse_rss, "tv": parse_tv, "wscn": parse_wscn}


def _health():
    try:
        return json.load(open(HEALTH, encoding="utf-8"))
    except Exception:
        return {}


def fetch_routes(now=None, log=print):
    """→ {路: [条目]}，并更新每条路的健康（连续失败、停到几点）。"""
    now = now or time.time()
    H = _health()
    got = {}
    for r in ROUTES:
        h = H.setdefault(r["id"], {"fails": 0})
        if h.get("stop_until", 0) > now:
            continue
        try:
            items = from_news() if r["kind"] == "news" else PARSE[r["kind"]](_get(r["url"], r["ua"]), r)
            got[r["id"]] = items
            h.update(fails=0, ok_at=now, n=len(items))
            h.pop("stop_until", None)
        except Exception as e:
            h["fails"] = h.get("fails", 0) + 1
            h["err"] = type(e).__name__
            if h["fails"] >= FAIL_STOP:
                h.update(stop_until=now + STOP_H * 3600, fails=0)
        time.sleep(0.4)
    store.write_atomic(HEALTH, json.dumps(H, ensure_ascii=False))
    bad = [k for k, h in H.items() if h.get("stop_until", 0) > now]
    log(f"  快讯：{sum(len(v) for v in got.values())} 条，{len(got)}/{len(ROUTES)} 条路取到" + (f"，{len(bad)} 条路停了 1 小时" if bad else ""))
    return got


# ================================================================ 存、"第一次"
def load_rows():
    if not os.path.exists(CSV):
        return []
    with open(CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows, now=None):
    now = now or datetime.now(timezone.utc)
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    cut_u = (now - timedelta(days=KEEP_UNTAGGED_DAYS)).isoformat(timespec="seconds")
    keep = lambda r: visible(r) >= (cut if (r.get("ents") or r.get("lines")) else cut_u)
    rows = sorted((r for r in rows if keep(r)), key=lambda r: (visible(r), r["route"], r["id"]))
    tmp = CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLS} for r in rows)
    os.replace(tmp, CSV)


def visible(r):
    """能看到的时间：实时的用 seen，回补的用 pub。"""
    return r.get("seen") or r["pub"]


def firsts(rows):
    """按能看到的时间排序，逐条标"第一次"：（主体, 线）在过去 FIRST_DAYS 天的白名单条目里没出现过。
    返回 {(route, id): "ent:line|..."}。同一时刻只看它以前的条目，所以截到任何一天重算，那天以前的结果不变（自检用）。"""
    last = {}
    out = {}
    for r in sorted(rows, key=lambda r: (visible(r), r["route"], r["id"])):
        if r["src"] not in WHITE:
            continue
        at = datetime.fromisoformat(visible(r))
        ents, lines = [x for x in r["ents"].split("|") if x], [x for x in r["lines"].split("|") if x]
        new = []
        for e in ents:
            for ln in lines:
                k = f"{e}:{ln}"
                prev = last.get(k)
                if prev is None or (at - prev) > timedelta(days=FIRST_DAYS):
                    new.append(k)
                last[k] = at
        if new:
            out[(r["route"], r["id"])] = "|".join(new)
    return out


def ingest(got, now=None, backfill=False):
    """新条目并进 news_flash.csv；返回这次新加的行。"""
    now = now or datetime.now(timezone.utc)
    rows = load_rows()
    have = {(r["route"], r["id"]) for r in rows}
    seen = now.isoformat(timespec="seconds")
    routes_had = {r["route"] for r in rows}
    new = []
    for route, items in got.items():
        for x in items:
            k = (route, x["id"])
            if k in have or not x.get("t"):
                continue
            if x["pub"] is None:                              # 不带发布时间：这条路第一次取到的一批当旧稿（往前记一天），之后的用看到的时间
                x = dict(x, pub=(now - timedelta(days=1 if route not in routes_had else 0)).timestamp())
            pub = _iso(x["pub"])
            ents, lines = tag(x["t"], bj_day(now))            # 用看到（回补：回补当天）那一刻在用的词表
            r = {"route": route, "id": x["id"], "src": x["src"], "t": x["t"][:300], "pub": pub, "seen": "" if backfill else seen,
                 "ents": "|".join(ents), "lines": "|".join(lines), "first": "", "backfill": "1" if backfill else ""}
            rows.append(r)
            new.append(r)
            have.add(k)
    F = firsts(rows)
    for r in rows:
        r["first"] = F.get((r["route"], r["id"]), "")
    save_rows(rows, now)
    return new


# ================================================================ 同一件事、扩散、推送候选
def events(rows, hours=SPREAD_H):
    """同一件事：标题的词重合 ≥ 一半（qx/news.py 的口径），而且能看到的时间相差不超过 hours 小时。返回 [[行, ...], ...]，新的在前。"""
    out = []
    for r in sorted(rows, key=visible, reverse=True):
        w = NW.words(r["t"])
        at = datetime.fromisoformat(visible(r))
        for ev in out:
            if w and ev["w"] and len(w & ev["w"]) / min(len(w), len(ev["w"])) >= NW.SAME and abs((ev["at"] - at).total_seconds()) <= hours * 3600:
                ev["rows"].append(r)
                break
        else:
            out.append({"w": w, "at": at, "rows": [r]})
    return [e["rows"] for e in out]


def candidates(now=None, rows=None, since_h=1):
    """推送候选（还没过推送总规则）：最近 since_h 小时新看到的。key 用来 24 小时内不重复。"""
    now = now or datetime.now(timezone.utc)
    rows = rows if rows is not None else load_rows()
    cut = (now - timedelta(hours=since_h)).isoformat(timespec="seconds")
    recent = [r for r in rows if r.get("seen") and r["seen"] >= cut]
    W = watch_ids(bj_day(now))
    out = []
    for r in recent:
        for k in [x for x in r["first"].split("|") if x]:
            e, ln = k.split(":")
            if e in W and ln in ("credit", "geo"):
                out.append(dict(kind="first", key=f"first:{k}", title=f"第一次：{name(e)} × {LINE_NAME.get(ln, ln)}", body=r["t"], src=r["src"], at=r["seen"]))
    pool = [r for r in rows if r.get("seen") and r["seen"] >= (now - timedelta(hours=since_h + SPREAD_H)).isoformat(timespec="seconds")]
    for ev in events(pool):
        srcs = {r["src"] for r in ev if r["src"] in WHITE}
        if len(srcs) >= SPREAD_N and max(r["seen"] for r in ev) >= cut:
            r0 = min(ev, key=visible)
            out.append(dict(kind="spread", key="spread:" + NW.key(r0["t"]), title=f"{len(srcs)} 家同时报道", body=r0["t"], src="、".join(sorted(srcs)), at=r0["seen"]))
    return out


LINE_NAME = {"credit": "融资和信用", "industry": "产业进度", "geo": "地缘和政策", "rates": "利率和流动性", "positioning": "仓位和资金", "narrative": "情绪和叙事"}


def name(eid):
    for i, x in enumerate(registry()["ent"]):
        if x["id"] == eid:
            return x["name"]
    return eid


# ================================================================ 延迟和页面
def lag_stats(rows, days=7, now=None):
    """每条路"发布 → 看到"的延迟（分钟）：只算这条路第一次取到以后才出现的条目（第一次取到的那一批不知道什么时候出现的）。"""
    now = now or datetime.now(timezone.utc)
    cut = (now - timedelta(days=days)).isoformat(timespec="seconds")
    first_seen = {}
    for r in rows:
        if r.get("seen"):
            first_seen[r["route"]] = min(first_seen.get(r["route"], r["seen"]), r["seen"])
    lags = {}
    nodate = {x["id"] for x in ROUTES if x.get("nodate")}
    for r in rows:
        if r.get("seen") and r["seen"] >= cut and r["seen"] > first_seen[r["route"]] and r["route"] not in nodate:
            m = (datetime.fromisoformat(r["seen"]) - datetime.fromisoformat(r["pub"])).total_seconds() / 60
            if m >= -5:                                       # 发布时间比看到还晚的（时区写错的源）不算
                lags.setdefault(r["route"].split(":")[0], []).append(max(0.0, m))
    q = lambda v, p: sorted(v)[min(len(v) - 1, int(p * len(v)))]
    return {k: {"n": len(v), "med": round(statistics.median(v)), "p90": round(q(v, 0.9))} for k, v in lags.items() if len(v) >= 5}


def _bj(iso):
    return datetime.fromisoformat(iso).astimezone(BJ).strftime("%H:%M")


def block(now=None):
    """页面"快讯"块的数据。"""
    now = now or datetime.now(timezone.utc)
    rows = load_rows()
    cut = (now - timedelta(hours=SHOW_H)).isoformat(timespec="seconds")
    recent = [r for r in rows if r.get("seen") and visible(r) >= cut and r["pub"] >= cut]     # RSS 里常混着几天前的旧稿：按发布时间也要在窗口里
    reg = registry(bj_day(now))
    en = {x["id"]: x["name"] for x in reg["ent"]}
    items = []
    for ev in events(recent):
        r0 = min(ev, key=lambda r: (r["pub"], r["seen"]))                       # 最早发布的那条当代表
        ents = sorted({e for r in ev for e in r["ents"].split("|") if e})
        lines = sorted({x for r in ev for x in r["lines"].split("|") if x})
        if not ents and not lines:
            continue                                                            # 没打上标签的只计数
        firsts_ = sorted({k for r in ev for k in r["first"].split("|") if k})
        vias = sorted({(r["src"], next((x["via"] for x in ROUTES if x["id"] == r["route"].split(":")[0] or x["id"] == r["route"]), "")) for r in ev})
        items.append(dict(_pub=r0["pub"], t=r0["t"], url=r0["id"], pub=_bj(r0["pub"]), seen=_bj(min(r["seen"] for r in ev)), src=[f"{s} · 经{v}" if v else s for s, v in vias],
                          ents=[en.get(e, e) for e in ents], lines=[LINE_NAME.get(x, x) for x in lines], first=[f"{en.get(k.split(':')[0], k)} × {LINE_NAME.get(k.split(':')[1], '')}" for k in firsts_],
                          n=len({r['src'] for r in ev})))
    items = [{k: v for k, v in x.items() if k != "_pub"} for x in sorted(items, key=lambda x: x["_pub"], reverse=True)]
    H = _health()
    t = time.time()
    lag = lag_stats(rows, now=now)
    health = []
    for r in ROUTES:
        h = H.get(r["id"], {})
        base = r["id"].split(":")[0]
        health.append(dict(id=r["id"], src=r["src"] or "白名单", via=r["via"], ok=bool(h.get("ok_at")) and h.get("stop_until", 0) <= t,
                           ago=round((t - h["ok_at"]) / 60) if h.get("ok_at") else None, fails=h.get("fails", 0), lag=lag.get(base)))
    total = len(recent)
    return dict(items=items[:SHOW_N], top=SHOW_TOP, total=total, shown=min(len(items), SHOW_N), hours=SHOW_H, health=health,
                backfill_done=_state().get("backfill_done"), version=reg["version"])


# ================================================================ 状态、回补
STATE = os.path.join(store.HERE, "flash_state.json")


def _state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def set_state(**kw):
    st = _state()
    st.update(kw)
    store.write_atomic(STATE, json.dumps(st, ensure_ascii=False))


def run(log=print, now=None):
    """每次运行：取、并进、返回推送候选（回补没跑完时返回空的，只标不推）。"""
    now = now or datetime.now(timezone.utc)
    got = fetch_routes(now.timestamp(), log)
    new = ingest(got, now)
    log(f"  快讯：新条目 {len(new)} 条，其中打上标签的 {sum(1 for r in new if r['ents'] or r['lines'])} 条")
    if not _state().get("backfill_done"):
        return []
    return candidates(now)


BACKFILL_SITES = ["reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com", "asia.nikkei.com"]


def backfill(days=FIRST_DAYS, log=print, sleep=60, now=None):
    """回补过去 30 天：谷歌新闻按日期搜（after: before:），观察名单的主体分几组，每分钟 1 次请求，跑完为止。"""
    from qx.fetch import get, UA
    now = now or datetime.now(timezone.utc)
    reg = registry(bj_day(now))
    W = [x for x in reg["ent"] if x.get("watch")]
    chunks, cur = [], []
    for x in W:
        names = [a for a in x["alias"] if re.match(r"^[\x00-\x7f]+$", a) and len(a) > 3][:2]   # 英文别名，太短的（股票代码）不搜
        if len(" OR ".join(cur + names)) > 180:
            chunks.append(cur)
            cur = []
        cur += [f'"{a}"' if " " in a else a for a in names]
    if cur:
        chunks.append(cur)
    site = " OR ".join("site:" + s for s in BACKFILL_SITES)
    n = 0
    for d in range(days, 0, -1):
        day = (now - timedelta(days=d)).date()
        got = []
        for ch in chunks:
            q = f"({' OR '.join(ch)}) ({site}) after:{day} before:{day + timedelta(days=1)}"
            try:
                xml = get(GN.format(q=urllib.parse.quote(q)), timeout=30, ua=UA)
                got += parse_rss(xml, {"id": "R3:backfill", "kind": "rss", "src": ""})
            except Exception as e:
                log(f"  ! 回补 {day} 没取到：{type(e).__name__}")
            n += 1
            time.sleep(sleep)
        new = ingest({"回补": [dict(x, src=x["src"]) for x in got]}, now, backfill=True)
        log(f"  回补 {day}：{len(new)} 条")
    set_state(backfill_done=now.isoformat(timespec="minutes"), backfill_queries=n)
    return n


# ================================================================ 给 Worker 的规则（随 /state 推过去；Worker 只查表）
def rules():
    reg = registry()
    return {"version": reg["version"], "since": reg["since"], "white": sorted(WHITE), "first_days": FIRST_DAYS, "spread": [SPREAD_H, SPREAD_N],
            "entities": [{"id": x["id"], "name": x["name"], "alias": x["alias"], "watch": bool(x.get("watch"))} for x in reg["ent"]],
            "lines": [{"id": x["id"], "name": x["name"], "kw": x["kw"]} for x in reg["line"]],
            "push_lines": ["credit", "geo"]}


# ================================================================ 和 Worker 同步（WORKER_URL、WORKER_WRITE_TOKEN 都有才做；没有就只靠 Actions 15 分钟一次）
def _worker(path, data=None, method="POST"):
    import urllib.request
    base, tok = os.environ.get("WORKER_URL", "").rstrip("/"), os.environ.get("WORKER_WRITE_TOKEN", "")
    if not base or not tok:
        return None
    req = urllib.request.Request(base + path, data=None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", **UA_NAMED}, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def sync(log=print, extra_state=None):
    """推规则、白名单"第一次"给 Worker，取回 Worker 存的快讯并进 news_flash.csv。日志只打条数。"""
    from qx import notify
    if not os.environ.get("WORKER_URL"):
        return False
    try:
        st = {"rules": {"flash": rules(), "push": notify.rules()}, **(extra_state or {})}
        if _state().get("backfill_done"):
            st["backfill_done"] = _state()["backfill_done"]
        _worker("/state", st)
        last = {}
        for r in sorted(load_rows(), key=visible):
            for k in [x for x in r["first"].split("|") if x] + [f"{e}:{ln}" for e in r["ents"].split("|") if e for ln in r["lines"].split("|") if ln]:
                if r["src"] in WHITE:
                    last[k] = int(datetime.fromisoformat(visible(r)).timestamp() * 1000)
        _worker("/firsts", [{"k": k, "at": v} for k, v in last.items()])
        since = _state().get("worker_since", int((time.time() - 86400) * 1000))
        got = (_worker(f"/news?since={since}", method="GET") or {}).get("rows") or []
        rows = load_rows()
        have = {(r["route"], r["id"]) for r in rows}
        n = 0
        for x in got:
            if (x["route"], x["id"]) in have:
                continue
            rows.append({"route": x["route"], "id": x["id"], "src": x["src"], "t": x["t"], "pub": _iso(x["pub"]), "seen": _iso(x["seen"] / 1000),
                         "ents": x["ents"] or "", "lines": x["lines"] or "", "first": "", "backfill": ""})
            n += 1
        if n:
            F = firsts(rows)
            for r in rows:
                r["first"] = F.get((r["route"], r["id"]), "")
            save_rows(rows)
        if got:
            set_state(worker_since=max(x["seen"] for x in got))
        log(f"  Worker：推了规则和 {len(last)} 个\"第一次\"，取回快讯 {n} 条")
        return True
    except Exception as e:
        log(f"  ! Worker 没连上：{type(e).__name__}")
        return False
