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
        if t >= pd.Timestamp("2010-01-01"):                  # 市场在交易什么（第四轮第 2 步）：篮子的成员多数 2010 年以后才有
            from qx import narrative as NR
            a, b = NR.values(NR.compute(D, t)), NR.values(NR.compute(Dt, t))
            eq = lambda x, y: x == y if isinstance(x, str) or isinstance(y, str) else same(x, y)
            diff += ["在交易什么 " + k for k in a if not eq(a[k], b.get(k, np.nan))]
        if t >= pd.Timestamp("2024-01-01"):                  # 小信号和仓位（第四轮第 3 步）：ICE 利差 FRED 只给最近 3 年
            from qx import smallsignal as SS, positioning as PS
            pa, pb = PS.compute(D, t), PS.compute(Dt, t)
            sa, sb = SS.compute(D, t, pa), SS.compute(Dt, t, pb)
            from qx import radar as RA                        # 机会和风险卡（第四轮第 4 步）
            a = {**PS.values(pa), **SS.values(sa), **{"卡:" + k: v for k, v in RA.values(RA.compute(D, t, pa, sa)).items()}}
            b = {**PS.values(pb), **SS.values(sb), **{"卡:" + k: v for k, v in RA.values(RA.compute(Dt, t, pb, sb)).items()}}
            diff += ["小信号/仓位 " + k for k in set(a) | set(b) if not eq(a.get(k, np.nan), b.get(k, np.nan))]
        log(f"  {t.date()}：" + ("一致" if not diff else "不一致 " + "、".join(diff[:8])))
        if diff:
            bad.append((t, diff))
    if not flash_check(rng, log):
        bad.append(("快讯", ["第一次"]))
    if not parity_check(log):
        bad.append(("和 Worker 对拍", ["打标签、第一次或推送规则"]))
    return not bad


def parity_check(log=print):
    """和 Worker 对拍（第四轮第 1 步）：Worker 的测试（cd worker && npm test）读同一组样例，两边的结果都要等于样例里写的。
    parity.json：按样例自己带的词表打标签、标"第一次"（不依赖现在的 登记/entities.toml，改词表不会让自检失败）；
    push_cases.json：推送总规则（qx/notify.py 的 gate、digest，只判断，不发）。"""
    import json, os
    from datetime import datetime
    from qx import flash, notify
    fx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker", "test", "fixtures")
    ok = True
    P = json.load(open(os.path.join(fx, "parity.json"), encoding="utf-8"))
    E = [(x["id"], flash._alias_re(x["alias"])) for x in P["rules"]["entities"]]
    L = [(x["id"], flash._kw_re(x["kw"])) for x in P["rules"]["lines"]]
    good = all([i for i, rx in E if rx.search(c["t"])] == c["ents"] and [i for i, rx in L if rx.search(c["t"])] == c["lines"] for c in P["cases"])
    if P["rules"]["white"] == sorted(flash.WHITE) and P["rules"]["first_days"] == flash.FIRST_DAYS:
        good &= {k[1]: v for k, v in flash.firsts([dict(r) for r in P["rows"]]).items()} == P["firsts"]
    ok &= good
    log("  和 Worker 对拍（打标签、第一次）：" + ("一致" if good else "不一致"))
    C = json.load(open(os.path.join(fx, "push_cases.json"), encoding="utf-8"))
    if C["rules"] != {"day_cap": notify.DAY_CAP, "day_start_bj": notify.DAY_START_H, "repeat_h": notify.REPEAT_H}:
        log("  和 Worker 对拍（推送规则）：样例的上限和现在的不一样，要重新写 push_cases.json")
        return False
    st, good = {}, True
    for s in C["steps"]:
        now = datetime.fromisoformat(s["at"].replace("Z", "+00:00"))
        dg = notify.digest(st, now)
        out, n_held = notify.gate(st, [dict(m) for m in s["msgs"]], now)
        good &= [m["key"] for m in out] == s["send"] and ("held" not in s or n_held == s["held"]) \
            and ("digest" not in s or [{"title": m["title"], "body": m["body"]} for m in dg] == s["digest"])
    ok &= good
    log(f"  和 Worker 对拍（推送规则 {len(C['steps'])} 步）：" + ("一致" if good else "不一致"))
    return ok


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
