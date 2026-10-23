"""数据层 · 读写（所有模块只通过 load() 读数据）

data/raw/<文件名>.csv：date,close,volume,open,high,low,adjclose（value 类序列只有 date,value）。
data/meta.json：每个序列的来源、抓取时间、最后日期、状态（ok / cached / missing）和校验提示。
"""
import csv, json, os
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from qx.registry import SERIES

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")   # 面板/data
RAW = os.path.join(HERE, "raw")
META = os.path.join(HERE, "meta.json")
OHLCV_COLS = ["date", "close", "volume", "open", "high", "low", "adjclose"]


def path(name):
    return os.path.join(RAW, SERIES[name]["file"])


def write_atomic(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)       # 云端第一次跑时 data/raw 还没有
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, p)


def read_rows(name):
    """原始行（下载兜底和合并用）：ohlcv → [d, c, v, o, h, l, a]；value → [d, x]。"""
    p = path(name)
    if not os.path.exists(p):
        return []
    out = {}
    fl = lambda x: float(x) if x not in (None, "") else None
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = r.get("date") or ""
            if len(d) != 10:
                continue
            try:
                if SERIES[name]["kind"] == "value":
                    out[d] = [d, float(r["value"])]
                else:
                    c = float(r["close"])
                    out[d] = [d, c, fl(r.get("volume")) or 0.0, fl(r.get("open")), fl(r.get("high")), fl(r.get("low")), fl(r.get("adjclose")) or c]
            except (TypeError, ValueError, KeyError):
                continue
    return [out[k] for k in sorted(out)]


def write_rows(name, rows):
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    if SERIES[name]["kind"] == "value":
        w.writerow(["date", "value"])
        for r in rows:
            w.writerow([r[0], r[1]])
    else:
        w.writerow(OHLCV_COLS)
        for r in rows:
            w.writerow([r[0]] + ["" if x is None else x for x in r[1:7]])
    write_atomic(path(name), buf.getvalue())


def frame(name, rows=None):
    """一个序列的 DataFrame：c 收盘（或值）、a 含分红收盘、v 成交量、o h l。日期升序、去重、去掉坏值。"""
    rows = read_rows(name) if rows is None else rows
    if not rows:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime([r[0] for r in rows]))
    if SERIES[name]["kind"] == "value":
        x = np.array([r[1] for r in rows], float)
        f = pd.DataFrame({"c": x, "a": x, "v": 0.0, "o": np.nan, "h": np.nan, "l": np.nan}, index=idx)
        ok = np.isfinite(f.c) & ((f.c >= 0) if SERIES[name]["zero"] else (f.c > 0) if SERIES[name]["unit"] != "%" else True)
    else:
        arr = lambda k: np.array([np.nan if r[k] is None else r[k] for r in rows], float)
        c, a = arr(1), arr(6)
        f = pd.DataFrame({"c": c, "a": np.where(np.isfinite(a), a, c), "v": np.nan_to_num(arr(2)), "o": arr(3), "h": arr(4), "l": arr(5)}, index=idx)
        ok = np.isfinite(f.c) & (f.c > 0)
    f = f[ok]
    f = f[~f.index.duplicated(keep="last")].sort_index()
    return f if len(f) else None


def load(names=None, until=None):
    """读登记过的序列：{名字: DataFrame}。until：只要这天及以前的观测（收盘后算、自检截断都用它）。"""
    out = {}
    t = pd.Timestamp(until) if until is not None else None
    for k in (names or SERIES):
        f = frame(k)
        if f is None:
            continue
        if t is not None:
            f = f[f.index <= t]
        if len(f):
            out[k] = f
    return out


def cut(D, t):
    """截到"那天收盘时已经知道的"为止（自检用）：每个序列只留观测日 ≤ t − 公布滞后 的值。
    只按观测日截断的话，一个模块忘了按滞后对齐（直接用当天还没公布的 Baa），截断和全量会一样，自检抓不到。"""
    t = pd.Timestamp(t)
    out = {}
    for k, v in D.items():
        lag = SERIES[k]["lag"] if k in SERIES else 0
        out[k] = v[v.index <= (t - pd.offsets.BDay(lag) if lag else t)]
    return out


def read_meta():
    try:
        with open(META, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_meta(m):
    write_atomic(META, json.dumps(m, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 校验（下载后和每天构建时都跑）
def validate(name, rows, old_rows=None):
    """返回提示列表（空 = 通过）。不改数据，只提示；严重的（变短太多、日期乱）由调用方决定是否沿用旧数据。"""
    s = SERIES[name]
    warn = []
    if not rows:
        return ["没有数据"]
    ds = [r[0] for r in rows]
    if ds != sorted(ds) or len(set(ds)) != len(ds):
        warn.append("日期没有排好或有重复")
    if old_rows and len(rows) < 0.9 * len(old_rows):
        warn.append(f"比存下的短很多（{len(rows)} < {len(old_rows)}）")
    if s["kind"] == "ohlcv":
        c = np.array([r[1] for r in rows], float)
        lr = np.abs(np.diff(np.log(c[c > 0])))
        big = int((lr > 0.5).sum())
        if big and s["group"] not in ("期权", "联动"):
            warn.append(f"有 {big} 天单日涨跌超过 65%（可能是拆股没复权）")
    return warn


def expected_last(lag, asof):
    """按公布滞后，截至 asof（最近收盘的交易日）这个序列最晚应该有哪天的观测（周末顺延，不认节假日）。"""
    d = pd.Timestamp(asof) - pd.offsets.BDay(lag)
    return d.strftime("%Y-%m-%d")


def health(D, asof, meta=None):
    """每个序列：最后日期、是否落后（按滞后算，周度序列放宽 7 天）、抓取状态。"""
    meta = meta or read_meta()
    out = {}
    for k, s in SERIES.items():
        m = meta.get(k, {})
        last = D[k].index[-1].strftime("%Y-%m-%d") if k in D else None
        exp = expected_last(s["lag"], asof)
        slack = 9 if k in ("WALCL", "WTREGEN") else 4          # 周度序列一周一个点；日度序列容忍长周末和节假日
        stale = last is None or (pd.Timestamp(exp) - pd.Timestamp(last)).days > slack
        out[k] = {"last": last, "expect": exp, "stale": bool(stale), "status": m.get("status", "local"),
                  "fetched": m.get("fetched"), "warn": m.get("warn", []), "hourly": m.get("hourly", []), "source": s["source"], "lag": s["lag"], "unit": s["unit"]}
    return out


def load_aaii():
    """AAII 历史（data/private/aaii.csv，云端加密存放）→ DataFrame(index=日期, bull, neutral, bear)；没有就 None。"""
    p = os.path.join(HERE, "private", "aaii.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()


def load_all():
    return load(), load_aaii()
