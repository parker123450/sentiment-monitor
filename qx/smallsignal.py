"""小信号（第四轮第 3 步，2026-10-27）。规则在 口径.md 第十一节，推演链登记在 登记/chains.toml。

compute(D, t, pos)   截至 t：
  1. 冷门市场先动：信用利差（单 B、BB、CCC、BBB、投资级）、高收益债 ÷ 中期国债、美债波动、日本 30 年国债、汇率、商品、扫描范围里的利率和信用的 5 日变化，
     在当天以前全部历史里同方向更极端的占几成：不超过 1%（汇率、商品、日本国债这些联动市场 0.5%）写"少见"，不超过 5% 写"偏高"。只列偏高以上。
  2. 一手来源第一次提到：快讯（qx/flash.py）里 t 以前 24 小时看到的"第一次"。
  3. 数据动了价格没跟：台湾月营收同比和股价 20 日涨跌方向相反（只作描述）。
  4. 推演链：每一环的读数出现偏高以上、方向是登记的"压力方向"，这一环就"亮"；前一环亮了 20 个交易日内下一环也亮，算往下走了一环。每条小信号写"下一环看什么"。
  5. 不对称：小信号对某个市场的多头不利、而这个市场的仓位挤在多头（或者反过来），标"不对称"，进机会卡第 1 类（第 4 步）。
只用 t 以前能看到的数据（FRED、日本国债按次一日才可用），自检核对。
"""
import os, tomllib

import numpy as np
import pandas as pd

from qx import coverage as C, positioning as PS
from qx.registry import SERIES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAINS = os.path.join(ROOT, "登记", "chains.toml")
N5, MIN_DAYS = 5, 504
RARE, RARE_LINKED, HIGH = 0.01, 0.005, 0.05
COLD = [("BAMLH0A2HYB", "单 B 利差"), ("BAMLH0A1HYBB", "BB 利差"), ("BAMLH0A3HYC", "CCC 利差"), ("BAMLC0A4CBBB", "BBB 利差"), ("BAMLC0A0CM", "投资级利差"),
        ("HYG/IEF", "高收益债 ÷ 中期国债"), ("^MOVE", "美债波动"), ("JGB30", "日本 30 年国债"), ("JGB10", "日本 10 年国债"), ("JPY=X", "美元兑日元"), ("CL=F", "原油 WTI")]
LINKED = {"汇率", "商品", "日本", "韩国", "台湾", "香港", "A 股", "欧洲"}
# 小信号 → 仓位的市场（positioning 的 market），和"对这个市场的多头不利"是哪个方向
POS_MAP = {"CL=F": ("原油", "down"), "BZ=F": ("原油", "down"), "GC=F": ("黄金", "down"), "HG=F": ("铜", "down"), "NG=F": ("天然气", "down"),
           "ZC=F": ("农产品", "down"), "ZS=F": ("农产品", "down"), "ZW=F": ("农产品", "down"), "^TNX": ("美债", "up"), "^TYX": ("美债", "up"),
           "^FVX": ("美债", "up"), "TLT": ("美债", "down"), "^MOVE": ("美债", "up"), "JPY=X": ("日元", "up"), "DX-Y.NYB": ("美元", "down"),
           "EURUSD=X": ("欧元", "down"), "BTC-USD": ("加密", "down"), "ETH-USD": ("加密", "down"), "BAMLH0A2HYB": ("美股", "up"),
           "BAMLH0A1HYBB": ("美股", "up"), "BAMLH0A3HYC": ("美股", "up"), "BAMLC0A4CBBB": ("美股", "up"), "BAMLC0A0CM": ("美股", "up"),
           "HYG/IEF": ("美股", "down"), "^VIX": ("美股", "up"), "^VXN": ("美股", "up")}
NAMES = dict(COLD)


def chains(day=None):
    """推演链的登记表。day：只要那天在用的版本（since ≤ day、还没到 until）；不给 day 是全部版本（只给页面列登记表用）。"""
    with open(CHAINS, "rb") as f:
        R = tomllib.load(f)
    ok = lambda x: (not day or x.get("since", R["since"]) <= day) and (not x.get("until") or not day or day < x["until"])
    return dict(R, chain=[c for c in R.get("chain", []) if ok(c)])


def chains_at(t):
    """t 那天在用的推演链；登记以前的日子（回放）用第一版。"""
    with open(CHAINS, "rb") as f:
        first = tomllib.load(f)["since"]
    return chains(max(pd.Timestamp(t).strftime("%Y-%m-%d"), first))


def _late(k):
    return k in SERIES and SERIES[k]["source"] == "FRED"


def series(D, k, t):
    """→ (序列, 按基点吗)。只用 t 能看到的：FRED、日本国债要 t 以前的观测。"""
    t = pd.Timestamp(t)
    if k.startswith("JGB"):
        s = PS.jgb_series(t, "y" + k[3:])                      # pub = 那一天的下一天
        return (s[s.index < t] if s is not None else None), True
    if "/" in k:
        a, _ = series(D, k.split("/")[0], t)
        b, _ = series(D, k.split("/")[1], t)
        if a is None or b is None:
            return None, False
        return (a / b.reindex(a.index)).dropna(), False
    if k not in D:
        return None, False
    s = D[k]["c"].dropna()
    s = s[s.index < t] if _late(k) else s[s.index <= t]
    return s, _late(k) or k in C.BP


def change(s, bp, n=N5):
    return ((s - s.shift(n)) * 100 if bp else np.log(s / s.shift(n))).dropna()


def rarity(ch):
    """最后一天的变化在它以前全部历史里：同方向更极端（含相等）的占几成。"""
    if len(ch) < MIN_DAYS:
        return None
    x, h = float(ch.iloc[-1]), ch.iloc[:-1]
    if x == 0:
        return None
    return float((h >= x).mean()) if x > 0 else float((h <= x).mean())


def _level(frac, linked):
    if frac is None:
        return None
    return "少见" if frac <= (RARE_LINKED if linked else RARE) else "偏高" if frac <= HIGH else None


def universe(CH=None):
    xs = list(COLD)
    for s in C.SCAN:
        if C.CLASS.get(s) in ("利率", "汇率", "商品", "信用", "波动"):
            xs.append((s, C.NAME.get(s, s)))
    for ch in (CH or chains())["chain"]:
        for L in ch["links"]:
            for s in L["series"]:
                xs.append((s, NAMES.get(s) or C.NAME.get(s, s)))
    seen, out = set(), []
    for k, nm in xs:                                          # 同一个读数只列一次（名字以先登记的为准）
        if k not in seen:
            seen.add(k)
            out.append((k, nm))
    return out


def _fmt(k, x, bp):
    if bp:
        return f"{'升' if x > 0 else '降'}了 {abs(x):.0f} 个基点"
    return f"{'涨' if x > 0 else '跌'}了 {abs(np.exp(x) - 1) * 100:.1f}%"


def one(D, k, t):
    s, bp = series(D, k, t)
    if s is None or len(s) < MIN_DAYS + N5:
        return None
    ch = change(s, bp)
    if not len(ch) or ch.index[-1] < pd.Timestamp(t) - pd.Timedelta(days=7):      # 读数太旧（停更的源）不算
        return None
    frac = rarity(ch)
    linked = k.startswith("JGB") or C.CLASS.get(k) in LINKED
    return dict(k=k, chg=float(ch.iloc[-1]), bp=bp, frac=frac, level=_level(frac, linked), dir="up" if ch.iloc[-1] > 0 else "down",
                asof=ch.index[-1].strftime("%Y-%m-%d"))


def _link_of(k, CH=None):
    for ch in (CH or chains())["chain"]:
        for i, L in enumerate(ch["links"]):
            if k in L["series"]:
                return ch, i
    return None, None


def chain_state(D, t, cache, R=None):
    """每条链：每一环最近 20 个交易日里最后一次"亮"的日子；往下走到第几环；下一环看什么。"""
    t = pd.Timestamp(t)
    R = R or chains_at(t)
    days = pd.bdate_range(end=t, periods=R["window"])
    out = []
    for ch in R["chain"]:
        lit = []
        for L in ch["links"]:
            last = None
            for k, st in zip(L["series"], L["stress"]):
                key = ("lit", k, st)
                if key not in cache:
                    s, bp = series(D, k, t)
                    hit = []
                    if s is not None and len(s) > MIN_DAYS + N5:
                        cg = change(s, bp)
                        for d in days:
                            c_ = cg[cg.index <= d]
                            if len(c_) and c_.index[-1] >= d - pd.Timedelta(days=4):
                                f = rarity(c_)
                                linked = k.startswith("JGB") or C.CLASS.get(k) in LINKED
                                if _level(f, linked) and (c_.iloc[-1] > 0) == (st == "up"):
                                    hit.append(c_.index[-1])
                    cache[key] = max(hit) if hit else None
                if cache[key] is not None and (last is None or cache[key] > last):
                    last = cache[key]
            lit.append(last)
        step = 0                                              # 按顺序：后一环亮的日子不早于前一环，而且相隔不超过 window 个交易日
        for i, d in enumerate(lit):
            if d is None:
                break
            if i:
                gap = int(np.busday_count(lit[i - 1].date(), d.date()))
                if gap < 0 or gap > R["window"]:
                    break
            step = i + 1
        nxt = ch["links"][step] if step < len(ch["links"]) else None
        out.append(dict(id=ch["id"], name=ch["name"], step=step, of=len(ch["links"]),
                        links=[dict(name=L["name"], lit=d.strftime("%Y-%m-%d") if d is not None else None, check=L["check"]) for L, d in zip(ch["links"], lit)],
                        next=dict(name=nxt["name"], check=nxt["check"]) if nxt else None))
    return out


def firsts(t, hours=24):
    from qx import flash
    t = pd.Timestamp(t, tz="UTC") if pd.Timestamp(t).tzinfo is None else pd.Timestamp(t)
    end = (t + pd.Timedelta(days=1)).isoformat()                    # 收盘日 t 当天看到的都算
    start = (t - pd.Timedelta(hours=hours)).isoformat()
    W = flash.watch_ids(max(t.strftime("%Y-%m-%d"), flash.registry()["since"]))   # 那天在用的观察名单（登记以前用第一版）
    out = []
    for r in flash.load_rows():
        v = flash.visible(r)
        if start <= v < end and r["first"]:
            for k in r["first"].split("|"):
                e, ln = k.split(":")
                out.append(dict(key=k, ent=flash.name(e), line=flash.LINE_NAME.get(ln, ln), watch=e in W, t=r["t"], src=r["src"], at=v))
    return out


def mismatch(D, t):
    """台湾月营收同比 vs 股价 20 日涨跌：方向相反写"对不上"（只作描述）。"""
    from qx import fundamentals as F
    rows = F.load_tw()                                        # 自检截断时这里只给 pub ≤ t 的行（qx/selftest.py 的 extras_cut）
    if not rows:
        return []
    t = pd.Timestamp(t)
    out = []
    for code, nm in F.TW.items():
        rs = sorted((r for r in rows if r["code"] == code and r.get("pub") and pd.Timestamp(r["pub"][:10]) <= t), key=lambda r: r["ym"])
        if not rs:
            continue
        r = rs[-1]
        if (t - pd.Timestamp(r["pub"][:10])).days > 35:
            continue
        sym = code + ".TW"
        s, _ = series(D, sym, t)
        if s is None or len(s) < 25:
            continue
        r20 = float(np.log(s.iloc[-1] / s.iloc[-21]))
        try:
            yoy = float(r["yoy"])
        except ValueError:
            continue
        if np.sign(yoy) != np.sign(r20) and abs(yoy) >= 10:
            out.append(dict(name=nm, ym=r["ym"], yoy=yoy, r20=round(r20 * 100, 1), note="营收和股价方向相反（只作描述）"))
    return out


def compute(D, t, pos=None):
    t = pd.Timestamp(t)
    pos = pos if pos is not None else PS.compute(D, t)
    crowd = {c["market"]: c["word"] for c in pos["crowd"]}
    sig = []
    CH = chains_at(t)                                         # t 那天在用的推演链版本
    for k, nm in universe(CH):
        x = one(D, k, t)
        if not x or not x["level"]:
            continue
        ch, i = _link_of(k, CH)
        nxt, against = None, False
        if ch is not None:
            st = ch["links"][i]["stress"][ch["links"][i]["series"].index(k)]
            against = x["dir"] != st                          # 和登记的压力方向相反：不往推演链下一环推
            nxt = ch["links"][i + 1] if i + 1 < len(ch["links"]) else None
        pm = POS_MAP.get(k)
        asym = None
        if pm:
            bad_for_longs = x["dir"] == pm[1]
            cw = crowd.get(pm[0])
            if (bad_for_longs and cw == "挤在多头") or (not bad_for_longs and cw == "挤在空头"):
                asym = dict(market=pm[0], crowd=cw, word="对多头不利、仓位挤在多头" if bad_for_longs else "对空头不利、仓位挤在空头")
        sig.append(dict(x, name=nm, cls=C.CLASS.get(k, "信用" if _late(k) or "/" in k else ""), text=f"{nm} 5 日{_fmt(k, x['chg'], x['bp'])}",
                        chain=ch["name"] if ch and not against else None,
                        next=(f"和{ch['name']}登记的压力方向相反" if ch and against else f"{ch['name']}的下一环：{nxt['name']}（{nxt['check']}）" if nxt else
                              f"{ch['name']}的最后一环" if ch else "没有登记在推演链里"), asym=asym))
    sig.sort(key=lambda x: x["frac"])
    return dict(asof=t.strftime("%Y-%m-%d"), signals=sig, chains=chain_state(D, t, {}, CH), firsts=firsts(t), mismatch=mismatch(D, t))


def values(res):
    v = {"n": len(res["signals"])}
    for x in res["signals"]:
        v["sig:" + x["k"]] = x["frac"]
    for c in res["chains"]:
        v["chain:" + c["id"]] = c["step"]
    return v
