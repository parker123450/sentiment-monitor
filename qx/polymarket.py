#!/usr/bin/env python3
"""Polymarket：议息会"不变 / 降息 / 加息"的市场概率（2026-10-23 加，第二轮规划 P1；只显示，不进任何计算）。

接口 https://gamma-api.polymarket.com/events?tag_slug=fed&closed=false（免费、不用钥匙，2026-10-23 实测）。
每次议息会有一个事件，标题 "Fed Decision in October?"，下面每个选项一个市场（groupItemTitle：No change、25 bps decrease、
50+ bps increase……），outcomePrices 第一个数是"是"的价格，就是市场认为这件事发生的概率。
匹配：标题里的英文月份 = 议息会决议日的月份，而且事件的 endDate 在决议日当天到之后 5 天内。
降息 = 所有 decrease 选项相加，加息 = 所有 increase 选项相加。取不到就不写，不报错。
"""
import json
from datetime import date, datetime

URL = "https://gamma-api.polymarket.com/events?tag_slug=fed&closed=false&limit=100"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
END_DAYS = 5


def match(events, d):
    """d（决议日）对应的事件 → {"hold": 概率, "cut": 概率, "hike": 概率, "vol": 成交额, "slug": ...}；没有就 None。"""
    want = f"Fed Decision in {MONTHS[d.month - 1]}"
    for e in events:
        if not (e.get("title") or "").startswith(want):
            continue
        try:
            end = datetime.fromisoformat(e["endDate"].replace("Z", "+00:00")).date()
        except Exception:
            continue
        if not (0 <= (end - d).days <= END_DAYS):
            continue
        out = {"hold": 0.0, "cut": 0.0, "hike": 0.0, "vol": 0.0, "slug": e.get("slug")}
        for m in e.get("markets") or []:
            if m.get("closed"):
                continue
            try:
                p = float(json.loads(m.get("outcomePrices") or "[]")[0])
            except Exception:
                continue
            g = (m.get("groupItemTitle") or "").lower()
            k = "hold" if "no change" in g else "cut" if "decrease" in g or "cut" in g else "hike" if "increase" in g or "hike" in g else None
            if k:
                out[k] += p
                out["vol"] += float(m.get("volume") or 0)
        if out["hold"] + out["cut"] + out["hike"] > 0:
            return {k: round(v, 4) if k != "slug" else v for k, v in out.items()}
    return None


def fetch(fomc_dates, get, log=print):
    """fomc_dates：决议日（YYYY-MM-DD）列表 → {日期: 概率}。整个取不到返回 {}。"""
    try:
        ev = json.loads(get(URL, timeout=30))
    except Exception as e:
        log(f"  ! Polymarket 没取到（日历里不显示概率）：{e}")
        return {}
    out = {}
    for s in fomc_dates:
        m = match(ev, date.fromisoformat(s))
        if m:
            out[s] = m
    return out


# ---------------------------------------------------------------- 话题监控（2026-10-23 夜加，第三轮第 2 步；用户："Polymarket 或者一些预测市场上的话题，你也去监控"）
# 每个话题用 Polymarket 自己的标签取事件，按 24 小时成交额排；去掉体育、每天 / 每周滚动的小盘（标签里有 SKIP_TAGS 的）。
# 每个事件取成交最多的几个还开着的市场：概率 = "是"的价格，1 天 / 1 周变化用 Polymarket 自己给的（oneDayPriceChange、oneWeekPriceChange）。
# 每天存一行到 data/raw/polymarket_history.csv（以后能在 K 线上叠加），最新一份写 data/polymarket.json。只显示，不进任何计算。
import csv, os
from datetime import datetime, timezone

TOPICS = [
    dict(id="fed", name="美联储与利率", tags=["fed", "fed-rates"]),
    dict(id="macro", name="通胀与就业", tags=["cpi-release", "jobs-report", "gdp"]),
    dict(id="trade", name="关税与贸易", tags=["tariffs", "trade"]),
    dict(id="china", name="中国与台海", tags=["china", "taiwan"], skip_words=["Mayor", "Magistrate", "Election"]),
    dict(id="geo", name="中东与俄乌", tags=["geopolitics", "iran", "ukraine"]),
    dict(id="oil", name="油价与能源", tags=["oil"]),
    dict(id="ai", name="AI 与大科技", tags=["ai", "big-tech"]),
    dict(id="crypto", name="加密", tags=["bitcoin", "ethereum"]),
    dict(id="politics", name="美国政治", tags=["midterms"]),
]
SKIP_TAGS = {"sports", "esports", "weekly", "multi-strikes", "hide-from-new", "daily-temperature", "tweets-markets"}   # 议息会带 recurring 标签，不能按它去
PER_TOPIC = 4                # 每个话题列 24 小时成交额最大的 4 个事件
PER_EVENT = 3                # 每个事件列成交最多的 3 个市场
EV_URL = "https://gamma-api.polymarket.com/events?tag_slug={}&closed=false&active=true&order=volume24hr&ascending=false&limit=25"
from qx.store import HERE                       # noqa: E402
LATEST = os.path.join(HERE, "polymarket.json")
HIST = os.path.join(HERE, "polymarket_history.csv")
HIST_COLS = ["date", "topic", "event", "market", "label", "p", "d1", "d7", "vol24"]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _event(e):
    ms = []
    for m in e.get("markets") or []:
        if m.get("closed") or not m.get("active", True):
            continue
        try:
            p = float(json.loads(m.get("outcomePrices") or "[]")[0])
        except Exception:
            continue
        ms.append({"id": str(m.get("id")), "label": (m.get("groupItemTitle") or m.get("question") or "").strip(), "p": round(p, 4),
                   "d1": _f(m.get("oneDayPriceChange")), "d7": _f(m.get("oneWeekPriceChange")), "vol": _f(m.get("volumeNum") or m.get("volume")) or 0,
                   "vol24": _f(m.get("volume24hr")) or 0})
    if not ms:
        return None
    top = sorted(ms, key=lambda m: -(m["vol24"] or m["vol"]))[:PER_EVENT]
    return {"slug": e.get("slug"), "title": (e.get("title") or "").strip(), "end": (e.get("endDate") or "")[:10],
            "vol24": _f(e.get("volume24hr")) or 0, "markets": top,
            "move": max((abs(m["d1"] or 0) for m in top), default=0)}


def snapshot(log=print, get=None):
    if get is None:
        from qx.fetch import get
    out, seen, ok = [], set(), 0
    for t in TOPICS:
        evs = []
        for tag in t["tags"]:
            try:
                for e in json.loads(get(EV_URL.format(tag), timeout=30)):
                    tags = {x.get("slug") for x in (e.get("tags") or [])}
                    if e.get("slug") in seen or tags & SKIP_TAGS or any(w in (e.get("title") or "") for w in t.get("skip_words", [])):
                        continue
                    x = _event(e)
                    if x:
                        seen.add(e.get("slug"))
                        evs.append(x)
                ok += 1
            except Exception as ex:
                log(f"  ! Polymarket 标签 {tag} 没取到：{str(ex)[:80]}")
        evs = sorted(evs, key=lambda x: -x["vol24"])[:PER_TOPIC]
        out.append({"id": t["id"], "name": t["name"], "events": evs})
    if not ok:
        raise RuntimeError("Polymarket 一个标签都没取到")
    now = datetime.now(timezone.utc)
    with open(LATEST + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"fetched": now.isoformat(timespec="minutes"), "topics": out}, f, ensure_ascii=False)
    os.replace(LATEST + ".tmp", LATEST)
    day = now.strftime("%Y-%m-%d")
    rows = []
    if os.path.exists(HIST):
        with open(HIST, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["date"] != day]
    for t in out:
        for e in t["events"]:
            for m in e["markets"]:
                rows.append({"date": day, "topic": t["id"], "event": e["slug"], "market": m["id"], "label": m["label"][:80], "p": m["p"],
                             "d1": m["d1"], "d7": m["d7"], "vol24": round(m["vol24"])})
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HIST_COLS)
        w.writeheader()
        w.writerows(rows)
    os.replace(HIST + ".tmp", HIST)
    log(f"  预测市场：{sum(len(t['events']) for t in out)} 个事件（{ok} 个标签取到）")
    return out


def load():
    try:
        with open(LATEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"fetched": None, "topics": []}
