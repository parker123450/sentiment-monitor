"""宏观数据公布值对预期（第四轮五样方案第六节"宏观意外"；规则在口径十四.10）。

数据：纳斯达克宏观日历（api.nasdaq.com/api/calendar/economicevents?date=，面板已在用的来源和请求头），带公布值、一致预期、前值，2010 年起都有。
      查 q 返回的是 q 前一天的事件，时间按 UTC−4 写（qx/events.py econ_rows 已经处理）。
只存美国名字里有 CPI、PCE、Payrolls、Unemployment Rate、ISM 的行，原样存进 data/macro_raw.csv；怎么认是哪一个、怎么算意外在后面。
回补：python run.py macro-backfill（3 个线程，两次请求开始至少隔 1 秒，约 4,300 次，断了接着取）；每天：update() 重取最近 5 个工作日（公布值当天才有）。
"""
import csv, json, os, re, time
from datetime import date, datetime, timedelta, timezone

from qx import events as EV, store

RAW = os.path.join(store.HERE, "macro_raw.csv")
STATE = os.path.join(store.HERE, "macro_raw_state.json")
COLS = ["date", "time", "name", "actual", "consensus", "previous", "q"]
KEEP = re.compile(r"CPI|PCE|Payrolls|Unemployment Rate|ISM")
START = date(2010, 1, 1)
RECENT = 5


def raw_rows():
    if not os.path.exists(RAW):
        return []
    with open(RAW, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save(rs):
    tmp = RAW + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLS} for r in sorted(rs, key=lambda r: (r["date"], r["time"], r["name"])))
    os.replace(tmp, RAW)


def _clean(x):
    x = (x or "").replace("&nbsp;", " ").strip()
    return x


def _day(get, q):
    """查 q（返回 q 前一天的事件）→ 要存的行。"""
    j = json.loads(get(EV.ECON_URL.format(q.isoformat()), timeout=30, ua=EV.JSON_UA))
    out = []
    for r, d, utc in EV.econ_rows(((j.get("data") or {}).get("rows")) or [], q):
        if (r.get("country") or "").strip() != "United States" or not KEEP.search(r.get("eventName") or ""):
            continue
        out.append({"date": d.isoformat(), "time": utc.astimezone(EV.clock.NY).strftime("%H:%M") if utc else "", "name": _clean(r.get("eventName")),
                    "actual": _clean(r.get("actual")), "consensus": _clean(r.get("consensus")), "previous": _clean(r.get("previous")), "q": q.isoformat()})
    return out


def _put(rs, q, new):
    """q 那一次取到的行换掉以前同一个 q 的（公布值、预期会在公布前后变）。"""
    return [r for r in rs if r.get("q") != q.isoformat()] + new


def _state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


class _Pace:
    """几个线程一起取，但两次请求开始的时间至少隔 1 秒（口径第八节；接口一次要 3–4 秒，顺着取要 5 个多小时）。"""
    def __init__(self, gap=1.0):
        import threading
        self.gap, self.next, self.lock = gap, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        time.sleep(max(0.0, at - now))


def backfill(end=None, log=print, gap=1.0, workers=3, chunk=60):
    from concurrent.futures import ThreadPoolExecutor
    from qx.fetch import get
    st = _state()
    d0 = date.fromisoformat(st["done_to"]) + timedelta(days=1) if st.get("done_to") else START
    end = end or (datetime.now(timezone.utc).date() - timedelta(days=1))
    days = [d0 + timedelta(days=i) for i in range((end - d0).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    rs, miss, pace = raw_rows(), list(st.get("miss") or []), _Pace(gap)

    def one(q):
        pace.wait()
        try:
            return q, _day(get, q)
        except Exception as e:
            return q, e

    with ThreadPoolExecutor(workers) as ex:
        for i in range(0, len(days), chunk):
            part = days[i:i + chunk]
            for q, got in ex.map(one, [d + timedelta(days=1) for d in part]):
                if isinstance(got, Exception):
                    miss.append(q.isoformat())
                    log(f"  ! 纳斯达克宏观 {q} 没取到：{type(got).__name__}（最后再补）")
                else:
                    rs = _put(rs, q, got)
            _save(rs)
            store.write_atomic(STATE, json.dumps({"done_to": part[-1].isoformat(), "miss": miss}))
    left = []
    for qs in miss:
        pace.wait()
        try:
            rs = _put(rs, date.fromisoformat(qs), _day(get, date.fromisoformat(qs)))
        except Exception:
            left.append(qs)
    _save(rs)
    store.write_atomic(STATE, json.dumps({"done_to": end.isoformat(), "miss": left}))
    log(f"  宏观公布值：取了 {len(days)} 天，存 {len(rs)} 行，到 {end}，没取到的 {len(left)} 天")
    return len(days)


def update(log=print, today=None):
    """每天收盘后：重取最近 5 个工作日（公布当天才有公布值）。"""
    from qx.fetch import get
    today = today or datetime.now(timezone.utc).astimezone(EV.clock.NY).date()
    rs, ok = raw_rows(), 0
    d = today
    days = []
    while len(days) < RECENT:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    for d in sorted(days):
        q = d + timedelta(days=1)
        try:
            rs = _put(rs, q, _day(get, q))
            ok += 1
        except Exception as e:
            log(f"  ! 纳斯达克宏观 {q} 没取到：{type(e).__name__}")
        time.sleep(1)
    if ok:
        _save(rs)
    log(f"  宏观公布值：最近 {RECENT} 个工作日取到 {ok} 天")
    return ok


# ---------------------------------------------------------------- 认是哪一个、算意外（口径十四.10）
# (编号, 页面上的名字, 事件名, 单位, 同名有环比和同比两行)
SERIES = [
    ("nfp", "非农", r"^Nonfarm Payrolls$", "万", False),
    ("ur", "失业率", r"^Unemployment Rate$", "%", False),
    ("cpi", "CPI 环比", r"^CPI$", "%", True),
    ("core_cpi", "核心 CPI 环比", r"^Core CPI$", "%", True),
    ("core_pce", "核心 PCE 环比", r"^Core PCE Price Index$", "%", True),
    ("ism_m", "ISM 制造业", r"^ISM Manufacturing PMI$", "", False),
    ("ism_s", "ISM 服务业", r"^ISM (Non-Manufacturing|Services) PMI$", "", False),
]
MIN_N = 24


def num(x):
    x = (x or "").replace(",", "").strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*([KMB%]?)$", x, re.I)
    return float(m[1]) if m else None


def _mom(pair, last, hist):
    """同名两行里哪一行是环比。依次：
    1) 两行的前值分别和上一次的环比、同比比，合起来差得少的那种分法（两种差得一样多——比如上一次环比、同比一样大——往下）；
    2) 过去 11 次的环比加这一次的环比，和这一次的同比最接近的那种分法（有 11 次才用）；
    3) 绝对值小的是环比。
    只有一行的：前值更接近上一次的环比就是环比；还没有上一次的，绝对值 < 1 的是环比。"""
    if len(pair) == 1:
        r = pair[0]
        if last.get("m") is None or last.get("y") is None:
            return r if abs(num(r["actual"])) < 1.0 else None
        p = num(r["previous"])
        return r if p is not None and abs(p - last["m"]) <= abs(p - last["y"]) else None
    a, b = pair[:2]
    na, nb = num(a["actual"]), num(b["actual"])
    pa, pb = num(a["previous"]), num(b["previous"])
    if last.get("m") is not None and last.get("y") is not None and pa is not None and pb is not None:
        ca = abs(pa - last["m"]) + abs(pb - last["y"])
        cb = abs(pb - last["m"]) + abs(pa - last["y"])
        if abs(ca - cb) > 0.05:
            return a if ca < cb else b
    if len(hist) >= 11:
        s = sum(hist[-11:])
        da, db = abs(s + na - nb), abs(s + nb - na)
        if abs(da - db) > 1e-9:
            return a if da < db else b
    return a if abs(na) <= abs(nb) else b


def releases(rows=None):
    """→ {编号: [dict(date, time, actual, consensus, surprise)]}，按日期排；只要有一致预期的那一行（公布时间 04:00 的是月初占位，没有预期）。"""
    rows = raw_rows() if rows is None else rows
    out = {}
    for sid, _, rx, _, two in SERIES:
        rx = re.compile(rx)
        by = {}
        for r in rows:
            if rx.search(r["name"]) and num(r["actual"]) is not None:
                by.setdefault((r["date"], r["time"]), []).append(r)
        last, hist, got = {}, [], []
        for (d, tm), rs in sorted(by.items()):
            if tm == "04:00":
                continue
            r = _mom(rs, last, hist) if two else rs[0]
            if two and r is not None:
                for x in rs[:2]:
                    last["m" if x is r else "y"] = num(x["actual"])
                hist.append(num(r["actual"]))
            if r is None or num(r["consensus"]) is None:
                continue
            a, c = num(r["actual"]), num(r["consensus"])
            got.append(dict(date=d, time=tm, actual=a, consensus=c, surprise=round(a - c, 6)))
        out[sid] = got
    return out


def _fmt(sid, unit, x):
    if unit == "万":
        return f"{x / 10:+.1f} 万"
    return f"{x:.1f}%" if unit == "%" else f"{x:.1f}"


def _gap(unit, s):
    w = "高" if s > 0 else "低"
    if unit == "万":
        return f"{'多' if s > 0 else '少'} {abs(s) / 10:.1f} 万"
    return f"{w} {abs(s):.1f} 个百分点" if unit == "%" else f"{w} {abs(s):.1f}"


def between(tp, t, R=None):
    """(tp, t] 之间公布的（按公布日期，美东）→ 每个公布时刻一行 [dict(key, date, time, title, items)]。
    每一样：公布值、一致预期、差多少；和这一样那天以前全部有预期的公布比（至少 24 次）：同方向、至少这么大的占几成 = (k + 1) ÷ (n + 1)。"""
    R = releases() if R is None else R
    tp, t = str(tp)[:10], str(t)[:10]
    slots = {}
    for sid, nm, _, unit, _ in SERIES:
        xs = R.get(sid) or []
        for i, x in enumerate(xs):
            if not (tp < x["date"] <= t):
                continue
            hist = [y["surprise"] for y in xs[:i] if y["date"] < x["date"]]
            s = x["surprise"]
            txt = f"{nm} {_fmt(sid, unit, x['actual'])}（预期 {_fmt(sid, unit, x['consensus'])}）"
            frac = None
            if abs(s) < 1e-9:
                txt += "，和预期一样"
            else:
                txt += "，" + _gap(unit, s)
                if len(hist) >= MIN_N:
                    k = sum(1 for y in hist if (y > 0) == (s > 0) and abs(y) >= abs(s) - 1e-9)
                    frac = (k + 1) / (len(hist) + 1)
                    txt += f"；{xs[0]['date'][:4]} 年以来 {len(hist)} 次里，同方向这么大的占 {frac * 100:.0f}%"
            slots.setdefault((x["date"], x["time"]), []).append(dict(sid=sid, text=txt, frac=frac, s=s))
    out = []
    for (d, tm), its in sorted(slots.items()):
        out.append(dict(key=f"macro:{d}:{tm}", date=d, time=tm, items=its,
                        title=f"宏观公布 · {int(d[5:7])}/{int(d[8:])} {tm} 美东：" + "；".join(x["text"] for x in its)))
    return out
