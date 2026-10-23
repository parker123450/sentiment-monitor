#!/usr/bin/env python3
"""日历：接下来两周会发生什么（从旧终端 data/events.py 改来，2026-10-23 加了美国宏观数据、日韩央行、月度期权到期）。

三个免费源（2026-10-23 实测能取到）：
  美联储      https://www.federalreserve.gov/json/calendar.json   议息会决议日、发布会、纪要、褐皮书、主席讲话和听证
  纳斯达克财报 https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD      关注公司 + 市值 ≥ 2000 亿美元的公司
  纳斯达克宏观 https://api.nasdaq.com/api/calendar/economicevents?date=YYYY-MM-DD  CPI、非农、PCE、GDP、零售、ISM、日韩央行
  （BLS 自己的日程对程序回 403，所以用纳斯达克的。）
月度期权到期：每月第三个周五（休市就提前一天），自己算。
不打分、不进任何计算。没取到的源沿用上次的。输出 data/calendar.json。
"""
import html, json, os, re, time
from datetime import date, datetime, timedelta, timezone

from qx import store, clock
from qx.registry import SEMIS, BIGTECH, AI

CAL = os.path.join(store.HERE, "calendar.json")
DAYS = 14
FED_URL = "https://www.federalreserve.gov/json/calendar.json"
EARN_URL = "https://api.nasdaq.com/api/calendar/earnings?date={}"
ECON_URL = "https://api.nasdaq.com/api/calendar/economicevents?date={}"
JSON_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
FED_KEEP = {"FOMC Meeting": ("fomc", "议息会（决议）"), "FOMC Press Conference": ("presser", "主席发布会"),
            "FOMC Minutes": ("minutes", "会议纪要"), "Beige Book": ("beige", "褐皮书")}
NAMES = {"NVDA": "英伟达", "MU": "美光", "TSM": "台积电", "AVGO": "博通", "AMD": "AMD", "ASML": "阿斯麦", "AAPL": "苹果", "MSFT": "微软",
         "GOOGL": "谷歌", "AMZN": "亚马逊", "META": "Meta", "TSLA": "特斯拉", "ORCL": "甲骨文", "CRWV": "CoreWeave", "INTC": "英特尔"}
WATCH = sorted(set(SEMIS) | set(BIGTECH) | {t for v in AI.values() for t in v})
BIG_CAP = 200e9
TIME_N = {"time-pre-market": "盘前", "time-after-hours": "盘后"}
# 宏观：(国家, 事件名的正则, 页面上的名字)。只收会动市场的几样（口径.md 三.8）
ECON = [
    ("United States", r"^CPI$|^Inflation Rate (YoY|MoM)$", "美国 CPI"),
    ("United States", r"^Core (CPI|Inflation Rate)", "美国核心 CPI"),
    ("United States", r"^Non ?Farm Payrolls$", "美国非农就业"),
    ("United States", r"^Unemployment Rate$", "美国失业率"),
    ("United States", r"^Core PCE Price Index", "美国核心 PCE"),
    ("United States", r"^GDP Growth Rate", "美国 GDP"),
    ("United States", r"^Retail Sales MoM$", "美国零售销售"),
    ("United States", r"^ISM (Manufacturing|Services|Non-Manufacturing) PMI$", "美国 ISM"),
    ("Japan", r"BoJ Interest Rate Decision|Interest Rate Decision", "日本央行利率决议"),
    ("South Korea", r"Interest Rate Decision", "韩国央行利率决议"),
]


def fed(txt, start, end):
    j = json.loads(txt.lstrip("﻿"))
    out = []
    for e in j.get("events", []):
        title, typ = (e.get("title") or "").strip(), e.get("type")
        kind = FED_KEEP.get(title)
        chair = typ in ("Speeches", "Testimony") and re.search(r"\bChair(man)?\b", title) and "Vice Chair" not in title
        if not kind and not chair:
            continue
        days = re.findall(r"\d+", e.get("days") or "")
        if not days or not e.get("month"):
            continue
        d = date.fromisoformat(f"{e['month']}-{int(days[-1]):02d}")        # 两天的会取最后一天（决议日）
        if not (start <= d <= end):
            continue
        desc = re.sub(r"<[^>]+>", "", html.unescape(e.get("description") or "")).strip()
        k, nm = kind if kind else ("chair", "主席讲话" if typ == "Speeches" else "主席听证")
        out.append({"date": d.isoformat(), "time": (e.get("time") or "").strip() + " 美东", "kind": k, "title": nm,
                    "note": desc[:80] if k in ("minutes",) else title[:80] if k == "chair" else "", "src": "美联储"})
    return out


def nasdaq_days(get, url, start, end, log):
    """每个工作日取一次纳斯达克的表 → {日期: rows}；返回 (表, 取到几天)。"""
    out, ok = {}, 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            try:
                j = json.loads(get(url.format(d.isoformat()), timeout=30, ua=JSON_UA))
                out[d.isoformat()] = ((j.get("data") or {}).get("rows")) or []
                ok += 1
            except Exception as e:
                log(f"  ! 纳斯达克 {d} 没取到：{str(e)[:80]}")
            time.sleep(0.4)
        d += timedelta(days=1)
    return out, ok


def earnings(tables):
    out = []
    for d, rows in tables.items():
        seen = set()
        for r in sorted(rows, key=lambda r: (r.get("symbol") or "") not in WATCH):
            s = (r.get("symbol") or "").strip()
            try:
                cap = float((r.get("marketCap") or "").replace("$", "").replace(",", ""))
            except ValueError:
                cap = None
            nm = (r.get("name") or s).strip()
            if (s in WATCH or (cap or 0) >= BIG_CAP) and nm not in seen:
                seen.add(nm)
                out.append({"date": d, "time": TIME_N.get(r.get("time"), "时间未定"), "kind": "earnings", "title": "财报", "sym": s,
                            "name": NAMES.get(s) or nm[:24], "cap": cap, "why": "关注" if s in WATCH else "大市值", "src": "纳斯达克"})
    return out


def econ(tables):
    out, seen = [], set()
    for d, rows in tables.items():
        for r in rows:
            c, n = (r.get("country") or "").strip(), (r.get("eventName") or "").strip()
            for cc, rx, nm in ECON:
                if c == cc and re.search(rx, n) and (d, nm) not in seen:
                    seen.add((d, nm))
                    out.append({"date": d, "time": (r.get("gmt") or "").strip(), "kind": "macro", "title": nm, "note": n, "src": "纳斯达克"})
                    break
    return out


def opex(start, end):
    """每月第三个周五；那天休市就提前到周四。"""
    out = []
    m = date(start.year, start.month, 1)
    while m <= end:
        fr = [m + timedelta(days=i) for i in range(31) if (m + timedelta(days=i)).month == m.month and (m + timedelta(days=i)).weekday() == 4]
        d = fr[2]
        while not clock.is_trading_day(d):
            d -= timedelta(days=1)
        if start <= d <= end:
            out.append({"date": d.isoformat(), "time": "收盘", "kind": "opex", "title": "月度期权到期", "note": "个股和指数的月度期权在这天到期", "src": "自己算"})
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


def fetch(log=print, today=None):
    from qx.fetch import get
    today = today or datetime.now(timezone.utc).date()
    start, end = today, today + timedelta(days=DAYS)
    old = load()
    keep_old = lambda kinds: [e for e in old.get("events", []) if e["kind"] in kinds and e["date"] >= start.isoformat()]
    ok = {}
    try:
        fe = fed(get(FED_URL, timeout=30), start, end)
        ok["fed"] = True
    except Exception as e:
        log(f"  ! 美联储日历没取到（沿用上次）：{e}")
        fe, ok["fed"] = keep_old({"fomc", "presser", "minutes", "beige", "chair"}), False
    et, n1 = nasdaq_days(get, EARN_URL, start, end, log)
    ea = earnings(et) if n1 else keep_old({"earnings"})
    mt, n2 = nasdaq_days(get, ECON_URL, start, end, log)
    ma = econ(mt) if n2 else keep_old({"macro"})
    ok.update(earnings=n1, macro=n2)
    ev = sorted(fe + ea + ma + opex(start, end), key=lambda e: (e["date"], e["kind"] != "fomc", e.get("time") or "", e.get("sym") or ""))
    store.write_atomic(CAL, json.dumps({"fetched": datetime.now(timezone.utc).isoformat(timespec="minutes"), "from": start.isoformat(),
                                        "to": end.isoformat(), "events": ev, "ok": ok}, ensure_ascii=False))
    log(f"日历：{start} → {end}，美联储 {len(fe)} 件、财报 {len(ea)} 家、宏观 {len(ma)} 件（纳斯达克财报 {n1} 天、宏观 {n2} 天取到）")
    return ev


def load():
    try:
        with open(CAL, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"fetched": None, "events": []}
