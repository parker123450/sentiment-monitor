"""预测市场、新闻、日历（第 4 步，2026-10-23）。规则在 口径.md 第五节。只描述，不进任何计算。

archive()         每次运行：新闻标题存档（每天每个话题最多 5 条，留 400 天），议息会概率每天一行。
block(today, D)   页面第 5、6 块：预测市场、首屏 3 条新闻和按话题的折叠、7 天日历（议息会概率、期权给事件的定价）；
                  给"今天要知道的"的涨跌配新闻；预测市场大变化进"今天要知道的"。
day_data()        K 线点某一天：那天存下的新闻、议息会概率；副图"下次议息会降息概率"。
"""
import csv, json, os, re
from datetime import date, datetime, timedelta, timezone

import numpy as np

from qx import store, clock, news as NW, polymarket as PM, events as EV

ARCH = os.path.join(store.HERE, "news_archive.csv")
FOMC = os.path.join(store.HERE, "fomc_history.csv")
SAID = os.path.join(store.HERE, "pm_said.json")
ARCH_DAYS, ARCH_PER = 400, 5
TOP_TOPICS = ["semis", "nvda", "tsmc", "memory", "fed", "aicredit", "trade"]
JUNK = r"Stock Price &|Latest News \||\(\w+\.\w+\) \|"          # 路透的行情页、ETP 报价页，不是新闻
BIG_CAP = 1e12
PM_MIN_VOL, PM_MIN_MOVE, PM_QUIET = 50_000, 0.15, 7
FED_PROXY = ["QQQ", "SMH"]
GROUP_KW = {
    "半导体": r"semiconductor|chip|Nvidia|TSMC|Micron|Broadcom|AMD|ASML|半导体|芯片|英伟达",
    "美股大盘": r"Wall Street|S&P|Nasdaq|stocks|equities|美股",
    "美股保险": r"volatility|VIX|selloff|sell-off|波动|恐慌",
    "日本": r"Nikkei|Japan|yen|BOJ|Bank of Japan|日经|日元|日本",
    "韩国": r"KOSPI|Korea|Samsung|Hynix|won|韩国|三星|海力士",
    "台湾": r"Taiwan|TSMC|TAIEX|台湾|台积电",
    "中国和香港": r"China|Chinese|Hang Seng|Hong Kong|yuan|PBOC|A 股|港股|恒指|人民币",
    "黄金": r"gold|黄金",
    "原油": r"oil|crude|OPEC|Brent|原油|油价",
    "美元和美债": r"Treasury|Treasuries|yield|dollar|Fed\b|Federal Reserve|美债|收益率|美元|美联储",
    "比特币": r"Bitcoin|crypto|Ether|比特币|加密",
}


def _ny_day(at):
    return datetime.fromisoformat(at).astimezone(clock.NY).date().isoformat()


def _rows(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(p, cols, rows):
    tmp = p + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in cols} for r in rows)
    os.replace(tmp, p)


def archive():
    """新闻标题和议息会概率存档（每次运行都可以调，同一天重复的会合并）。"""
    nj, _ = NW.load()
    rows = _rows(ARCH)
    have = {(r["date"], r["topic"], NW.key(r["t"])) for r in rows}
    per = {}
    for r in rows:
        per[(r["date"], r["topic"])] = per.get((r["date"], r["topic"]), 0) + 1
    for tid, xs in (nj.get("topics") or {}).items():
        for x in sorted(xs, key=lambda x: (-(x.get("k") or 1), x["at"]), reverse=False):
            d = _ny_day(x["at"])
            k = (d, tid, NW.key(x["t"]))
            if k in have or per.get((d, tid), 0) >= ARCH_PER:
                continue
            rows.append({"date": d, "topic": tid, "t": x["t"], "src": x.get("src", ""), "url": x["url"], "k": x.get("k") or 1, "at": x["at"]})
            have.add(k)
            per[(d, tid)] = per.get((d, tid), 0) + 1
    cut = (date.today() - timedelta(days=ARCH_DAYS)).isoformat()
    rows = sorted((r for r in rows if r["date"] >= cut), key=lambda r: (r["date"], r["topic"]))
    _write(ARCH, ["date", "topic", "t", "src", "url", "k", "at"], rows)
    cal = EV.load()
    fr = {(r["date"], r["meeting"]): r for r in _rows(FOMC)}
    today = datetime.now(timezone.utc).astimezone(clock.NY).date().isoformat()
    pms = {e["date"]: e["pm"] for e in cal.get("events", []) if e.get("kind") == "fomc" and e.get("pm")} | (cal.get("fomc_pm") or {})   # 下一次和下下次（口径五.1）
    for m, p in pms.items():
        if not p.get("stale"):
            fr[(today, m)] = {"date": today, "meeting": m, "hold": p["hold"], "cut": p["cut"], "hike": p["hike"]}
    _write(FOMC, ["date", "meeting", "hold", "cut", "hike"], [fr[k] for k in sorted(fr)])


def _ago(at, now):
    h = (now - datetime.fromisoformat(at)).total_seconds() / 3600
    return f"{max(1, int(h))} 小时前" if h < 24 else f"{int(h // 24)} 天前"


def news_block(now=None):
    now = now or datetime.now(timezone.utc)
    nj, _ = NW.load()
    T = nj.get("topics") or {}
    names = {t["id"]: t["name"] for t in NW.TOPICS}
    cut = (now - timedelta(hours=24)).isoformat(timespec="minutes")
    top, used = [], set()
    cands = []
    for i, tid in enumerate(TOP_TOPICS):
        for x in T.get(tid, []):
            if x["at"] >= cut and not x.get("dup") and x.get("lang") == "en" and not re.search(JUNK, x["t"]):
                cands.append((-(x.get("k") or 1), i, x["at"], tid, x))
                break
    for _, _, _, tid, x in sorted(cands, key=lambda c: (c[0], c[1]))[:3]:
        top.append(dict(topic=names.get(tid, tid), t=x["t"], src=x.get("src", ""), url=x["url"], ago=_ago(x["at"], now), k=x.get("k") or 1))
        used.add(x["url"])
    more = []
    for t in NW.TOPICS:
        xs = [dict(t=x["t"], src=x.get("src", ""), url=x["url"], ago=_ago(x["at"], now), k=x.get("k") or 1) for x in T.get(t["id"], [])
              if x["url"] not in used and not x.get("dup") and not re.search(JUNK, x["t"])][:6]
        if xs:
            more.append(dict(topic=t["name"], items=xs))
    return dict(top=top, more=more, fetched=nj.get("fetched"))


def attach_news(items, now=None):
    """给"今天要知道的"里的涨跌配同一时间的新闻（最多 2 条、最近 36 小时，按关键词）。"""
    now = now or datetime.now(timezone.utc)
    nj, _ = NW.load()
    allx = [x for xs in (nj.get("topics") or {}).values() for x in xs]
    cut = (now - timedelta(hours=36)).isoformat(timespec="minutes")
    seen = set()
    pool = []
    for x in sorted(allx, key=lambda x: x["at"], reverse=True):
        k = NW.key(x["t"])
        if x["at"] >= cut and k not in seen:
            seen.add(k)
            pool.append(x)
    for it in items:
        rx = GROUP_KW.get(it.get("group")) if it.get("kind") == "move" else None
        if not rx:
            continue
        hit = [x for x in pool if re.search(rx, x["t"], re.I)][:2]
        if hit:
            it["news"] = [dict(t=x["t"], src=x.get("src", ""), url=x["url"], ago=_ago(x["at"], now)) for x in hit]
    return items


def pm_block(now=None):
    """第 5 块和"今天要知道的"里的预测市场大变化（口径.md 五.1）。"""
    now = now or datetime.now(timezone.utc)
    j = PM.load()
    try:
        said = json.load(open(SAID, encoding="utf-8"))
    except Exception:
        said = {}
    today = now.astimezone(clock.NY).date().isoformat()
    items, topics = [], []
    for t in j.get("topics") or []:
        evs = []
        for e in t.get("events") or []:
            ms = []
            for m in e.get("markets") or []:
                ms.append(dict(label=m["label"], p=m["p"], d1=m.get("d1"), d7=m.get("d7"), vol24=m.get("vol24")))
                soon = e.get("end") and e["end"] <= (now + timedelta(days=3)).strftime("%Y-%m-%d")
                big = (m.get("vol24") or 0) >= PM_MIN_VOL and abs(m.get("d1") or 0) >= PM_MIN_MOVE and 0.03 < m["p"] < 0.97 and not soon
                last = said.get(m["id"])
                if big and (not last or (date.fromisoformat(today) - date.fromisoformat(last)).days >= PM_QUIET):
                    said[m["id"]] = last = today
                if big and last == today:
                    d1 = m["d1"] * 100
                    items.append(dict(kind="pm", key=f"pm:{m['id']}", group=t["name"], title=f"预测市场：{e['title']}" + (f" · {m['label']}" if m['label'] and m['label'] != e['title'] else "") +
                                      f"，概率一天{'升' if d1 > 0 else '降'}了 {abs(d1):.0f} 个百分点，到 {m['p'] * 100:.0f}%",
                                      facts=[f"话题：{t['name']}；这个选项 24 小时成交 {(m.get('vol24') or 0) / 1e4:,.0f} 万美元。"],
                                      mean="预测市场的概率是下注的人用钱投出来的，变化快说明有新消息或新资金；不是真实概率。",
                                      n10=None, hist="预测市场（Polymarket）", date=today, live=False, us=t["id"] in ("fed", "macro", "trade", "ai")))
            evs.append(dict(title=e["title"], end=e.get("end"), vol24=e.get("vol24"), slug=e.get("slug"), markets=ms))
        if evs:
            topics.append(dict(name=t["name"], events=evs))
    store.write_atomic(SAID, json.dumps(said))
    return dict(topics=topics, fetched=j.get("fetched")), items


def _implied(chains, sym, react):
    c = chains.get(sym)
    if not c or not c.get("curve"):
        return None
    asof = date.fromisoformat(c.get("date") or c["asof"])
    for exp, dte, iv in c["curve"]:
        e = date.fromisoformat(exp)
        if e >= react and dte > 0:
            return {"sym": sym, "exp": exp[5:], "move": round(iv / 100 * np.sqrt(max(1, (e - asof).days) / 365), 4)}
    return None


def _event_implied(chains, sym, react, tm):
    """财报：期权算的"财报这一下"，拆掉平常每天的波动（口径十四.9，和第 5 类卡同一个算法）；拆不出来不写。"""
    from qx import cboe
    em = cboe.event_move(chains.get(sym), react, two=tm not in ("盘前", "盘后"))
    return {"sym": sym, "exp": em["exp"][5:], "move": round(em["med"], 4), "ev": 1} if em else None


def calendar_block(now=None):
    now = now or datetime.now(timezone.utc)
    d0 = now.astimezone(clock.NY).date()
    end = (d0 + timedelta(days=7)).isoformat()
    try:
        chains = json.load(open(os.path.join(store.HERE, "chains_latest.json"), encoding="utf-8"))
    except Exception:
        chains = {}
    chains = {k: v for k, v in chains.items() if str(v.get("date") or v.get("asof") or "9999")[:10] <= d0.isoformat()}   # 那天以后取的不用（原则 3）
    out = []
    for e in EV.load().get("events", []):
        if not (d0.isoformat() <= e["date"] <= end):
            continue
        if e["kind"] == "earnings" and not (e.get("why") == "关注" or (e.get("cap") or 0) >= BIG_CAP):
            continue
        if e["kind"] == "beige":
            continue
        y = dict(e)
        d = date.fromisoformat(e["date"])
        if e["kind"] == "earnings":
            react = d if e.get("time") == "盘前" else d + timedelta(days=1)    # 时间未定的看当天加下一天（口径十四.9）
            while not clock.is_trading_day(react):
                react += timedelta(days=1)
            im = _event_implied(chains, e.get("sym"), react, e.get("time"))
            y["implied"] = [im] if im else []
        elif e["kind"] == "fomc":
            y["implied"] = [x for x in (_implied(chains, s, d) for s in FED_PROXY) if x]
        out.append(y)
    return out


def day_data(days=120):
    """K 线点某一天用：那天存下的新闻（最多 8 条）、议息会概率；副图"下次议息会降息概率"。"""
    names = {t["id"]: t["name"] for t in NW.TOPICS}
    rows = _rows(ARCH)
    cut = (date.today() - timedelta(days=days)).isoformat()
    news = {}
    for r in sorted(rows, key=lambda r: (r["date"], TOP_TOPICS.index(r["topic"]) if r["topic"] in TOP_TOPICS else 99, -int(r.get("k") or 1))):
        if r["date"] < cut:
            continue
        a = news.setdefault(r["date"], [])
        if len(a) < 8:
            a.append([names.get(r["topic"], r["topic"]), r["t"], r["src"], r["url"]])
    fomc = {}
    for r in _rows(FOMC):
        if r["meeting"] >= r["date"]:
            cur = fomc.get(r["date"])
            if not cur or r["meeting"] < cur[0]:
                fomc[r["date"]] = [r["meeting"], float(r["hold"]), float(r["cut"]), float(r["hike"])]
    return dict(news=news, fomc=fomc)


def block(D=None, now=None):
    pm, pm_items = pm_block(now)
    return dict(news=news_block(now), pm=pm, calendar=calendar_block(now), items=pm_items, day=day_data())
