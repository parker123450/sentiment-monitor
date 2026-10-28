"""财报反应（第四轮第 4 步第 4 类卡，2026-10-27）。规则在 口径.md 第十二节。

fetch(days)    纳斯达克财报日历（api.nasdaq.com/api/calendar/earnings?date=，面板已在用的来源和请求头）按天取：实际 EPS、一致预期、超预期 %、市值、盘前 / 盘后。
               市值 ≥ 200 亿美元的，再取它自己的日线（Yahoo，1990 年或上市起），算反应日涨跌和长期日波动。存 data/earnings_react.csv。
               能看到的时间：公布当天收盘后（盘后发的到第二天收盘才有反应日）→ seen = 反应日。
反应日：盘前发的是当天；盘后发的是下一个交易日；不知道的（time-not-supplied）取当天和下一天两天合计。
日度波动：反应日以前全部日线的对数涨跌标准差（原则 2，至少 250 天；两天合计的乘 √2）。2026-10-28 以前是"前 504 天"（滚动窗口），
               那时算的行没有 basis 列，不进第 4 类卡；refresh() 按全部历史重算（python run.py earn-refresh）。
"""
import csv, json, os, time
from datetime import date, datetime, timedelta, timezone

import numpy as np

from qx import store

CSV = os.path.join(store.HERE, "earnings_react.csv")
COLS = ["date", "sym", "name", "time", "eps", "est", "surprise", "cap", "react_day", "ret", "dvol", "seen", "basis"]
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
                        rr = _react(sym.replace(".", "-"), d, x.get("time"))
                    except Exception:
                        rr = None
                    if not rr:
                        continue
                    out.append({"date": d.isoformat(), "sym": sym, "name": (x.get("name") or "")[:60], "time": x.get("time", ""), "eps": eps, "est": "" if est is None else est,
                                "surprise": _num(x.get("surprise")) if _num(x.get("surprise")) is not None else "", "cap": cap, "react_day": rr[0],
                                "ret": round(rr[1], 6), "dvol": round(rr[2], 6), "seen": rr[0], "basis": BASIS})
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
