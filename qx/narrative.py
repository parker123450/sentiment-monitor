"""市场在交易什么（第四轮第 2 步，2026-10-27）。规则在 口径.md 第十节，篮子和结束信号登记在 登记/narratives.toml。

compute(D, t)   截至 t 收盘：每个篮子的 20 日涨跌（按成员各自的长期波动折算后取中位数）、和对照指数同不同向、配对读数的 20 日变化在自己历史里的位置；
                主线 = 领跌的篮子 且 配对读数偏高以上（两样都满足）。只用 t 以前的数据（FRED 按"次一个观测日才可用"），自检核对。
heat(t)         主题热度：白名单要闻按主题计数，5 日条数 ÷（60 日日均 × 5）。60 日窗口和原则 2 冲突，只作描述，不进任何规则；谷歌新闻到 100 条封顶的日子不算。
block(D)        页面三行：在交易什么、哪个篮子在带着跌、主题热度。数字在这里算好，页面只画。
"""
import json, os, tomllib

import numpy as np
import pandas as pd

from qx import store
from qx.registry import SERIES
from qx.sentiment import longvol

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "登记", "narratives.toml")
N20, MIN_DAYS = 20, 252
BP_PRICE = {"^TNX"}                                   # 收益率指数：变化按基点


def registry(day=None):
    with open(REG, "rb") as f:
        R = tomllib.load(f)
    ok = lambda x: (not day or x.get("since", R["since"]) <= day) and (not x.get("until") or not day or day < x["until"])
    return dict(R, basket=[b for b in R.get("basket", []) if ok(b)], control=[c for c in R.get("control", []) if ok(c)])


def registry_at(t):
    """t 那天在用的登记版本（since ≤ t、还没到 until）。登记以前的日子（回放）用第一版：不拿后来加的版本去算过去。"""
    first = registry()["since"]
    return registry(max(pd.Timestamp(t).strftime("%Y-%m-%d"), first))


def _series(D, k, t):
    """收盘价序列截到 t（FRED 只要 t 以前的观测：第二天才公布）。HYG/IEF 这类写法是两个序列相除。"""
    if "/" in k:
        a, b = (_series(D, x, t) for x in k.split("/"))
        if a is None or b is None:
            return None
        s = (a / b.reindex(a.index)).dropna()
        return s if len(s) > MIN_DAYS else None
    if k not in D:
        return None
    s = D[k]["c"].dropna()
    late = k in SERIES and SERIES[k]["source"] == "FRED"
    s = s[s.index < t] if late else s[s.index <= t]
    return s if len(s) > MIN_DAYS else None


def _name(k):
    """页面上写名字，不写 Yahoo 的代码（GC=F、^KS11 这种）；美股个股的代码交易员认得，没有中文名的照写代码。"""
    from qx import coverage as C
    return C.NAME.get(k, k)


def _z20(D, k, t):
    """20 日对数涨跌 ÷（长期日波动 × √20）。"""
    s = _series(D, k, t)
    if s is None or (s <= 0).any():
        return None
    lv = longvol(s).iloc[-1] / np.sqrt(252)
    if not np.isfinite(lv) or lv <= 0:
        return None
    return float(np.log(s.iloc[-1] / s.iloc[-1 - N20]) / (lv * np.sqrt(N20)))


def _pair(D, p, t):
    """配对读数：20 日变化，和当天以前全部历史里的 20 日变化比（同方向更极端的占几成）。"""
    s = _series(D, p["id"], t)
    if s is None:
        return None
    fred = p["id"] in SERIES and SERIES[p["id"]]["source"] == "FRED"
    ch = (s - s.shift(N20)) * 100 if (fred or p["id"] in BP_PRICE) else np.log(s / s.shift(N20))
    ch = ch.dropna()
    if len(ch) < MIN_DAYS:
        return None
    today, hist = float(ch.iloc[-1]), ch.iloc[:-1]
    stress = today if p.get("up_is_stress", True) else -today
    h = hist if p.get("up_is_stress", True) else -hist
    frac = float((h >= stress).mean())
    return dict(name=p["name"], id=p["id"], chg=round(today, 4), bp=fred or p["id"] in BP_PRICE, frac=round(frac, 4), asof=s.index[-1].strftime("%Y-%m-%d"))


def _level(frac, R):
    return "少见" if frac <= R["rare_pct"] else "偏高" if frac <= R["high_pct"] else "平常"


def compute(D, t):
    t = pd.Timestamp(t)
    R = registry_at(t)
    out = []
    for b in R["basket"] + [dict(c, control_group=True) for c in R["control"]]:
        zs = {m: _z20(D, m, t) for m in b["members"]}
        zs = {m: z for m, z in zs.items() if z is not None}
        if not zs:
            continue
        z = float(np.median(list(zs.values())))
        ref = _z20(D, b["vs"], t) if b.get("vs") else None
        pairs = [x for x in (_pair(D, p, t) for p in b.get("pair", [])) if x]
        for x in pairs:
            x["level"] = _level(x["frac"], R)
        out.append(dict(id=b["id"], name=b["name"], z=round(z, 3), n=len(zs), of=len(b["members"]), members={m: round(v, 2) for m, v in zs.items()},
                        names={m: _name(m) for m in zs},
                        vs=b.get("vs"), ref=None if ref is None else round(ref, 3), same=None if ref is None else bool(np.sign(ref) == np.sign(z)),
                        pairs=pairs, control=bool(b.get("control_group")), end=b.get("end"), ai=bool(b.get("ai"))))
    cand = sorted([x for x in out if not x["control"]], key=lambda x: x["z"])
    lead = cand[0] if cand else None
    main = None
    if lead and lead["z"] <= R["lead_max"] and any(p["level"] != "平常" for p in lead["pairs"]):
        main = dict(id=lead["id"], name=lead["name"], z=lead["z"], pair=next(p for p in lead["pairs"] if p["level"] != "平常"), end=lead["end"])
    return dict(asof=t.strftime("%Y-%m-%d"), version=R["version"], baskets=sorted(out, key=lambda x: x["z"]), lead=lead and lead["id"], main=main)


def values(res):
    """自检比对用：扁平的数字。"""
    v = {"main": res["main"]["id"] if res["main"] else ""}
    for b in res["baskets"]:
        v[b["id"] + ".z"] = b["z"]
        for p in b["pairs"]:
            v[f"{b['id']}.{p['id']}.frac"] = p["frac"]
    return v


def heat(now=None):
    """主题热度（只作描述）：5 日条数 ÷（60 日日均 × 5）；到 100 条封顶的那天不算。"""
    from qx import news as NW
    _, counts = NW.load()
    days = sorted(counts)
    if len(days) < 10:
        return {"note": f"要闻条数从 {days[0] if days else '—'} 起攒，满 10 天才算", "rows": []}
    names = {t["id"]: t["name"] for t in NW.TOPICS}
    rows = []
    for tid, nm in names.items():
        cap = next((NW.cap(t) for t in NW.TOPICS if t["id"] == tid), None)
        v = [(d, counts[d].get(tid)) for d in days if counts[d].get(tid) is not None]
        ok = [(d, x) for d, x in v if not cap or x < cap]
        if len(ok) < 10:
            continue
        last5 = [x for d, x in ok[-5:]]
        base = [x for d, x in ok[-65:-5]]
        if not base or np.mean(base) <= 0:
            continue
        rows.append(dict(topic=nm, ratio=round(sum(last5) / (np.mean(base) * 5), 2), n5=int(sum(last5)), base=round(float(np.mean(base)), 1),
                         capped=sum(1 for d, x in v[-5:] if cap and x >= cap)))
    rows.sort(key=lambda r: -r["ratio"])
    return {"note": "只作描述：60 日窗口不符合\"不用滚动窗口\"，不进任何规则", "rows": rows[:6], "since": days[0]}


def block(D):
    t = max(D[k].index[-1] for k in ("^SOX", "^GSPC") if k in D)
    res = compute(D, t)
    res["heat"] = heat()
    return res
