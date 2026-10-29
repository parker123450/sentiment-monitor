"""财报反应（第四轮第 4 步第 4 类卡，2026-10-27）。规则在 口径.md 第十二节。

fetch(days)    纳斯达克财报日历（api.nasdaq.com/api/calendar/earnings?date=，面板已在用的来源和请求头）按天取：实际 EPS、一致预期、超预期 %、市值、盘前 / 盘后。
               市值 ≥ 200 亿美元的，再取它自己的日线（Yahoo，1990 年或上市起），算反应日涨跌和长期日波动。存 data/earnings_react.csv。
               能看到的时间：公布当天收盘后（盘后发的到第二天收盘才有反应日）→ seen = 反应日。
反应日：盘前发的是当天；盘后发的是下一个交易日；不知道的（time-not-supplied）取当天和下一天两天合计。
日度波动：反应日以前全部日线的对数涨跌标准差（原则 2，至少 250 天；两天合计的乘 √2）。2026-10-28 以前是"前 504 天"（滚动窗口），
               那时算的行没有 basis 列，不进第 4 类卡；refresh() 按全部历史重算（python run.py earn-refresh）。
当时的市值（cap_then，2026-10-29 补，口径十二）：纳斯达克日历给的市值是取数那天的，回补的季度拿它筛"≥ 200 亿美元"等于用了后来的数据（原则 3）。
               改成 取数时的市值 × 公布前一个交易日收盘 ÷ 取数那天以前最后一个收盘（股本按取数时的算，近似）。入选看 cap_then。
               还剩的偏差：回补时只存了取数那天 ≥ 200 亿的公司，当时够、后来跌出去的没有存下（只会漏，不会多）。
分开的两天（r0、r1，2026-10-29 补，口径十四.9）：纳斯达克的历史日历几乎都不给盘前盘后（2,000 行里 1,986 行是 time-not-supplied），
               两天合计会把"发布前一天大涨、发布后大跌"抵消掉。另存公布当天（r0 = 当天收盘 ÷ 前一天收盘）和下一个交易日（r1）的对数涨跌，
               第 5 类卡按这家公司下一次财报登记的盘前 / 盘后挑一天（python run.py earn-split 给旧行补）。第 4 类照旧用两天合计。
"""
import csv, json, os, time
from datetime import date, datetime, timedelta, timezone

import numpy as np

from qx import store

CSV = os.path.join(store.HERE, "earnings_react.csv")
COLS = ["date", "sym", "name", "time", "eps", "est", "surprise", "cap", "react_day", "ret", "dvol", "seen", "basis", "cap_then", "fetched", "r0", "r1"]
FETCHED_FIRST = "2026-10-27"            # 2026-10-29 以前存下的行都是 10-27、10-28 取的（回补和头两天的实时），取数日按这天算
CAP_MIN = 20e9
BASIS, MIN_HIST = "all", 250              # basis = all：日度波动按反应日以前的全部历史算；至少 250 天（和 qx/sentiment.py 的 MIN_N 一样）
JSON_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _num(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").replace("(", "-").replace(")", ""))
    except (TypeError, ValueError):
        return None


def rows():
    if not os.path.exists(CSV):
        return []
    with open(CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save(rs):
    tmp = CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLS} for r in sorted(rs, key=lambda r: (r["date"], r["sym"])))
    os.replace(tmp, CSV)


def _history(sym):
    """这家公司的日线（Yahoo，1990 年或上市起）→ [[日期, 收盘, …]]。"""
    from qx.fetch import yahoo, rows_from
    return [r for r in rows_from(yahoo(sym)) if r[1]]


def _react_rows(rs, d, tm):
    """→ (反应日, 对数涨跌, 日度波动)；数据不够返回 None。日度波动 = 反应日以前全部日线的对数涨跌标准差（原则 2，不用滚动窗口）。"""
    if not rs:
        return None
    ds = [r[0] for r in rs]
    c = np.array([r[1] for r in rs], float)
    i = next((k for k, x in enumerate(ds) if x >= d.isoformat()), None)
    if i is None or i == 0:
        return None
    if tm == "time-after-hours":
        i += 1
    if i >= len(ds):
        return None                                                  # 反应日还没收盘
    two = tm not in ("time-pre-market", "time-after-hours")
    j = min(i + 1, len(ds) - 1) if two else i
    if two and j == i:
        return None
    lr = np.diff(np.log(c[: i]))                                     # 反应日以前的全部历史
    if len(lr) < MIN_HIST:
        return None
    ret = float(np.log(c[j] / c[i - 1]))
    return ds[j], ret, float(np.std(lr, ddof=1)) * (np.sqrt(2) if two else 1.0)


def _split(rs, d):
    """→ (公布当天的对数涨跌, 下一个交易日的)；公布日按"那天或以后第一个交易日"。数据不够返回 None。"""
    ds = [r[0] for r in rs]
    i = next((k for k, x in enumerate(ds) if x >= d), None)
    if i is None or i == 0 or i + 1 >= len(ds):
        return None
    c = [r[1] for r in rs]
    return float(np.log(c[i] / c[i - 1])), float(np.log(c[i + 1] / c[i]))


def split(log=print, limit=None, sleep=1.0):
    """给还没有 r0、r1 的行补上公布当天、下一个交易日分开的涨跌（每个代码取一次日线；python run.py earn-split）。"""
    rs = rows()
    todo = sorted({r["sym"] for r in rs if not r.get("r0")})
    n = 0
    for i, sym in enumerate(todo[:limit], 1):
        try:
            hist = _history(sym.replace(".", "-"))
        except Exception as e:
            log(f"  ! {sym} 日线没取到：{type(e).__name__}（下次再算）")
            continue
        for r in rs:
            if r["sym"] != sym or r.get("r0"):
                continue
            sp = _split(hist, r["date"])
            r["r0"], r["r1"] = (round(sp[0], 6), round(sp[1], 6)) if sp else ("na", "na")
            n += 1
        time.sleep(sleep)
        if i % 20 == 0:                               # 每 20 个代码存一次，断了下次接着补
            _save(rs)
    _save(rs)
    log(f"  财报反应：补了 {n} 行分开的两天（{len(todo[:limit])} 个代码，还剩 {max(0, len(todo) - len(todo[:limit]))} 个）")
    return n


def _cap_then(rs, d, cap, fetched):
    """公布前一个交易日的市值（近似）= 取数时的市值 × 那天收盘 ÷ 取数那天以前最后一个收盘。数据不够返回 None。"""
    if not rs or not cap:
        return None
    before = [r for r in rs if r[0] < d]
    at = [r for r in rs if r[0] <= fetched]
    if not before or not at or not at[-1][1]:
        return None
    return float(cap) * before[-1][1] / at[-1][1]


def in_sample(r):
    """进第 4 类卡、季度计数和比较样本的行：日度波动按全部历史算，而且公布前的市值 ≥ 200 亿美元（cap_then，原则 3）。"""
    try:
        return r.get("basis") == BASIS and float(r.get("cap_then") or 0) >= CAP_MIN
    except ValueError:
        return False


def recap(log=print, limit=None, sleep=1.0):
    """给还没有 cap_then 的行补上公布前的市值（每个代码取一次日线；python run.py earn-recap）。"""
    rs = rows()
    todo = sorted({r["sym"] for r in rs if not r.get("cap_then")})
    n = 0
    for sym in todo[:limit]:
        try:
            hist = _history(sym.replace(".", "-"))
        except Exception as e:
            log(f"  ! {sym} 日线没取到：{type(e).__name__}（下次再算）")
            continue
        for r in rs:
            if r["sym"] != sym or r.get("cap_then"):
                continue
            ct = _cap_then(hist, r["date"], _num(r.get("cap")), r.get("fetched") or FETCHED_FIRST)
            r["fetched"] = r.get("fetched") or FETCHED_FIRST
            r["cap_then"] = round(ct) if ct else "na"
            n += 1
        time.sleep(sleep)
        if n and n % 200 == 0:
            _save(rs)
    _save(rs)
    log(f"  财报反应：补了 {n} 行的公布前市值（{len(todo[:limit])} 个代码，还剩 {max(0, len(todo) - len(todo[:limit]))} 个）")
    return n


def _react(sym, d, tm):
    return _react_rows(_history(sym), d, tm)


def refresh(log=print, limit=None, sleep=1.0):
    """2026-10-28 以前按"前 504 天"算的行（没有 basis）按全部历史重算日度波动（每个代码取一次日线）。
    另一个进程在往 data/earnings_react.csv 里写的时候不要跑（两边会互相盖掉）。"""
    rs = rows()
    todo = sorted({r["sym"] for r in rs if r.get("basis") not in (BASIS, "short")})
    n = 0
    for sym in todo[:limit]:
        try:
            hist = _history(sym.replace(".", "-"))
        except Exception as e:
            log(f"  ! {sym} 日线没取到：{type(e).__name__}（下次再算）")
            continue
        for r in rs:
            if r["sym"] != sym or r.get("basis") in (BASIS, "short"):
                continue
            rr = _react_rows(hist, date.fromisoformat(r["date"]), r.get("time"))
            if rr:
                r.update(react_day=rr[0], ret=round(rr[1], 6), dvol=round(rr[2], 6), seen=rr[0], basis=BASIS)
                n += 1
            else:
                r["basis"] = "short"                                  # 反应日以前不到 250 天：不进第 4 类卡，也不再重算
        time.sleep(sleep)
    _save(rs)
    log(f"  财报反应：按全部历史重算了 {n} 行（{len(todo[:limit])} 个代码，还剩 {max(0, len(todo) - len(todo[:limit]))} 个）")
    return n


def fetch(start, end=None, log=print, sleep=1.0):
    from qx.fetch import get
    end = end or (datetime.now(timezone.utc).date() - timedelta(days=1))
    have = {(r["date"], r["sym"]) for r in rows()}
    out = rows()
    d, n = start, 0
    while d <= end:
        if d.weekday() < 5:
            try:
                j = json.loads(get(f"https://api.nasdaq.com/api/calendar/earnings?date={d.isoformat()}", timeout=30, ua=JSON_UA))
                for x in ((j.get("data") or {}).get("rows") or []):
                    cap = _num(x.get("marketCap"))
                    sym = (x.get("symbol") or "").strip()
                    if not sym or not cap or cap < CAP_MIN or (d.isoformat(), sym) in have:
                        continue
                    eps, est = _num(x.get("eps")), _num(x.get("epsForecast"))
                    if eps is None:
                        continue
                    try:
                        hist = _history(sym.replace(".", "-"))
                        rr = _react_rows(hist, d, x.get("time"))
                    except Exception:
                        hist, rr = [], None
                    if not rr:
                        continue
                    today = datetime.now(timezone.utc).date().isoformat()
                    ct = _cap_then(hist, d.isoformat(), cap, today)
                    sp = _split(hist, d.isoformat())
                    out.append({"date": d.isoformat(), "sym": sym, "name": (x.get("name") or "")[:60], "time": x.get("time", ""), "eps": eps, "est": "" if est is None else est,
                                "surprise": _num(x.get("surprise")) if _num(x.get("surprise")) is not None else "", "cap": cap, "react_day": rr[0],
                                "ret": round(rr[1], 6), "dvol": round(rr[2], 6), "seen": rr[0], "basis": BASIS,
                                "cap_then": round(ct) if ct else "na", "fetched": today,
                                "r0": round(sp[0], 6) if sp else "na", "r1": round(sp[1], 6) if sp else "na"})
                    have.add((d.isoformat(), sym))
                    n += 1
                    time.sleep(sleep)
            except Exception as e:
                log(f"  ! 财报日历 {d}：{type(e).__name__}")
            _save(out)                                       # 每天存一次：中途断了不丢
            time.sleep(sleep)
        d += timedelta(days=1)
    _save(out)
    log(f"  财报反应：新 {n} 家（共 {len(out)}）")
    return n
