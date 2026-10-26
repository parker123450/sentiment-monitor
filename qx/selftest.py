"""全局自检：不用未来数据（做法照旧终端 core/selftest.py）。

把原始数据截到过去某天 t（FRED 和 AAII 只留观测日早于 t 的，因为第二天才公布；其余留到 t），用同样的代码重算，
t 那天的每个读数都要和全量计算完全一致（相对误差 1e-9）；转折标签里"t 那天已经知道的"也要一样。
模块忘了按公布滞后对齐，或者用了以后的数据，这里会对不上。

用法：python -m qx.selftest [--n 5]
"""
import argparse, sys
import numpy as np
import pandas as pd

from qx import sentiment as S, watch as W
from qx.registry import SERIES

KEYS = ["stage", "sell", "price", "pos", "credit", "credit_n", "dd", "ddv", "m_sell", "m_price", "m_pos", "m_credit", "regime", "vixmax"]


def cut(D, aaii, t):
    t = pd.Timestamp(t)
    out = {}
    for k, f in D.items():
        late = k in SERIES and SERIES[k]["source"] == "FRED"
        out[k] = f[f.index < t] if late else f[f.index <= t]
    return out, (aaii[aaii.index < t] if aaii is not None else None)


def values_at(R, t):
    v = {k: R[k].get(t, np.nan) for k in KEYS}
    v.update({c: R["F"][c].get(t, np.nan) for c in R["F"].columns})
    v.update({"X." + c: R["X"][c].get(t, np.nan) for c in R["X"].columns})
    return v


def same(a, b):
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def run(D, aaii, R=None, n=5, seed=None, log=print):
    R = R or S.compute_all(D, aaii)
    idx = R["P"].index
    rng = np.random.default_rng(seed)
    pool = idx[(idx >= "2000-01-01") & (idx < idx[-5])]
    days = list(idx[-2:]) + list(pd.DatetimeIndex(rng.choice(pool.values, size=n, replace=False)))
    bad = []
    for t in days:
        Dt, at = cut(D, aaii, t)
        Rt = S.compute_all(Dt, at)
        full, part = values_at(R, t), values_at(Rt, t)
        diff = [k for k in full if not same(full[k], part.get(k, np.nan))]
        tf = [x for x in R["turns"] if x[2] <= t]
        tp = [x for x in Rt["turns"] if x[2] <= t]
        if tf != tp:
            diff.append("转折标签")
        if [x["title"] for x in W.close_items(D, R, t)] != [x["title"] for x in W.close_items(Dt, Rt, t)]:
            diff.append("今天要知道的")
        log(f"  {t.date()}：" + ("一致" if not diff else "不一致 " + "、".join(diff[:8])))
        if diff:
            bad.append((t, diff))
    if not flash_check(rng, log):
        bad.append(("快讯", ["第一次"]))
    return not bad


def flash_check(rng, log=print, n=3):
    """快讯的"第一次"：按"能看到的时间"截到过去某一刻重算，那一刻以前的标记必须和全量一样（第四轮第 1 步）。"""
    from qx import flash
    rows = flash.load_rows()
    if len(rows) < 20:
        return True
    full = flash.firsts(rows)
    ts = sorted({flash.visible(r) for r in rows})
    ok = True
    for t in [ts[-1]] + list(rng.choice(ts[: max(1, len(ts) - 1)], size=min(n, len(ts) - 1), replace=False)):
        part = [r for r in rows if flash.visible(r) <= t]
        a = flash.firsts(part)
        b = {k: v for k, v in full.items() if any(r["route"] == k[0] and r["id"] == k[1] for r in part)}
        same_ = a == b
        ok &= same_
        log(f"  快讯截到 {t[:16]}：" + ("一致" if same_ else f"不一致（{len(set(a.items()) ^ set(b.items()))} 处）"))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    a = ap.parse_args()
    from qx import store
    D, aaii = store.load_all()
    ok = run(D, aaii, n=a.n)
    print("自检通过" if ok else "自检没过")
    sys.exit(0 if ok else 1)
