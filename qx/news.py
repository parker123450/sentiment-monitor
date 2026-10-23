#!/usr/bin/env python3
"""市场发生了什么 · 要闻收集（2026-10-23 用户要求：终端每天自己去收集关注市场的消息）

做法：每个主题在可靠来源里搜（谷歌新闻 RSS 加 site: 白名单）、加一手来源和华尔街见闻"重要"快讯；按标题去重、同一件事合并，保留最近 7 天。
另外每天记一次每个主题有多少条报道（data/news_count.json，保留 90 天），用来看哪件事在升温。
这里只收集标题、来源、时间、链接，不做摘要、不打分、不进任何计算（"模型只处理文字"，这里连模型都没有）。

输出：data/news.json   {"fetched": 时间, "basis": 口径, "topics": {主题: [{"t": 标题, "src": 来源, "at": UTC 时间, "url": 链接, "lang": en/zh, "k": 几家报道}, ...]}}
      data/news_count.json {"basis": 口径, "days": {日期: {主题: 最近一天的条数}}}

用法：python3 data/news.py
"""
import html, json, os, re, sys, time, urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qx import store                                           # noqa: E402

NEWS = os.path.join(store.HERE, "news.json")
COUNT = os.path.join(store.HERE, "news_count.json")
KEEP_DAYS = 7
COUNT_DAYS = 90
PER_TOPIC = 40                    # 每个主题最多留多少条（页面只显示最新的几条）
# 热度（显示惯例，2026-10-23 登记，改了记口径变更）：今天条数 ≥ 前 7 天中位数 2 倍、且 ≥ 20 条，标"升温"；前面不满 3 天的不标
HEAT_X, HEAT_MIN, HEAT_BASE, HEAT_MIN_DAYS, HEAT_BARS = 2, 20, 7, 3, 14
SRC_CAP = 100                     # 谷歌新闻一次最多给 100 条：到了就是封顶，实际可能更多
SAME = 0.5                        # 两条标题的词重合 ≥ 一半算同一件事（合并成一条，记几家报道）

# 2026-10-23 第二版（用户："不是什么都要，筛掉无用的噪音，特别是国内的噪音"）：
# 第一版按关键词泛搜，中英各一半；7 天 440 条里只有 43 条来自可靠来源，最多的是搜狐、新浪转载和"Chennai gold price"一类。
# 第二版只收三种：① 谷歌新闻 RSS 限定可靠来源（site: 白名单）；② 一手来源（美联储声明和讲话）和几家专门的源（韩联社英文、CoinDesk）；
# ③ 中文只收华尔街见闻快讯里网站标为"重要"的（score ≥ 2）。改来源或白名单要在 docs/口径变更.md 记一行。
BASIS = "白名单 v4（2026-10-23）"
SITES = ["reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com", "asia.nikkei.com"]
SITES_KR = SITES + ["en.yna.co.kr", "koreaherald.com", "koreajoongangdaily.joins.com"]
# 谷歌新闻偶尔不守 site: 限制（关键词多时），取回来再按来源名核一遍
SRC_OK = {"Reuters", "Bloomberg.com", "Bloomberg", "WSJ", "The Wall Street Journal", "Financial Times", "CNBC", "Nikkei Asia",
          "Yonhap News Agency", "The Korea Herald", "Korea JoongAng Daily"}
FED_KEEP = r"FOMC|Federal Open Market|monetary policy|statement|minutes|discount rate|Beige Book|balance sheet|financial stability|Chair|Powell|economic projections"
KR_KEEP = r"KOSPI|stock|shares|won|Samsung|SK hynix|chip|semiconductor|export|Bank of Korea|BOK|rate"
FEEDS = {
    "fed_press": ("美联储", "https://www.federalreserve.gov/feeds/press_all.xml", FED_KEEP),
    "fed_speech": ("美联储讲话", "https://www.federalreserve.gov/feeds/speeches.xml", None),
    "yonhap": ("韩联社", "https://en.yna.co.kr/RSS/news.xml", KR_KEEP),
    "coindesk": ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", None),
}
WSCN = "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel={ch}-channel&limit=100"
WSCN_MIN = 2                      # 华尔街见闻快讯的重要度：2 = 网站标"重要"

# 主题登记：id、名字、标题关键词（谷歌新闻里用 intitle: 只搜标题，只在白名单来源里搜；取回来再按标题核一遍）、额外的源。
# 不用 intitle 时谷歌按正文匹配，100 条里只有约 10 条标题和主题有关（2026-10-23 实测）。
TOPICS = [
    dict(id="semis", name="半导体板块", kw=["semiconductor", "semiconductors", "chipmaker", "chipmakers", "chip", "chips", "foundry"]),
    dict(id="nvda", name="英伟达与 AI 算力", kw=["Nvidia", "AI chips", "AI spending", "AI capex", "hyperscaler", "hyperscalers", "data center", "data centers"]),
    dict(id="tsmc", name="台积电", kw=["TSMC", "Taiwan Semiconductor"]),
    dict(id="memory", name="存储（海力士、三星、美光）", kw=["SK Hynix", "Hynix", "Micron", "Samsung", "HBM", "memory chip", "memory chips", "DRAM", "NAND"]),
    dict(id="fed", name="美联储与利率", kw=["Federal Reserve", "Fed", "Powell", "Treasury yields", "Treasuries", "rate cut", "rate cuts", "rate hike", "inflation", "payrolls"],
         feeds=["fed_press", "fed_speech"]),
    dict(id="trade", name="关税与出口管制", kw=["export controls", "export curbs", "export ban", "tariff", "tariffs", "trade war", "entity list"]),
    # 用户要盯 AI 相关信用（10-22 Meta CDS 创纪录、甲骨文发债），CDS 没有免费数字，先把这类消息收进来
    dict(id="aicredit", name="AI 融资与信用", kw=["AI debt", "AI bond", "bond sale", "bond deal", "credit default", "CDS", "private credit", "CoreWeave",
                                                "debt financing", "data center financing", "credit spreads"]),
    dict(id="korea", name="韩国市场", kw=["KOSPI", "Korea", "Korean", "Seoul stocks"], sites=SITES_KR, feeds=["yonhap"]),
    dict(id="china", name="A 股与港股", kw=["China stocks", "Chinese stocks", "Hang Seng", "Hong Kong stocks", "yuan", "PBOC", "China's economy"],
         wscn=["a-stock", "hk-stock"]),
    dict(id="crypto", name="加密货币", kw=["Bitcoin", "crypto", "Ether", "stablecoin", "stablecoins"], feeds=["coindesk"]),
    dict(id="commod", name="黄金与原油", kw=["gold", "oil", "OPEC", "crude", "copper"]),
    dict(id="wscn", name="中文快讯 · 重要", wscn=["us-stock", "global"]),
]
# 中文快讯里个股的季报流水（"前三季度归母净利润……"）对你没用，去掉；大事（指数、政策、央行）留着
WSCN_DROP = r"归母净利润|营业收入|营收同比|净利润同比|扣非|^提醒：日内请重点关注|^早间要闻汇总"


def kw_re(kw):
    return re.compile("|".join(rf"\b{re.escape(k)}\b" if re.match(r"^[\w ']+$", k) else re.escape(k) for k in kw), re.I)


def rss_url(kw, sites=SITES):
    q = " OR ".join(f'intitle:"{k}"' if " " in k else f"intitle:{k}" for k in kw)
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"({q}) when:1d (" + " OR ".join("site:" + d for d in sites) + ")")
            + "&hl=en-US&gl=US&ceid=US:en")


def parse(xml, lang, src=None, keep=None):
    """RSS → 条目列表。用正则取字段（不解析实体、不跟外部引用）。src：源自己没有 <source> 时用这个名字；keep：标题要匹配的正则。"""
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]
        title = html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", g("title").strip())).strip()
        s_ = html.unescape(g("source")).strip() or src or ""
        if s_ and title.endswith(" - " + s_):
            title = title[: -len(s_) - 3].strip()
        if keep and not re.search(keep, title, re.I):
            continue
        try:
            at = parsedate_to_datetime(g("pubDate").strip()).astimezone(timezone.utc)
        except Exception:
            continue
        link = html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", g("link").strip())).strip()
        if title and link.startswith("https://"):
            out.append({"t": title, "src": s_, "at": at.isoformat(timespec="minutes"), "url": link, "lang": lang})
    return out


def wscn(ch, get):
    """华尔街见闻快讯：只要网站标为"重要"的（score ≥ WSCN_MIN）。"""
    j = json.loads(get(WSCN.format(ch=ch), timeout=30))
    out = []
    for x in (j.get("data") or {}).get("items") or []:
        if (x.get("score") or 1) < WSCN_MIN or re.search(WSCN_DROP, (x.get("title") or "") + (x.get("content_text") or "")):
            continue
        t = (x.get("title") or "").strip() or re.sub(r"\s+", " ", x.get("content_text") or "").strip()[:90]
        if not t or not x.get("display_time"):
            continue
        out.append({"t": t, "src": "华尔街见闻", "at": datetime.fromtimestamp(x["display_time"], timezone.utc).isoformat(timespec="minutes"),
                    "url": f"https://wallstreetcn.com/livenews/{x['id']}", "lang": "zh"})
    return out


def key(title):
    """去重用：去掉标点空白、转小写，取前 40 个字。"""
    return re.sub(r"[\W_]+", "", title.lower())[:40]


STOP = set("the a an and or of to in on for with as at by from is are be its it this that after amid over new says say will".split())


def words(title):
    """比较两条是不是同一件事用：英文取 3 个字母以上的词，中文取相邻两个字。"""
    t = title.lower()
    w = {x for x in re.findall(r"[a-z0-9]{3,}", t) if x not in STOP}
    zh = re.sub(r"[^一-鿿]", "", t)
    return w | {zh[i:i + 2] for i in range(len(zh) - 1)}


def cluster(items):
    """同一件事多家报道合并成一条（按时间从新到旧，保留最新的那条），k = 几家来源报道过。"""
    out = []
    for x in items:
        w = words(x["t"])
        for y in out:
            if w and y["_w"] and len(w & y["_w"]) / min(len(w), len(y["_w"])) >= SAME:
                y["_srcs"].add(x.get("src") or "")
                break
        else:
            out.append(dict(x, _w=w, _srcs={x.get("src") or ""}))
    return [{**{k: v for k, v in y.items() if not k.startswith("_")}, "k": len(y["_srcs"])} for y in out]


def fetch(log=print, now=None):
    from qx.fetch import get
    now = now or datetime.now(timezone.utc)
    try:
        with open(NEWS, encoding="utf-8") as f:
            oj = json.load(f)
        old = oj.get("topics", {}) if oj.get("basis") == BASIS else {}     # 换了来源口径：旧的泛搜条目不要了
    except Exception:
        old = {}
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="minutes")
    day_cut = (now - timedelta(hours=24)).isoformat(timespec="minutes")
    topics, counts, ok, tried = {}, {}, 0, 0
    seen_all = set()
    cache = {}
    for t in TOPICS:
        items = []
        jobs = ([("gn", t["kw"])] if t.get("kw") else []) + [("feed", f) for f in t.get("feeds", [])] + [("wscn", c) for c in t.get("wscn", [])]
        for kind, q in jobs:
            tried += 1
            try:
                if kind == "gn":
                    rx = kw_re(q)
                    items += [x for x in parse(get(rss_url(q, t.get("sites", SITES)), timeout=30), "en") if rx.search(x["t"]) and x["src"] in SRC_OK]
                elif kind == "feed":
                    nm, url, keep = FEEDS[q]
                    if url not in cache:
                        cache[url] = get(url, timeout=30)
                    items += parse(cache[url], "en", nm, keep)
                else:
                    items += wscn(q, get)
                ok += 1
            except Exception as e:
                log(f"  ! 要闻 {t['name']}（{str(q)[:40]}）没取到：{e}")
            time.sleep(0.4)
        counts[t["id"]] = sum(1 for x in items if x["at"] >= day_cut)
        merged, seen = [], set()
        for x in sorted(items + old.get(t["id"], []), key=lambda x: x["at"], reverse=True):
            k = key(x["t"])
            if x["at"] < cut or k in seen:
                continue
            seen.add(k)
            merged.append(dict(x, dup=k in seen_all))          # 别的主题已经有这条：页面上可以不重复显示
            seen_all.add(k)
        topics[t["id"]] = cluster(merged)[:PER_TOPIC]
    if not ok:
        raise RuntimeError("一个要闻源都没取到")
    store.write_atomic(NEWS, json.dumps({"fetched": now.isoformat(timespec="minutes"), "basis": BASIS, "topics": topics}, ensure_ascii=False))
    try:
        with open(COUNT, encoding="utf-8") as f:
            cj = json.load(f)
        hist = cj.get("days", {}) if cj.get("basis") == BASIS else {}      # 口径换了，条数不能和以前比，从头攒
    except Exception:
        hist = {}
    hist[now.strftime("%Y-%m-%d")] = counts
    keep = sorted(hist)[-COUNT_DAYS:]
    store.write_atomic(COUNT, json.dumps({"basis": BASIS, "days": {k: hist[k] for k in keep}}, ensure_ascii=False))
    log("  要闻：" + "，".join(f"{t['name']} {counts[t['id']]}" for t in TOPICS) + f"（最近 24 小时条数；{ok}/{tried} 个源取到）")
    return topics


def cap(t):
    """这个主题的条数到多少算封顶（谷歌新闻一次最多 100 条；其他源不封顶）。"""
    return SRC_CAP if t.get("kw") else None


def load():
    try:
        with open(NEWS, encoding="utf-8") as f:
            news = json.load(f)
    except Exception:
        news = {"fetched": None, "topics": {}}
    try:
        with open(COUNT, encoding="utf-8") as f:
            cj = json.load(f)
        counts = cj.get("days", {}) if cj.get("basis") == BASIS else {}
    except Exception:
        counts = {}
    if news.get("basis") != BASIS:                                  # 还是第一版泛搜的条目：不显示
        news = {"fetched": news.get("fetched"), "topics": {}}
    return news, counts


if __name__ == "__main__":
    fetch()
