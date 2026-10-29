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
               盘前发的行取到时下一个交易日常常还没收盘：r0 照写，r1 留空，每天补的时候再补（2026-10-29 复查改正，原来两个都写成 na、再也不补）；
               两周以后还没有的（停牌、退市）写 na，不再每天重取——要连着 5 天没取到（或取到的日线没到那一天）才写，
               一次临时取不到不算（停了几天再跑、头一次补就已经过了两周的行，原来一次失败就写成 na；2026-10-29 第三、四轮核实改正）。
               一天最多算一次；这一次一个代码都没取到、SPY 也取不到的（数据源断了）不算。连着几天记在 data/earn_split_fails.json
               （代码 → 天数、最后算的那天），取到了就清掉；记着的代码排在没记着的后面，不占每天 20 个名额。
日线对着交易日历（2026-10-30 第五轮核实改正）：Yahoo 偶尔整天漏一根日线（2026-10-21 三十多个品种都没有收盘价），
               停牌的也没有那一根；原来按日线里的前后位置算，隔着洞会把两天的涨跌写成一天，写进去以后不会再改。
               现在前一个交易日、反应日（两天合计的再加下一个）要和 qx/clock 的 NYSE 日历一天不差，对不上的不算（等补上，或按没取到走 na）。
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
SPLIT_WAIT, SPLIT_FAILS = 14, 5           # 分开的两天过了 14 天还算不出来、而且连着 5 天都没取到（或日线没到那一天），写 na
FAILS = os.path.join(store.HERE, "earn_split_fails.json")
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


def _tdays(d):
    """公布日 d（YYYY-MM-DD）→ [前一个交易日, 那天或以后第一个交易日, 再下一个交易日]（qx/clock 的 NYSE 日历）。"""
    from qx import clock
    f = date.fromisoformat(d)
    while not clock.is_trading_day(f):
        f += timedelta(days=1)
    p, n = f - timedelta(days=1), f + timedelta(days=1)
    while not clock.is_trading_day(p):
        p -= timedelta(days=1)
    while not clock.is_trading_day(n):
        n += timedelta(days=1)
    return [p.isoformat(), f.isoformat(), n.isoformat()]


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
    k = 1 if tm == "time-after-hours" else 0
    if ds[i - 1: j + 1] != _tdays(d.isoformat())[k: k + j - i + 2]:
        return None                                                  # 中间漏了一根（Yahoo 没给收盘价、停牌）：隔着洞是两天的涨跌，等补上
    lr = np.diff(np.log(c[: i]))                                     # 反应日以前的全部历史
    if len(lr) < MIN_HIST:
        return None
    ret = float(np.log(c[j] / c[i - 1]))
    return ds[j], ret, float(np.std(lr, ddof=1)) * (np.sqrt(2) if two else 1.0)


def _split(rs, d):
    """→ (公布当天的对数涨跌, 下一个交易日的)；公布日按"那天或以后第一个交易日"。
    还没收盘的是 None（下次再补）；永远算不了的（上市第一天，没有前一天收盘）是 "na"。
    日线里那三天和交易日历对不上的（漏了一根、停牌，日线从公布以后才开始）也是 None，按没取到算。"""
    ds = [r[0] for r in rs]
    i = next((k for k, x in enumerate(ds) if x >= d), None)
    p, t0, t1 = _tdays(d)
    if i is None or ds[i] != t0:
        return None, None
    c = [r[1] for r in rs]
    r0 = "na" if i == 0 else float(np.log(c[i] / c[i - 1])) if ds[i - 1] == p else None
    r1 = float(np.log(c[i + 1] / c[i])) if i + 1 < len(ds) and ds[i + 1] == t1 else None
    return r0, r1


def _cell(x):
    return "" if x is None else x if x == "na" else round(x, 6)


def split(log=print, limit=None, sleep=1.0):
    """给 r0、r1 还空着的行补上公布当天、下一个交易日分开的涨跌（每个代码取一次日线；python run.py earn-split）。"""
    rs = rows()
    blank = lambda x: x in ("", None)                 # 0.0 是算出来的数，不是空着
    gap = lambda r: blank(r.get("r0")) or blank(r.get("r1"))
    fails = _load_fails()
    wait = {}
    for r in rs:
        if gap(r):
            wait[r["sym"]] = min(wait.get(r["sym"], r["date"]), r["date"])
    todo = sorted(wait, key=lambda s: (fails.get(s, {}).get("n", 0), wait[s], s))
    # 没记着取不到的先补，再按空着最久的：过了 14 天还空着的，是每次都排在前面、取过很多次的，不是一直轮不上；连着取不到的（退市、换代码）不占着名额
    old = (date.today() - timedelta(days=SPLIT_WAIT)).isoformat()
    today = date.today().isoformat()
    n = k = got = 0
    bad = []                                          # [(代码, 没取到的原因, 过了两周还空着的行)]
    for i, sym in enumerate(todo[:limit], 1):
        why = ""
        try:
            hist = _history(sym.replace(".", "-"))
            if not hist:
                why = "空的"
        except Exception as e:
            hist, why = [], type(e).__name__
        got += bool(hist)
        mine = [r for r in rs if r["sym"] == sym and gap(r)]
        for r in mine:
            new = False
            for c, x in zip(("r0", "r1"), _split(hist, r["date"]) if hist else (None, None)):
                if blank(r.get(c)) and x is not None:
                    r[c] = _cell(x)
                    new |= x != "na"
                    k += x == "na"
            n += new
        left = [r for r in mine if gap(r) and r["date"] < old]  # 过了两周还算不出来的：日线没取到，或者取到了但没到那一天（停牌、退市）
        if hist and not left:
            fails.pop(sym, None)
        elif left or why:
            bad.append((sym, why, left))
        time.sleep(sleep)
        if i % 20 == 0:                               # 每 20 个代码存一次，断了下次接着补
            _save(rs)
    count = got > 0 or bool(bad) and _alive()         # 一个代码都没取到：看 SPY 取不取得到，取不到是数据源断了，这次不算
    for sym, why, left in bad if count else []:
        f = fails.setdefault(sym, {"n": 0, "day": ""})
        if f["day"] != today:                         # 一天最多算一次（手动连跑、云端重跑不会多算）
            f["n"], f["day"] = f["n"] + 1, today
        kk = 0
        if f["n"] >= SPLIT_FAILS:
            for r in left:
                for c in ("r0", "r1"):
                    if blank(r.get(c)):
                        r[c], kk = "na", kk + 1
        k += kk
        log(f"  ! {sym} " + (f"日线没取到：{why}" if why else "日线没到公布后的交易日") + f"（连着 {f['n']} 天；"
            + (f"等了 {SPLIT_WAIT} 天以上的 {kk} 格写 na）" if kk else f"连着 {SPLIT_FAILS} 天、等了 {SPLIT_WAIT} 天以上才写 na，下次再算）"))
    if bad and not count:
        log(f"  ! 财报反应：这次 {len(bad)} 个代码的日线都没取到，SPY 也取不到——数据源断了，不算进连着几天，下次再算")
    _save(rs)
    _save_fails({s: v for s, v in fails.items() if s in {r["sym"] for r in rs if gap(r)}})
    log(f"  财报反应：补了 {n} 行分开的两天" + (f"，{k} 格写 na" if k else "")
        + f"（试了 {len(todo[:limit])} 个代码，还有 {len({r['sym'] for r in rs if gap(r)})} 个代码有空着的）")
    return n


def _alive():
    try:
        return bool(_history("SPY"))
    except Exception:
        return False


def _load_fails():
    try:
        with open(FAILS, encoding="utf-8") as f:
            x = json.load(f)
        return {str(s): {"n": int(v["n"]), "day": str(v.get("day", ""))} for s, v in x.items()}
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return {}                                     # 没有、或者被改坏了：从头数（只会晚写 na，不会早写）


def _save_fails(fails):
    tmp = FAILS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(fails.items())), f, ensure_ascii=False, indent=0)
    os.replace(tmp, FAILS)


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


def _ntd(a, b):
    """a 到 b 以前（不含 b）的交易日数（qx/clock 的 NYSE 日历）。"""
    from qx import clock
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    return sum(clock.is_trading_day(a + timedelta(days=x)) for x in range(max(0, (b - a).days)))


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
        if not hist:                                                  # 取到了但是空的（只有 meta、收盘价全空）：按没取到算（2026-10-30 第七轮核实改正）
            log(f"  ! {sym} 日线是空的（下次再算）")
            continue
        for r in rs:
            if r["sym"] != sym or r.get("basis") in (BASIS, "short"):
                continue
            rr = _react_rows(hist, date.fromisoformat(r["date"]), r.get("time"))
            if rr:
                r.update(react_day=rr[0], ret=round(rr[1], 6), dvol=round(rr[2], 6), seen=rr[0], basis=BASIS)
                n += 1
            elif all(c - (r.get("time") != "time-after-hours") < MIN_HIST for c in (sum(h[0] < r["date"] for h in hist), _ntd(hist[0][0], r["date"]))):
                r["basis"] = "short"                                  # 反应日以前不到 250 天：不进第 4 类卡，也不再重算
                # 日线根数和交易日历都不够才算（第七轮核实改正）：Yahoo 漏了一根的，补上以后够数，不能先标成不够；2025 年以前日历没有假日，数多了只会留着
            # 其余（日线对不上交易日历、反应日还没收盘）留着，下次再算
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
                                "r0": _cell(sp[0]), "r1": _cell(sp[1])})
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
