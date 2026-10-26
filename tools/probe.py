#!/usr/bin/env python3
"""第 0 步 · 数据源实测（第四轮规划第五节第 0 步，2026-10-26）。

对每个打算接的源各取几次，记：状态码、耗时、返回的是不是正常内容、最新一条离现在多久；另读 robots.txt 和使用条款里关于自动访问的句子。
结论（用不用、主路备路）不在这里下，人看了结果写进 docs/数据源实测.md。

规矩（第四轮规划 3.3）：
  新来源用实名 UA（UA_NAMED），不伪装浏览器；现有来源（Yahoo、谷歌新闻、华尔街见闻、纳斯达克、CNN、AAII、FRED）照面板现在的请求头。
  新闻类网站每个主机两次请求至少隔 GAP_NEWS 秒（合计每分钟不超过 1 次）；遇到 429、503 按指数退避，最多再试两次。
  R1（路透站点地图）和 Lipper Alpha 只读 robots.txt 和条款；SEC 没有联系邮箱（环境变量 SEC_CONTACT）就不测。
  金十、财联社没有公开接口：只读 robots.txt，不碰内部接口。
  标准输出只打状态码、条数和耗时（公开仓库的 Actions 日志谁都能看）；明细写进 OUT 下的 JSON。

用法：
  python tools/probe.py once                 # 所有源各取一次，写 data/probe/once-<机器>.json
  python tools/probe.py watch --rounds 12    # 每 5 分钟一轮：路透几条路的新条目（算发布到看到的延迟）、各市场行情时点，写 watch-<机器>.jsonl
  python tools/probe.py summary              # 把 watch 的结果汇总成延迟中位数（写 summary-<机器>.json）
机器名用环境变量 PROBE_WHERE（Actions 里是 actions），默认 mac。
"""
import argparse, html, json, os, re, socket, statistics, sys, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from qx import fetch, news                                                    # noqa: E402
from qx.registry import YAHOO                                                 # noqa: E402

OUT = os.path.join(ROOT, "data", "probe")
WHERE = os.environ.get("PROBE_WHERE", "mac")
UA_NAMED = {"User-Agent": "qx-radar/1.0 (+https://github.com/parker123450/sentiment-monitor)"}
UA_PANEL = fetch.UA                                                          # 面板现在给 Yahoo、谷歌新闻、华尔街见闻用的
JSON_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}          # 面板给纳斯达克用的（qx/events.py）
GAP_NEWS, GAP_DATA = 60, 1.0
NEWS_HOSTS = {"news.google.com", "www.reuters.com", "www.reutersagency.com", "api-one-wscn.awtmt.com", "insight.factset.com",
              "lipperalpha.refinitiv.com", "api.gdeltproject.org", "www.jin10.com", "www.cls.cn", "www.sec.gov", "efts.sec.gov"}
TERMS_RE = re.compile(r"[^.;:!?。]*\b(robot|robots|crawl\w*|scrap\w*|spider\w*|automat\w*|data[- ]mining|harvest\w*|bots?)\b[^.;!?。]*[.;!?。]", re.I)

# ---------------------------------------------------------------- 扫描范围（第四轮规划第五节第 2 步；代码以这里实测为准）
SCAN = {
    "美股指数和行业": ["^GSPC", "^NDX", "^RUT", "IWM", "RSP", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
                  "SMH", "IGV", "KRE", "XBI", "ITB", "XME", "XOP", "GDX", "URA", "ITA", "JETS", "TLT", "NQ=F"],
    "其他股市": ["^N225", "^KS11", "^TWII", "^HSI", "^HSTECH", "HSTECH.HK", "3033.HK", "000300.SS", "399006.SZ", "^STOXX50E", "^GDAXI",
             "INDA", "EWZ", "EEM", "KWEB"],
    "商品": ["CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F", "ZC=F", "ZS=F", "ZW=F"],
    "利率": ["^IRX", "^FVX", "^TNX", "^TYX"],
    "汇率": ["DX-Y.NYB", "JPY=X", "CNH=X", "KRW=X", "TWD=X", "EURUSD=X", "AUDUSD=X"],
    "加密": ["BTC-USD", "ETH-USD", "SOL-USD", "COIN", "MSTR"],
    "波动": ["^VIX", "^VXN", "^MOVE", "^OVX", "^GVZ"],
    "日本": ["9984.T", "6857.T", "8035.T", "6920.T", "6146.T", "285A.T"],
    "台湾": ["2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW", "2308.TW", "3711.TW"],
    "A 股和港股": ["688256.SS", "300308.SZ", "601138.SS", "688981.SS", "0981.HK", "0700.HK", "9988.HK"],
    "欧洲": ["ASML.AS", "ASM.AS", "BESI.AS", "IFX.DE"],
    "电力和数据中心": ["VST", "CEG", "GEV", "ETN", "TLN", "CORZ"],
}
# 每个市场挑一个代码看行情时点（盘中离现在多久 = 延迟）
MARKET_PICK = {"美股": "^GSPC", "美股期货": "NQ=F", "日本": "^N225", "韩国": "^KS11", "台湾": "^TWII", "香港": "^HSI", "A 股": "000300.SS",
               "深圳": "399006.SZ", "欧洲": "^STOXX50E", "德国": "^GDAXI", "荷兰": "ASML.AS", "原油": "CL=F", "汇率": "JPY=X", "加密": "BTC-USD"}
CALENDARS = ["XNYS", "XTKS", "XKRX", "XTAI", "XSHG", "XSHE", "XHKG", "XAMS", "XETR"]

R3_SECTIONS = ["markets", "business", "technology", "world"]
R3_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
R4_URLS = {"全部精选": "https://www.reutersagency.com/feed/?post_type=best",
           "商业财经": "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
           "科技": "https://www.reutersagency.com/feed/?best-topics=tech&post_type=best"}
R5_CHANNELS = ["global", "us-stock"]
GDELT_URL = ("https://api.gdeltproject.org/api/v2/doc/doc?query=domain:reuters.com&mode=artlist&format=json&maxrecords=75"
             "&timespan={span}&sort=datedesc")


def r3_url(sec, span="1h"):
    return R3_URL.format(q=urllib.parse.quote(f"when:{span} site:reuters.com/{sec}"))


# ================================================================ 取数（按主机限速）
_gate_lock = threading.Lock()
_gate = {}            # 主机 → (锁, 下次可以发的时间)


def _wait(host):
    gap = GAP_NEWS if host in NEWS_HOSTS else GAP_DATA
    with _gate_lock:
        lk = _gate.setdefault(host, [threading.Lock(), 0.0])
    lk[0].acquire()
    try:
        d = lk[1] - time.time()
        if d > 0:
            time.sleep(d)
        lk[1] = time.time() + gap
    finally:
        lk[0].release()


def req(url, headers=None, timeout=20, method="GET", data=None, tries=3):
    """→ {url, status, ms, bytes, ctype, text, err}。HTTP 错误也记状态码和返回的开头。"""
    host = urllib.parse.urlsplit(url).hostname
    out = {"url": url}
    for i in range(tries):
        _wait(host)
        t0 = time.time()
        try:
            r = urllib.request.Request(url, headers=headers or UA_NAMED, method=method, data=data)
            with urllib.request.urlopen(r, timeout=timeout, context=fetch.CTX) as f:
                b = f.read()
                out.update(status=f.status, ctype=f.headers.get("Content-Type", ""), final=f.geturl())
        except urllib.error.HTTPError as e:
            b = e.read() if hasattr(e, "read") else b""
            out.update(status=e.code, ctype=e.headers.get("Content-Type", "") if e.headers else "")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            b = b""
            out.update(status=None, err=type(e).__name__ + ": " + str(getattr(e, "reason", e))[:120])
        out["ms"] = int((time.time() - t0) * 1000)
        out["bytes"] = len(b)
        out["text"] = b.decode("utf-8", "replace") if not out.get("ctype", "").startswith(("application/vnd", "application/octet")) else ""
        out["raw"] = b
        if out.get("status") in (429, 503) and i < tries - 1:
            time.sleep(30 * 2 ** i)                        # 指数退避
            continue
        if out.get("status") is None and i == 0:           # 网络错误（连接被断、超时）再试一次
            time.sleep(10)
            continue
        break
    return out


def slim(r, keep_text=0):
    """存进结果文件的样子：不存正文（只存开头几个字用来判断是不是正常内容）。"""
    d = {k: r.get(k) for k in ("url", "status", "ms", "bytes", "ctype", "err", "final") if r.get(k) is not None}
    if keep_text:
        d["head"] = re.sub(r"\s+", " ", r.get("text") or "")[:keep_text]
    return d


# ================================================================ robots.txt 和条款
def robots(base, paths, ua=UA_NAMED):
    r = req(base.rstrip("/") + "/robots.txt", headers=ua)
    out = slim(r)
    txt = r.get("text") or ""
    if r.get("status") == 200 and "html" not in (r.get("ctype") or "").lower():
        out["allow"] = {p: {"qx-radar": allowed(txt, "qx-radar", p), "*": allowed(txt, "*", p)} for p in paths}
        cd = [ln.split(":", 1)[1].strip() for ln in txt.splitlines() if ln.lower().startswith("crawl-delay:")]
        out["crawl_delay"] = cd[0] if cd else None
        out["sitemaps"] = [ln.split(":", 1)[1].strip() for ln in txt.splitlines() if ln.lower().startswith("sitemap:")][:6]
        out["lines"] = star_group(txt)
        out["ai_block"] = bool(re.search(r"GPTBot|ClaudeBot|anthropic|CCBot|Google-Extended", txt, re.I))
    elif r.get("status") == 200:
        out["note"] = "返回的是网页不是 robots.txt"
    return out


def groups(txt):
    """robots.txt → [(UA 列表, [(允许?, 路径模式)])]。照谷歌的规范（RFC 9309）：空行不分组，连着的几行 User-agent 是一组。
    （Python 自带的 urllib.robotparser 把 User-agent 后面的空行当成一组结束，Lipper Alpha 那种写法会被读成什么都允许。）"""
    out, agents, rules = [], [], []
    for ln in txt.splitlines():
        s = ln.split("#")[0].strip()
        if ":" not in s:
            continue
        k, v = (x.strip() for x in s.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if rules:
                out.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
        elif k in ("allow", "disallow") and agents:
            if v:
                rules.append((k == "allow", v))
            elif not rules:
                rules.append((True, ""))                    # "Disallow:" 空 = 全部允许
    if agents:
        out.append((agents, rules))
    return out


def allowed(txt, ua, path):
    """这个 UA 能不能取 path（含查询串）：先找名字对得上的组，没有就用 *；最长匹配的规则说了算，一样长时允许优先。"""
    gs = groups(txt)
    mine = [r for a, r in gs if any(x != "*" and ua.lower().startswith(x) for x in a)] if ua != "*" else []
    rules = [x for r in (mine or [r for a, r in gs if "*" in a]) for x in r]
    best = None
    for ok, pat in rules:
        rx = re.escape(pat).replace(r"\*", ".*")
        rx = rx[:-2] + "$" if rx.endswith(r"\$") else rx
        if re.match(rx, path):
            key = (len(pat), ok)
            best = key if best is None or key > best else best
    return True if best is None else best[1]


def star_group(txt, n=12):
    """robots.txt 里 User-agent: * 那一组的前几行。"""
    lines, on = [], False
    for ln in txt.splitlines():
        s = ln.split("#")[0].strip()
        if not s:
            continue
        if s.lower().startswith("user-agent:"):
            on = s.split(":", 1)[1].strip() == "*"
            continue
        if on:
            lines.append(s)
    return lines[:n]


def terms(url, ua=UA_NAMED):
    r = req(url, headers=ua)
    out = slim(r)
    t = html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", r.get("text") or "", flags=re.S))
    t = re.sub(r"\s+", " ", t)
    hits = []
    for m in TERMS_RE.finditer(t):
        s = m.group(0).strip()
        if 30 < len(s) < 600 and s not in hits:
            hits.append(s)
    out["hits"] = hits[:6]
    out["words"] = len(t.split())
    return out


# ================================================================ 解析
def rss_items(xml):
    out = []
    for it in re.findall(r"<item\b.*?>(.*?)</item>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1].strip()
        title = html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", g("title"))).strip()
        link = html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", g("link"))).strip()
        src = html.unescape(g("source"))
        try:
            pub = parsedate_to_datetime(g("pubDate")).timestamp()
        except Exception:
            pub = None
        out.append({"t": title, "link": link.split("?")[0] if "news.google.com" not in link else link, "src": src, "pub": pub})
    return out


def age_min(ts, now=None):
    return None if ts is None else round(((now or time.time()) - ts) / 60, 1)


def feed_check(r, items):
    pubs = [x["pub"] for x in items if x["pub"]]
    d = slim(r, 80 if not items else 0)
    d.update(n=len(items), newest_min=age_min(max(pubs)) if pubs else None, oldest_min=age_min(min(pubs)) if pubs else None)
    return d


def wscn_items(text):
    j = json.loads(text)
    out = []
    for x in (j.get("data") or {}).get("items") or []:
        body = (x.get("title") or "") + " " + (x.get("content_text") or "")
        out.append({"id": x.get("id"), "t": re.sub(r"\s+", " ", body).strip()[:160], "pub": x.get("display_time"),
                    "reuters": "路透" in body, "score": x.get("score")})
    return out


def gdelt_items(text):
    j = json.loads(text)
    out = []
    for a in j.get("articles") or []:
        try:
            pub = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            pub = None
        out.append({"t": a.get("title"), "link": (a.get("url") or "").split("?")[0], "pub": pub})
    return out


# ================================================================ 各组
def probe_r1():
    return {"robots": robots("https://www.reuters.com", ["/", "/markets/", "/arc/outboundfeeds/sitemap-news/"]),
            "terms": terms("https://www.reuters.com/info-pages/terms-of-use/")}


def probe_r3():
    out = {"robots": robots("https://news.google.com", ["/rss/search?q=x", "/rss", "/"], ua=UA_PANEL), "sections": {}}
    for s in R3_SECTIONS:
        r = req(r3_url(s), headers=UA_PANEL)
        items = rss_items(r.get("text") or "") if r.get("status") == 200 else []
        d = feed_check(r, items)
        d["src_reuters"] = sum(1 for x in items if x["src"].lower().startswith("reuters"))
        out["sections"][s] = d
    # 实名 UA 能不能取（"待用户定"：要不要把现有来源的请求头也换成实名）
    r = req(r3_url("markets"), headers=UA_NAMED)
    out["named_ua"] = slim(r)
    return out


def probe_r4():
    out = {"robots": robots("https://www.reutersagency.com", ["/feed/", "/en/"]), "feeds": {}, "terms": {}}
    for k, u in R4_URLS.items():
        r = req(u)
        out["feeds"][k] = feed_check(r, rss_items(r.get("text") or "") if r.get("status") == 200 else [])
    for u in ("https://www.reutersagency.com/en/terms-of-use/", "https://www.reutersagency.com/terms-of-use/"):
        t = terms(u)
        out["terms"][u] = t
        if t.get("status") == 200:
            break
    return out


def probe_r5():
    out = {}
    for ch in R5_CHANNELS:
        r = req(news.WSCN.format(ch=ch), headers=UA_PANEL)
        items = wscn_items(r["text"]) if r.get("status") == 200 else []
        d = slim(r)
        rt = [x for x in items if x["reuters"]]
        d.update(n=len(items), reuters=len(rt), newest_min=age_min(max([x["pub"] for x in items if x["pub"]], default=None)),
                 newest_reuters_min=age_min(max([x["pub"] for x in rt if x["pub"]], default=None)))
        out[ch] = d
    out["robots"] = robots("https://wallstreetcn.com", ["/livenews"], ua=UA_PANEL)
    return out


def probe_factset():
    out = {"robots": robots("https://insight.factset.com", ["/", "/rss.xml"]),
           "terms": terms("https://www.factset.com/terms-of-use")}
    r = req("https://insight.factset.com/rss.xml")
    items = rss_items(r.get("text") or "") if r.get("status") == 200 else []
    out["rss"] = feed_check(r, items)
    out["rss"]["earnings_posts"] = [x["t"] for x in items if re.search(r"Earnings (Season|Insight)|S&P 500", x["t"] or "")][:5]
    return out


def probe_lipper():
    return {"robots": robots("https://lipperalpha.refinitiv.com", ["/", "/feed/"]),
            "terms": terms("https://www.lseg.com/en/policies/website-terms-of-use")}


def probe_sec():
    who = os.environ.get("SEC_CONTACT", "").strip()
    if not who:
        return {"skipped": "没有联系邮箱（SEC_CONTACT），按规划不测"}
    ua = {"User-Agent": f"qx-radar/1.0 {who}"}
    r = req("https://data.sec.gov/submissions/CIK0001045810.json", headers=ua)
    return {"submissions": slim(r)}


def probe_gn_topic():
    """面板现在用的谷歌新闻主题搜索（qx/news.py），拿"AI 融资与信用"那个主题试。"""
    t = [x for x in news.TOPICS if x["id"] == "aicredit"][0]
    r = req(news.rss_url(t["kw"]), headers=UA_PANEL)
    items = rss_items(r.get("text") or "") if r.get("status") == 200 else []
    d = feed_check(r, items)
    d["cap"] = len(items) >= news.SRC_CAP
    return d


def probe_gdelt():
    out = {"robots": robots("https://api.gdeltproject.org", ["/api/v2/doc/doc"])}
    r = req(GDELT_URL.format(span="2h"))
    try:
        items = gdelt_items(r["text"]) if r.get("status") == 200 else []
    except Exception:
        items, r["err"] = [], "不是 JSON：" + (r.get("text") or "")[:60]
    out["doc"] = feed_check(r, items)
    # 回补用：按日期段查（10/1–10/2）
    r = req("https://api.gdeltproject.org/api/v2/doc/doc?query=domain:reuters.com%20nvidia&mode=artlist&format=json&maxrecords=50"
            "&startdatetime=20261001000000&enddatetime=20261002000000")
    try:
        out["backfill"] = dict(slim(r), n=len(gdelt_items(r["text"])) if r.get("status") == 200 else 0)
    except Exception:
        out["backfill"] = dict(slim(r, 60))
    return out


def probe_cn():
    """金十、财联社：没有公开接口，只读 robots.txt。"""
    return {"jin10": robots("https://www.jin10.com", ["/"]), "cls": robots("https://www.cls.cn", ["/telegraph"])}


# ---------------------------------------------------------------- 行情
def yahoo_chart(sym, ua=UA_PANEL, rng="1d", interval="5m"):
    r = req(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={interval}", headers=ua)
    d = slim(r)
    try:
        res = json.loads(r["text"])["chart"]["result"][0]
        m = res["meta"]
        reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
        now = time.time()
        d.update(ok=True, rmt=m.get("regularMarketTime"), rmt_min=age_min(m.get("regularMarketTime")), price=m.get("regularMarketPrice") is not None,
                 tz=m.get("exchangeTimezoneName"), open_now=bool(reg and reg.get("start", 0) <= now < reg.get("end", 0)),
                 delayed_by=m.get("exchangeDataDelayedBy"), name=m.get("shortName") or m.get("longName"), currency=m.get("currency"),
                 itype=m.get("instrumentType"))
    except Exception:
        d.update(ok=False)
    return d


def yahoo_spark(syms, ver="v8"):
    host = "query1.finance.yahoo.com"
    u = f"https://{host}/{ver}/finance/spark?symbols={urllib.parse.quote(','.join(syms))}&range=1d&interval=5m"
    r = req(u, headers=UA_PANEL)
    d = slim(r, 0 if r.get("status") == 200 else 80)
    got = {}
    try:
        j = json.loads(r["text"])
        if "spark" in j:                                  # 带 meta 的格式（10-26 实测是 v7 给这种）
            for x in j["spark"].get("result") or []:
                resp = (x.get("response") or [{}])[0]
                m = resp.get("meta") or {}
                got[x["symbol"]] = {"rmt": m.get("regularMarketTime"), "n": len(resp.get("timestamp") or [])}
        else:                                             # 只有时间和收盘价的格式（10-26 实测是 v8 给这种）：没有 regularMarketTime，用最后一个时间戳
            for s, x in j.items():
                ts = x.get("timestamp") or []
                got[s] = {"rmt": None, "last_ts": ts[-1] if ts else None, "n": len(ts), "keys": sorted(x)[:12]}
    except Exception:
        pass
    d["format"] = "meta" if any(v.get("rmt") for v in got.values()) else ("flat" if got else None)
    d["got"] = got
    return d


def probe_yahoo():
    out = {"markets": {}, "spark": {}, "coverage": {}}
    for k, s in MARKET_PICK.items():
        out["markets"][k] = dict(yahoo_chart(s), sym=s)
    allsyms = list(dict.fromkeys([s for v in SCAN.values() for s in v] + YAHOO))
    # spark 一次几个：先试 20 个，不行就 10 个
    for ver in ("v8", "v7"):
        res = [yahoo_spark(allsyms[i:i + 20], ver) for i in range(0, 40, 20)]
        out["spark"][ver] = [{k: v for k, v in r.items() if k != "got"} | {"n_got": len(r["got"]), "sample": dict(list(r["got"].items())[:2]),
                              "missing": [s for s in allsyms[i * 20:(i + 1) * 20] if s not in r["got"]]} for i, r in enumerate(res)]
    # 扫描范围里每个代码：spark v8 批量取，取不到的单个用 chart 再试
    sp = {}
    for i in range(0, len(allsyms), 20):
        sp.update(yahoo_spark(allsyms[i:i + 20], "v7")["got"])
    for grp, syms in SCAN.items():
        for s in syms:
            g = sp.get(s)
            if g and g["rmt"]:
                out["coverage"][s] = {"grp": grp, "via": "spark v7", "rmt_min": age_min(g["rmt"]), "n": g["n"]}
            else:
                c = yahoo_chart(s, rng="5d", interval="1d")
                out["coverage"][s] = {"grp": grp, "via": "chart", "ok": c.get("ok"), "status": c.get("status"), "rmt_min": c.get("rmt_min"), "name": c.get("name")}
    old = [s for s in YAHOO if s not in out["coverage"]]
    out["registry_missing"] = [s for s in old if not (sp.get(s) or {}).get("rmt")]
    out["registry_n"] = len(YAHOO)
    out["named_ua"] = yahoo_chart("^GSPC", ua=UA_NAMED)        # "待用户定"：实名 UA Yahoo 收不收
    return out


def probe_earnings():
    """纳斯达克财报日历取过去的日期：有没有实际 EPS 和超预期（第 4 类卡要用）。"""
    out = {}
    for d in ("2026-10-22", "2026-10-23"):
        r = req(f"https://api.nasdaq.com/api/calendar/earnings?date={d}", headers=JSON_UA)
        x = slim(r)
        try:
            j = json.loads(r["text"])
            rows = (j.get("data") or {}).get("rows") or []
            hdr = (j.get("data") or {}).get("headers") or {}
            x.update(n=len(rows), headers=hdr, sample={k: rows[0].get(k) for k in list(hdr)[:12]} if rows else None,
                     with_eps=sum(1 for z in rows if (z.get("eps") or "").strip() not in ("", "N/A")),
                     with_surprise=sum(1 for z in rows if (z.get("surprise") or "").strip() not in ("", "N/A")))
        except Exception:
            x["ok"] = False
        out[d] = x
    r = req("https://api.nasdaq.com/api/company/NVDA/earnings-surprise", headers=JSON_UA)
    out["surprise_api"] = slim(r)
    return out


def probe_cftc():
    out = {"robots": robots("https://publicreporting.cftc.gov", ["/resource/"])}
    for k, ds in (("legacy_fut", "6dca-aqww"), ("tff_fut", "gpe5-46if"), ("disagg_fut", "72hh-3qpy")):
        r = req(f"https://publicreporting.cftc.gov/resource/{ds}.json?$limit=3&$order=report_date_as_yyyy_mm_dd%20DESC")
        x = slim(r)
        try:
            j = json.loads(r["text"])
            x.update(n=len(j), latest=(j[0].get("report_date_as_yyyy_mm_dd") or "")[:10] if j else None, cols=len(j[0]) if j else 0)
        except Exception:
            x["ok"] = False
        out[k] = x
    # 纳指 100 迷你（20974+）在金融期货报告里能不能按名字找到
    r = req("https://publicreporting.cftc.gov/resource/gpe5-46if.json?$limit=2&$order=report_date_as_yyyy_mm_dd%20DESC"
            "&$where=" + urllib.parse.quote("market_and_exchange_names like '%NASDAQ%'"))
    try:
        out["nasdaq_rows"] = [(z.get("market_and_exchange_names"), z.get("report_date_as_yyyy_mm_dd", "")[:10]) for z in json.loads(r["text"])]
    except Exception:
        out["nasdaq_rows"] = slim(r, 80)
    return out


def probe_direxion():
    out = {"robots": robots("https://www.direxion.com", ["/holdings/SOXL.csv", "/product/daily-semiconductor-bull-bear-3x-etfs"]),
           "terms": terms("https://www.direxion.com/terms-of-use")}
    for s in ("SOXL", "SOXS"):
        r = req(f"https://www.direxion.com/holdings/{s}.csv")
        x = slim(r, 160)
        x["csv"] = r.get("status") == 200 and "," in (r.get("text") or "")[:500] and "<html" not in (r.get("text") or "")[:500].lower()
        x["shares_line"] = next((ln.strip()[:120] for ln in (r.get("text") or "").splitlines()[:12] if re.search(r"shares|outstanding", ln, re.I)), None)
        out[s] = x
    return out


def probe_korea():
    """KOFIA（投资者存款、信用融资余额）、SEIBro、KRX Open API：只看有没有公开的取法和注册要求。"""
    out = {"kofia_robots": robots("https://freesis.kofia.or.kr", ["/"]), "kofia_home": slim(req("https://freesis.kofia.or.kr/"), 120),
           "seibro_robots": robots("https://seibro.or.kr", ["/"]), "seibro_api": slim(req("https://seibro.or.kr/OpenPlatform/callOpenAPI.jsp"), 160),
           "krx_robots": robots("https://openapi.krx.co.kr", ["/"]), "krx_home": slim(req("https://openapi.krx.co.kr/contents/OPP/MAIN/main/index.cmd"), 160),
           "datagokr": slim(req("https://www.data.go.kr/data/15094809/openapi.do"), 160)}
    return out


def probe_short():
    out = {"finra_robots": robots("https://www.finra.org", ["/finra-data/"])}
    r = req("https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest?limit=3", headers=dict(UA_NAMED, Accept="application/json"))
    out["finra_api"] = slim(r, 160)
    # Reg SHO 每日卖空成交量（公开文件）：最近一个美股交易日
    d = datetime.now(timezone.utc) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    r = req(f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d:%Y%m%d}.txt")
    out["regsho_daily"] = dict(slim(r, 100), day=f"{d:%Y-%m-%d}", lines=len((r.get("text") or "").splitlines()))
    r = req("https://api.nasdaq.com/api/quote/NVDA/short-interest?assetClass=stocks", headers=JSON_UA)
    x = slim(r)
    try:
        rows = ((json.loads(r["text"]).get("data") or {}).get("shortInterestTable") or {}).get("rows") or []
        x.update(n=len(rows), latest=rows[0] if rows else None)
    except Exception:
        x["ok"] = False
    out["nasdaq_si"] = x
    return out


def probe_treasury():
    out = {"robots": robots("https://www.treasurydirect.gov", ["/TA_WS/securities/auctioned"])}
    r = req("https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days=14")
    x = slim(r)
    try:
        j = json.loads(r["text"])
        x.update(n=len(j), latest=max((z.get("auctionDate") or z.get("issueDate") or "")[:10] for z in j) if j else None,
                 fields=[k for k in ("highYield", "bidToCoverRatio", "indirectBidderAccepted", "directBidderAccepted") if j and k in j[0]])
    except Exception:
        x["ok"] = False
    out["auctioned"] = x
    # 财政部 Fiscal Data（给程序用的公开接口）的拍卖结果，TreasuryDirect 的 robots.txt 不让取时用它
    out["fiscal_robots"] = robots("https://api.fiscaldata.treasury.gov", ["/services/api/"])
    r = req("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?sort=-auction_date&page%5Bsize%5D=5")
    x = slim(r)
    try:
        j = json.loads(r["text"]).get("data") or []
        x.update(n=len(j), latest=j[0].get("auction_date") if j else None,
                 fields=[k for k in ("high_yield", "bid_to_cover_ratio", "indirect_bidder_accepted", "direct_bidder_accepted") if j and k in j[0]])
    except Exception:
        x["ok"] = False
    out["fiscaldata"] = x
    return out


def probe_mof():
    out = {"robots": robots("https://www.mof.go.jp", ["/jgbs/reference/interest_rate/jgbcme.csv"])}
    # 规划里写的 jgbcme.csv / jgbcme_all.csv 在日文站是 404（10-26）：日文站是 jgbcm.csv、data/jgbcm_all.csv，英文站在 /english/policy/ 下
    for k, u in (("当月", "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"),
                 ("当月英文", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"),
                 ("全量", "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv")):
        r = req(u)
        x = slim(r)
        raw = r.get("raw") or b""
        try:
            t = raw.decode("shift_jis", "replace")
        except Exception:
            t = ""
        rows = [ln for ln in t.splitlines() if re.match(r"^[RHS]?\d", ln)]
        x.update(rows=len(rows), first=rows[0][:60] if rows else None, last=rows[-1][:80] if rows else None)
        out[k] = x
    return out


def probe_calendars():
    try:
        import exchange_calendars as xc
        import pandas as pd
    except Exception as e:
        return {"err": f"没装 exchange_calendars：{e}"}
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    out = {"version": getattr(xc, "__version__", "?")}
    for c in CALENDARS:
        try:
            k = xc.get_calendar(c)
            s = k.is_session(today)
            bs = k.session_break_start(today) if s else None
            out[c] = {"session": bool(s), "open": str(k.session_open(today)) if s else None, "close": str(k.session_close(today)) if s else None,
                      "break": str(bs) if s and not pd.isna(bs) else None, "last_session": str(k.last_session.date())}
        except Exception as e:
            out[c] = {"err": type(e).__name__ + ": " + str(e)[:80]}
    # 11/3 日本文化之日（规划第 2 步验收要测休市）
    try:
        out["XTKS_2026-11-03"] = bool(xc.get_calendar("XTKS").is_session(pd.Timestamp("2026-11-03")))
    except Exception as e:
        out["XTKS_2026-11-03"] = str(e)[:60]
    return out


def probe_existing():
    """现有来源的请求头（待用户定）：CNN、AAII 现在用浏览器 UA，试一次实名 UA 收不收。"""
    out = {}
    r = req(fetch.CNN_URL, headers=UA_NAMED)
    out["cnn_named"] = slim(r, 60)
    r = req(fetch.CNN_URL, headers=dict(fetch.BROWSER, Referer="https://www.cnn.com/", Origin="https://www.cnn.com"))
    out["cnn_panel"] = slim(r)
    r = req(fetch.AAII_URL, headers=UA_NAMED)
    out["aaii_named"] = dict(slim(r), xls=(r.get("raw") or b"")[:4] == b"\xd0\xcf\x11\xe0")
    r = req(fetch.AAII_URL, headers=fetch.BROWSER)
    out["aaii_panel"] = dict(slim(r), xls=(r.get("raw") or b"")[:4] == b"\xd0\xcf\x11\xe0")
    r = req("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS30", headers=UA_PANEL)
    out["fred_dgs30"] = dict(slim(r), last=((r.get("text") or "").strip().splitlines() or [""])[-1][:30])
    return out


def probe_size():
    """现在页面加密包多大（第 2 步首屏不超过它的 1.5 倍）；data 分支的 data.enc 多大。"""
    out = {"page": slim(req("https://parker123450.github.io/sentiment-monitor/", headers=UA_NAMED))}
    r = req("https://raw.githubusercontent.com/parker123450/sentiment-monitor/data/data.enc", headers=UA_NAMED)
    out["data_enc"] = slim(r)
    return out


GROUPS = {"R1": probe_r1, "R3": probe_r3, "R4": probe_r4, "R5": probe_r5, "FactSet": probe_factset, "Lipper": probe_lipper, "SEC": probe_sec,
          "谷歌新闻主题": probe_gn_topic, "GDELT": probe_gdelt, "金十财联社": probe_cn, "Yahoo": probe_yahoo, "纳斯达克财报": probe_earnings,
          "CFTC": probe_cftc, "Direxion": probe_direxion, "韩国": probe_korea, "空头": probe_short, "TreasuryDirect": probe_treasury,
          "财务省": probe_mof, "交易所日历": probe_calendars, "现有来源请求头": probe_existing, "页面大小": probe_size}


def strip_raw(x):
    if isinstance(x, dict):
        return {k: strip_raw(v) for k, v in x.items() if k not in ("raw", "text")}
    if isinstance(x, list):
        return [strip_raw(v) for v in x]
    return x


def statuses(x, acc=None):
    """日志用：只收集状态码和耗时。"""
    acc = acc if acc is not None else []
    if isinstance(x, dict):
        if "url" in x and ("status" in x or "err" in x):
            acc.append((x.get("status") or "ERR", x.get("ms")))
        for v in x.values():
            statuses(v, acc)
    elif isinstance(x, list):
        for v in x:
            statuses(v, acc)
    return acc


def once(only=None):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    res = {"where": WHERE, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "groups": {}}
    names = [g for g in GROUPS if not only or g in only]

    def run(g):
        a = time.time()
        try:
            r = GROUPS[g]()
        except Exception as e:
            r = {"crash": type(e).__name__ + ": " + str(e)[:160]}
        st = statuses(r)
        print(f"  {g}：{len(st)} 次请求，状态 " + " ".join(str(s) for s, _ in st[:14]) + ("…" if len(st) > 14 else "")
              + f"，{time.time() - a:.0f} 秒", flush=True)
        return g, strip_raw(r)

    with ThreadPoolExecutor(max_workers=len(names)) as ex:
        for g, r in ex.map(run, names):
            res["groups"][g] = r
    res["secs"] = round(time.time() - t0)
    p = os.path.join(OUT, f"once-{WHERE}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"写入 {os.path.relpath(p, ROOT)}，共 {res['secs']} 秒")


# ================================================================ watch：每 5 分钟一轮，算"发布 → 看到"的延迟
def watch_round(k):
    """第 k 轮（从 0 起）：R3 四个栏目、R5 两个频道每轮都取；R4 和 GDELT 每 3 轮（15 分钟）取一次；各市场行情时点每轮取。"""
    now = time.time()
    rec = {"k": k, "at": now, "routes": {}, "mkt": {}}
    jobs = [("R3:" + s, lambda s=s: rss_items(_ok(req(r3_url(s), headers=UA_PANEL)))) for s in R3_SECTIONS]
    jobs += [("R5:" + c, lambda c=c: [x for x in wscn_items(_ok(req(news.WSCN.format(ch=c), headers=UA_PANEL))) if x["reuters"]]) for c in R5_CHANNELS]
    if k % 3 == 0:
        jobs += [("R4:" + n, lambda u=u: rss_items(_ok(req(u)))) for n, u in R4_URLS.items()]
        jobs += [("GDELT", lambda: gdelt_items(_ok(req(GDELT_URL.format(span="1h")))))]

    def run(j):
        name, fn = j
        t = time.time()
        try:
            items = fn()
            return name, {"ok": True, "seen": t, "items": [{"id": str(x.get("link") or x.get("id")), "t": x.get("t"), "pub": x.get("pub")} for x in items]}
        except Exception as e:
            return name, {"ok": False, "err": type(e).__name__ + ": " + str(e)[:80]}

    with ThreadPoolExecutor(max_workers=8) as ex:
        for name, r in ex.map(run, jobs):
            rec["routes"][name] = r
    sp = yahoo_spark(list(MARKET_PICK.values()), "v7")["got"]
    for m, s in MARKET_PICK.items():
        rec["mkt"][m] = {"sym": s, "rmt": (sp.get(s) or {}).get("rmt")}
    return rec


def _ok(r):
    if r.get("status") != 200:
        raise RuntimeError(f"HTTP {r.get('status')} {r.get('err') or ''}")
    return r["text"]


def watch(rounds, every=300):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"watch-{WHERE}.jsonl")
    t0 = time.time()
    for k in range(rounds):
        a = time.time()
        rec = watch_round(k)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        st = " ".join(f"{n}={'ok' if r['ok'] else 'X'}/{len(r.get('items') or [])}" for n, r in rec["routes"].items())
        print(f"  第 {k + 1}/{rounds} 轮（{time.time() - a:.0f} 秒）：{st}", flush=True)
        if k < rounds - 1:
            time.sleep(max(0, t0 + (k + 1) * every - time.time()))
    print(f"写入 {os.path.relpath(p, ROOT)}")


def summary():
    """watch 结果 → 每条路：新条目数、发布到看到的延迟（分钟）中位数和 90% 分位、失败轮数；各市场行情时点离取的时候多久。
    第一轮看到的条目不知道什么时候出现的，不算；之后第一次出现的才算"新"。延迟里含最多一个轮询间隔。"""
    out = {}
    for fn in sorted(os.listdir(OUT)):
        if not fn.startswith("watch-"):
            continue
        where = fn[len("watch-"):-len(".jsonl")]
        recs = [json.loads(ln) for ln in open(os.path.join(OUT, fn), encoding="utf-8") if ln.strip()]
        seen, first, lag, fail, polls, mkt = {}, {}, {}, {}, {}, {}
        for rec in recs:
            for name, r in rec["routes"].items():
                polls[name] = polls.get(name, 0) + 1
                if not r["ok"]:
                    fail[name] = fail.get(name, 0) + 1
                    continue
                s = seen.setdefault(name, set())
                new = [x for x in r["items"] if x["id"] not in s]
                if name in first and new:
                    lag.setdefault(name, []).extend((r["seen"] - x["pub"]) / 60 for x in new if x["pub"])
                first.setdefault(name, rec["k"])
                s.update(x["id"] for x in r["items"])
            for m, x in rec["mkt"].items():
                if x["rmt"]:
                    mkt.setdefault(m, []).append(round((rec["at"] - x["rmt"]) / 60, 1))
        q = lambda v, p: round(sorted(v)[min(len(v) - 1, int(p * len(v)))], 1)
        out[where] = {"rounds": len(recs), "from": datetime.fromtimestamp(recs[0]["at"], timezone.utc).isoformat(timespec="minutes") if recs else None,
                      "routes": {n: {"polls": polls[n], "fail": fail.get(n, 0), "new": len(lag.get(n, [])),
                                     "lag_med": round(statistics.median(lag[n]), 1) if lag.get(n) else None,
                                     "lag_p90": q(lag[n], 0.9) if lag.get(n) else None, "lag_min": round(min(lag[n]), 1) if lag.get(n) else None}
                                 for n in polls},
                      "mkt_lag": {m: {"min": min(v), "med": statistics.median(v), "n": len(v)} for m, v in mkt.items()}}
        p = os.path.join(OUT, f"summary-{where}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out[where], f, ensure_ascii=False, indent=1)
        for n, r in out[where]["routes"].items():
            print(f"  {where} {n}：取 {r['polls']} 次，失败 {r['fail']}，新条目 {r['new']}，延迟中位数 {r['lag_med']} 分钟")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["once", "watch", "summary"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--every", type=int, default=300)
    a = ap.parse_args()
    if a.cmd == "once":
        once(a.only)
    elif a.cmd == "watch":
        watch(a.rounds, a.every)
    else:
        summary()
