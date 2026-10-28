"""前瞻的时间轴（第四轮第 5 步，2026-10-27）。规则在 口径.md 第十三节。

未来 6 个月已知的事件，每条带来源链接和北京时间；排不到的列进"缺"，不猜。每周取一次，存 data/timeline.json。
  议息会：美联储日程页（federalreserve.gov/monetarypolicy/fomccalendars.htm，含明年的；决议日 = 两天会的第二天，美东 14:00）
  日本央行会议：日本央行日程页（boj.or.jp，含明年的；决议日 = 第二天，时间不固定只写日期）
  PCE、GDP：美国经济分析局日程（bea.gov/news/schedule，通常只排到两三个月后；美东 8:30）
  CPI、非农、韩国央行：纳斯达克宏观日历（面板原有来源，只排到约 1 个月后）。劳工统计局网站对程序回 403，不绕。
  月度期权到期：每月第三个周五（遇美股休市提前一天），用 exchange_calendars 算
  财报：观察名单的公司，纳斯达克财报日历（只有已经公布日期的，约 1 个月内）
  手动登记的（选举、上市、融资事件）：登记/timeline.toml
"""
import html, json, os, re, tomllib
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from qx import store, events as EV

OUT = os.path.join(store.HERE, "timeline.json")
REG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "登记", "timeline.toml")
UA_NAMED = {"User-Agent": "qx-radar/1.0 (+https://github.com/parker123450/sentiment-monitor)"}
FED_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BOJ_PAGE = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
BEA_PAGE = "https://www.bea.gov/news/schedule"
MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}
MON3 = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "June": 6, "Jun": 6, "July": 7, "Jul": 7, "Aug": 8, "Sept": 9, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
NY = "America/New_York"
HORIZON = 183
SKIP = {"日本央行利率决议", "美国核心 PCE", "美国 GDP"}          # 官方日程页已经有的，纳斯达克那份不再收


def _bj(d, hm, tz=NY):
    """当地时间 → 北京时间的字符串。"""
    t = pd.Timestamp(f"{d} {hm}", tz=tz).tz_convert("Asia/Shanghai")
    return t.strftime("%Y-%m-%d %H:%M")


def _text(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "|", h)))


def fed(get):
    t = get(FED_PAGE, timeout=60, ua=UA_NAMED)
    out = []
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"(\d{4}) FOMC Meetings", t)]
    for i, (pos, yr) in enumerate(heads):
        end = min([p for p, _ in heads if p > pos] or [len(t)])
        blk = t[pos:end]
        for m in re.finditer(r'fomc-meeting__month[^>]*>(?:<strong>)?([A-Za-z/]+)(?:</strong>)?</div>\s*<div class="fomc-meeting__date[^>]*>([^<]+)<', blk):
            mon, days = m.group(1).split("/")[-1], m.group(2)
            if "notation" in days or mon not in MONTHS:
                continue
            nums = re.findall(r"\d+", days)
            if not nums:
                continue
            first_m = MONTHS[m.group(1).split("/")[0]] if m.group(1).split("/")[0] in MONTHS else MONTHS[mon]
            d = date(yr, MONTHS[mon] if len(nums) > 1 and first_m != MONTHS[mon] else first_m, int(nums[-1]))
            out.append(dict(date=d.isoformat(), bj=_bj(d, "14:00"), kind="fomc", title="美联储议息会决议" + ("（附经济预测）" if "*" in days else ""), src="美联储", url=FED_PAGE))
    return out


def boj(get):
    t = _text(get(BOJ_PAGE, timeout=60, ua=UA_NAMED))
    out = []
    for m in re.finditer(r"Table : (\d{4})(.*?)(?=Table : \d{4}|Note:|$)", t):
        yr, blk = int(m.group(1)), m.group(2)
        for x in re.finditer(r"(Jan|Feb|Mar|Apr|May|June|July|Aug|Sept|Oct|Nov|Dec)\.? (\d{1,2}) \([A-Za-z.]+\), (\d{1,2}) \([A-Za-z.]+\)(, (\d{4}))?", blk):
            y = int(x.group(5)) if x.group(5) else yr
            mon = MON3[x.group(1)]
            d1, d2 = int(x.group(2)), int(x.group(3))
            d = date(y, mon + (1 if d2 < d1 else 0), d2) if not (mon == 12 and d2 < d1) else date(y + 1, 1, d2)
            out.append(dict(date=d.isoformat(), bj=d.isoformat(), kind="boj", title="日本央行议息会决议", src="日本央行", url=BOJ_PAGE))
    return list({e["date"]: e for e in out}.values())


def bea(get, today):
    s = _text(get(BEA_PAGE, timeout=60, ua=UA_NAMED))
    out = []
    for m in re.finditer(r"\|([A-Z][a-z]+) (\d{1,2})\|[| ]*(\d{1,2}:\d{2} [AP]M)[| ]*(?:N[| ]*ews[| ]*)?([^|]{5,90})", s):
        title = m.group(4).strip()
        if not re.match(r"Personal Income and Outlays|GDP \(", title) or m.group(1) not in MONTHS:
            continue
        mon = MONTHS[m.group(1)]
        y = today.year + (1 if mon < today.month - 2 else 0)
        d = date(y, mon, int(m.group(2)))
        hm = datetime.strptime(m.group(3), "%I:%M %p").strftime("%H:%M")
        nm = "美国 PCE（个人收入和支出）" if title.startswith("Personal") else "美国 GDP"
        out.append(dict(date=d.isoformat(), bj=_bj(d, hm), kind="pce" if title.startswith("Personal") else "gdp", title=nm + "：" + title, src="美国经济分析局", url=BEA_PAGE))
    return out


def opex(today, months=6):
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS")
    out = []
    for k in range(months + 1):
        y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
        d = date(y, m, 15)
        while d.weekday() != 4:
            d += timedelta(days=1)
        try:
            while not cal.is_session(pd.Timestamp(d)):
                d -= timedelta(days=1)
        except Exception:
            pass
        if d >= today:
            out.append(dict(date=d.isoformat(), bj=_bj(d, "16:00"), kind="opex", title="美股月度期权到期", src="交易所日历（第三个周五）", url="https://www.cboe.com/"))
    return out


def nasdaq(get, today, days=35):
    """纳斯达克宏观日历（CPI、非农、韩国央行等，面板原有的口径）和观察名单的财报。"""
    from qx import coverage as C
    watch = set(EV.WATCH) | {s for s in C.CORE if "." not in s and "=" not in s and "^" not in s and "-" not in s}
    out, last_macro = [], today
    for i in range(days):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            j = json.loads(get(EV.ECON_URL.format(d.isoformat()), timeout=30, ua=EV.JSON_UA))
            for r in ((j.get("data") or {}).get("rows") or []):
                for country, rx, nm in EV.ECON:
                    if nm in SKIP:
                        continue
                    if r.get("country") == country and re.search(rx, r.get("eventName") or ""):
                        # 纳斯达克的时间字段口径不清（10-27 核对过对不上），美国的按惯例写美东时间，日韩央行只写日期
                        bj = _bj(d, "10:00" if "ISM" in nm else "08:30") if country == "United States" else d.isoformat()
                        out.append(dict(date=d.isoformat(), bj=bj, kind="macro", title=nm, src="纳斯达克宏观日历", url=EV.ECON_URL.format(d.isoformat())))
                        last_macro = d
                        break
        except Exception:
            pass
        try:
            j = json.loads(get(EV.EARN_URL.format(d.isoformat()), timeout=30, ua=EV.JSON_UA))
            for r in ((j.get("data") or {}).get("rows") or []):
                if r.get("symbol") in watch:
                    out.append(dict(date=d.isoformat(), bj=d.isoformat() + {"time-pre-market": " 盘前", "time-after-hours": " 盘后"}.get(r.get("time"), ""),
                                    kind="earnings", title=f"{r.get('name') or r['symbol']} 财报", sym=r["symbol"], src="纳斯达克财报日历", url=EV.EARN_URL.format(d.isoformat())))
        except Exception:
            pass
    return out, last_macro


def manual():
    if not os.path.exists(REG):
        return []
    with open(REG, "rb") as f:
        R = tomllib.load(f)
    return [dict(e, kind=e.get("kind", "manual"), bj=e.get("bj", e["date"])) for e in R.get("event", [])]


def build(log=print, today=None):
    from qx.fetch import get
    today = today or datetime.now(timezone.utc).date()
    end = today + timedelta(days=HORIZON)
    ev, missing = [], []
    for nm, f in (("美联储议息会", lambda: fed(get)), ("日本央行会议", lambda: boj(get)), ("PCE 和 GDP", lambda: bea(get, today)), ("期权到期", lambda: opex(today))):
        try:
            xs = f()
            ev += xs
            last = max((x["date"] for x in xs), default=None)
            if not last or last < end.isoformat():
                missing.append(f"{nm}：只排到 {last or '—'}")
        except Exception as e:
            missing.append(f"{nm}：没取到（{type(e).__name__}）")
    xs, last_macro = nasdaq(get, today)
    ev += xs
    missing.append(f"美国 CPI、非农、韩国央行：只排到 {last_macro}（纳斯达克日历只给约 1 个月；劳工统计局网站对程序回 403，不绕）")
    missing.append("观察名单的财报：只有已经公布日期的（约 1 个月内）")
    ev += manual()
    ev = sorted({(e["date"], e["kind"], e["title"]): e for e in ev if today.isoformat() <= e["date"] <= end.isoformat()}.values(), key=lambda e: (e["date"], e.get("bj", "")))
    res = dict(built=datetime.now(timezone.utc).isoformat(timespec="minutes"), start=today.isoformat(), end=end.isoformat(), events=ev, missing=missing)
    store.write_atomic(OUT, json.dumps(res, ensure_ascii=False))
    log(f"  时间轴：{len(ev)} 件，到 {end}；缺 {len(missing)} 项")
    return res


def load():
    try:
        return json.load(open(OUT, encoding="utf-8"))
    except Exception:
        return {"events": [], "missing": ["时间轴还没生成"]}
