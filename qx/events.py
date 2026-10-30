#!/usr/bin/env python3
"""日历：接下来两周会发生什么（从旧终端 data/events.py 改来，2026-10-23 加了美国宏观数据、日韩央行、月度期权到期）。

三个免费源（2026-10-23 实测能取到）：
  美联储      https://www.federalreserve.gov/json/calendar.json   议息会决议日、发布会、纪要、褐皮书、主席讲话和听证
  纳斯达克财报 https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD      关注公司 + 市值 ≥ 2000 亿美元的公司
  纳斯达克宏观 https://api.nasdaq.com/api/calendar/economicevents?date=YYYY-MM-DD  CPI、非农、PCE、GDP、零售、ISM、日韩央行
  （BLS 自己的日程对程序回 403，所以用纳斯达克的；纳斯达克漏了的非农，用 登记/bls_empsit.toml 里手抄的 BLS 发布日表补，bls_nfp()，只给页面用。）
月度期权到期：每月第三个周五（休市就提前一天），自己算。
不打分、不进任何计算。没取到的源沿用上次的。输出 data/calendar.json。
"""
import html, json, os, re, time, tomllib
from datetime import date, datetime, timedelta, timezone

from qx import store, clock
from qx.registry import SEMIS, BIGTECH, AI

CAL = os.path.join(store.HERE, "calendar.json")
BLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "登记", "bls_empsit.toml")
DAYS = 14
FED_URL = "https://www.federalreserve.gov/json/calendar.json"
EARN_URL = "https://api.nasdaq.com/api/calendar/earnings?date={}"
ECON_URL = "https://api.nasdaq.com/api/calendar/economicevents?date={}"
JSON_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
FED_KEEP = {"FOMC Meeting": ("fomc", "议息会（决议）"), "FOMC Press Conference": ("presser", "主席发布会"),
            "FOMC Minutes": ("minutes", "会议纪要"), "Beige Book": ("beige", "褐皮书")}
NAMES = {"NVDA": "英伟达", "MU": "美光", "TSM": "台积电", "AVGO": "博通", "AMD": "AMD", "ASML": "阿斯麦", "AAPL": "苹果", "MSFT": "微软",
         "GOOGL": "谷歌", "AMZN": "亚马逊", "META": "Meta", "TSLA": "特斯拉", "ORCL": "甲骨文", "CRWV": "CoreWeave", "INTC": "英特尔",
         "LLY": "礼来", "STM": "意法半导体", "ASX": "日月光", "UMC": "联电", "SNDK": "闪迪", "KLAC": "KLA", "LRCX": "泛林", "AMAT": "应用材料",
         "QCOM": "高通", "TXN": "德州仪器", "ADI": "亚德诺", "NXPI": "恩智浦", "ON": "安森美", "MRVL": "迈威尔", "ARM": "Arm", "SMCI": "超微电脑",
         "DELL": "戴尔", "HPE": "慧与", "CSCO": "思科", "IBM": "IBM", "NFLX": "奈飞", "WDC": "西部数据", "STX": "希捷", "TER": "泰瑞达", "ASML": "阿斯麦",
         "JPM": "摩根大通", "V": "Visa", "MA": "万事达", "WMT": "沃尔玛", "COST": "好市多", "XOM": "埃克森美孚", "BRK.B": "伯克希尔", "UNH": "联合健康"}   # 一张名字表：有中文名的用中文（五样方案第五节）
WATCH = sorted(set(SEMIS) | set(BIGTECH) | {t for v in AI.values() for t in v})
BIG_CAP = 200e9
TIME_N = {"time-pre-market": "盘前", "time-after-hours": "盘后"}
# 宏观：(国家, 事件名的正则, 页面上的名字)。只收会动市场的几样（口径.md 三.8）
ECON = [
    ("United States", r"^CPI$|^Inflation Rate (YoY|MoM)$", "美国 CPI"),
    ("United States", r"^Core (CPI|Inflation Rate)", "美国核心 CPI"),
    ("United States", r"(?i)^non ?farm payrolls$", "美国非农就业"),   # 纳斯达克写 Nonfarm Payrolls（10-29 核对，原来大小写对不上一直没认出）
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


def nasdaq_days(get, url, start, end, log, lag=0):
    """每个工作日取一次纳斯达克的表 → {日期: rows}；返回 (表, 取到几天)。
    lag：查的日子比事件晚几天（宏观日历查 q 得到 q 前一天的事件，lag=1），按事件那天是不是工作日挑（新3 改正：原来按查的那天挑，
    周五的事件要查周六，被跳过了，11/6 的非农就这样漏了；口径十四.1 更正）。"""
    out, ok = {}, 0
    d = start
    while d <= end:
        if (d - timedelta(days=lag)).weekday() < 5:
            try:
                j = json.loads(get(url.format(d.isoformat()), timeout=30, ua=JSON_UA))
                out[d.isoformat()] = ((j.get("data") or {}).get("rows")) or []
                ok += 1
            except Exception as e:
                log(f"  ! 纳斯达克 {d} 没取到：{str(e)[:80]}")
            time.sleep(1)                                              # 数据接口每次至少隔 1 秒（口径第八节）
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
                            "name": NAMES.get(s) or nm, "cap": cap, "why": "关注" if s in WATCH else "大市值", "src": "纳斯达克"})
    return out


NASDAQ_TZ = timezone(timedelta(hours=-4))


def econ_rows(rows, q):
    """纳斯达克宏观日历两处口径（2026-10-29 核对，口径三.8 补）：
    查 date=q 返回的是前一天的事件（查 2024-08-03 周六返回 8/2 的非农，查 2026-10-02 返回 10/1 的 ISM）；
    时间一律按 UTC−4 写（夏令时结束以后 ISM 的 10:00 写成 11:00）。返回 [(row, 美东日期, utc 时刻或 None)]。"""
    d = q - timedelta(days=1)
    out = []
    for r in rows:
        m = re.match(r"^(\d{1,2}):(\d{2})$", (r.get("gmt") or "").strip())
        utc = datetime(d.year, d.month, d.day, int(m[1]), int(m[2]), tzinfo=NASDAQ_TZ).astimezone(timezone.utc) if m else None
        out.append((r, utc.astimezone(clock.NY).date() if utc else d, utc))
    return out


def econ(tables):
    out, seen = [], set()
    for q, rows in tables.items():
        for r, d, utc in econ_rows(rows, date.fromisoformat(q)):
            c, n = (r.get("country") or "").strip(), (r.get("eventName") or "").strip()
            for cc, rx, nm in ECON:
                if c == cc and re.search(rx, n):
                    if (d, nm) not in seen:
                        seen.add((d, nm))
                        out.append({"date": d.isoformat(), "time": utc.astimezone(clock.NY).strftime("%H:%M") + " 美东" if utc else "",
                                    "utc": utc.isoformat(timespec="minutes") if utc else None, "kind": "macro", "title": nm, "note": n, "src": "纳斯达克"})
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
    mt, n2 = nasdaq_days(get, ECON_URL, start + timedelta(days=1), end + timedelta(days=1), log, lag=1)   # 查 q 得到 q 前一天的事件
    ma = [e for e in econ(mt) if start.isoformat() <= e["date"] <= end.isoformat()] if n2 else keep_old({"macro"})
    ok.update(earnings=n1, macro=n2)
    ev = sorted(fe + ea + ma + opex(start, end), key=lambda e: (e["date"], e["kind"] != "fomc", e.get("time") or "", e.get("sym") or ""))
    # 议息会加 Polymarket 的"不变 / 降 / 加"概率（只显示；取不到就沿用上次的，标 stale）
    from qx import polymarket, timeline
    # 下一次和下下次议息会都取概率（口径五.1；2026-10-29 补：原来只取 14 天窗口里的那一次）。会期从时间轴的美联储日程来
    nxt = sorted({e["date"] for e in timeline.load().get("events", []) if e.get("kind") == "fomc" and e["date"] >= start.isoformat()})[:2]
    meetings = sorted({e["date"] for e in ev if e["kind"] == "fomc"} | set(nxt))
    pm = polymarket.fetch(meetings, get, log)
    old_pm = {e["date"]: e["pm"] for e in old.get("events", []) if e.get("kind") == "fomc" and e.get("pm")} | (old.get("fomc_pm") or {})
    for e in ev:
        if e["kind"] == "fomc" and (pm.get(e["date"]) or old_pm.get(e["date"])):
            e["pm"] = pm.get(e["date"]) or {**old_pm[e["date"]], "stale": True}
    fomc_pm = {d: pm.get(d) or {**old_pm[d], "stale": True} for d in meetings if pm.get(d) or old_pm.get(d)}
    ok["polymarket"] = bool(pm)
    store.write_atomic(CAL, json.dumps({"fetched": datetime.now(timezone.utc).isoformat(timespec="minutes"), "from": start.isoformat(),
                                        "to": end.isoformat(), "events": ev, "fomc_pm": fomc_pm, "ok": ok}, ensure_ascii=False))
    log(f"日历：{start} → {end}，美联储 {len(fe)} 件、财报 {len(ea)} 家、宏观 {len(ma)} 件（纳斯达克财报 {n1} 天、宏观 {n2} 天取到）")
    return ev


NFP = "美国非农就业"


def bls_table():
    """登记/bls_empsit.toml（手抄的 BLS 发布日表）→ dict(source, dates=[发布日…])；没有这个文件给空表。"""
    try:
        with open(BLS, "rb") as f:
            R = tomllib.load(f)
    except FileNotFoundError:
        return dict(source={}, dates=[])
    return dict(source=R.get("source") or {}, dates=sorted(r["date"] for r in R.get("release") or []))


def nfp_est(y, m):
    """参考月 y-m 的非农大约哪天发（估的，只给 BLS 表管不到的月份用；新3 复查改正，口径十四.1）：
    参考周（参考月里含 12 号的那一周，周日到周六）结束以后的第三个周五；落在 1 月 1–3 日的往后挪一周（年底假期），
    落在 7 月 3、4 日（独立日或它的补假）的提前一天到周四。
    拿 data/macro_raw.csv 里 2010 年以来 201 次非农发布日对过：196 次对得上，对不上的 5 次都是政府停摆推迟的
    （2013-10-22、2013-11-08、2025-11-20、2025-12-16、2026-02-11）；BLS 表里的 14 次全对得上。按"每月第一个周五"是 166 次。"""
    d12 = date(y, m, 12)
    f = d12 + timedelta(days=(5 - d12.weekday()) % 7 + 20)             # 参考周的周六 + 6 天是第一个周五，再 + 14 天是第三个
    if f.month == 1 and f.day <= 3:
        f += timedelta(days=7)
    elif f.month == 7 and f.day in (3, 4):
        f -= timedelta(days=1)
    return f


def bls_nfp(start, end):
    """非农的后备（新3，口径十四.1 更正）：BLS 发布日表里 [start, end] 之间的发布日，换成日历的格式（美东 08:30）。
    表管到的那几个月（第一次到最后一次发布的月份）以外，按参考周估一条（nfp_est()，上个月是参考月），标 est=True：只进"再往后"那一行，
    不进 ④ 的状态词、不算口径三.8 的大事。不按"每月第一个周五"估（2010 年以来 201 次里 35 次不在第一个周五；新3 复查改正，原来就是按它估的）。
    表管到的月份里没有发布的就是没有，不估。不进 load()：推送读的 today.upcoming 不动，页面那几处自己补（qx/front.py nfp_add()）。"""
    start, end = str(start), str(end)
    T = bls_table()
    src = T["source"]
    hm = src.get("time_et") or "08:30"
    note = f"Employment Situation：非农就业和失业率（BLS 发布日表，{src.get('copied', '')} 手抄）"
    url = src.get("url") or ""

    def row(d, est):
        dt = datetime.fromisoformat(f"{d} {hm}").replace(tzinfo=clock.NY).astimezone(timezone.utc)
        if est:                                                        # 估的不是表里抄的：来源写估法（新3 复查改正）
            return {"date": d, "time": hm + " 美东", "utc": dt.isoformat(timespec="minutes"), "kind": "macro", "title": NFP, "est": True,
                    "note": "Employment Situation：BLS 发布日表管不到的月份，按参考周（含 12 号那一周）结束以后的第三个周五估", "src": "估的（按参考周推）", "url": url}
        return {"date": d, "time": hm + " 美东", "utc": dt.isoformat(timespec="minutes"), "kind": "macro", "title": NFP, "note": note,
                "src": "BLS 发布日表", "url": url}

    out = [row(d, False) for d in T["dates"] if start <= d <= end]
    lo, hi = (T["dates"][0][:7], T["dates"][-1][:7]) if T["dates"] else ("9999-99", "0000-00")
    m = date.fromisoformat(start[:8] + "01")
    while m.isoformat() <= end:
        ym = m.isoformat()[:7]
        if not (lo <= ym <= hi):
            fr = nfp_est(m.year - (m.month == 1), (m.month - 2) % 12 + 1)          # 这个月发的是上个月的数
            if start <= fr.isoformat() <= end:
                out.append(row(fr.isoformat(), True))
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return sorted(out, key=lambda e: e["date"])


OFFICIAL = {"gdp": "美国 GDP", "pce": "美国 PCE", "boj": "日本央行利率决议"}


def official(start=None, end=None):
    """时间轴从官方日程取到的 GDP、PCE、日本央行（纳斯达克那份没有或不全），换成日历的格式（2026-10-29 补：48 小时原来漏了这几样）。"""
    from qx import timeline
    out = []
    for e in timeline.load().get("events", []):
        nm = OFFICIAL.get(e.get("kind"))
        if not nm or (start and e["date"] < start) or (end and e["date"] > end):
            continue
        bj, utc, tm = e.get("bj") or "", None, ""
        if len(bj) >= 16:
            t = datetime.fromisoformat(bj[:16]).replace(tzinfo=clock.SH)
            utc = t.astimezone(timezone.utc).isoformat(timespec="minutes")
            tm = t.astimezone(clock.NY).strftime("%H:%M") + " 美东"
        out.append({"date": e["date"], "time": tm, "utc": utc, "kind": "macro", "title": nm, "note": e.get("title", ""), "src": e.get("src", "")})
    return out


def load():
    try:
        with open(CAL, encoding="utf-8") as f:
            cal = json.load(f)
    except Exception:
        cal = {"fetched": None, "events": []}
    ev = cal.get("events", [])
    have = {(e["date"], e["title"]) for e in ev}
    add = [e for e in official(cal.get("from"), cal.get("to")) if (e["date"], e["title"]) not in have]
    if add:
        cal = dict(cal, events=sorted(ev + add, key=lambda e: (e["date"], e["kind"] != "fomc", e.get("time") or "", e.get("sym") or "")))
    return cal
