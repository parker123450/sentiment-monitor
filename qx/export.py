"""给页面导出数据（从 原型/导出.py 改来，2026-10-23）。数字都在这里算好，页面只画、只把数字写成白话。

- chart：多个品种的日线 [日期, 开, 高, 低, 收, 量]、RSI(14)、摆动高低点、抛售日、涨过头日
- daily：半导体市场每天的读数（阶段、四条读数和它们在加速还是减速、分型、VIX、期限结构、成分股广度）和写白话用的事实
- turns：转折标签（恐慌高峰、恐慌退潮、二次探底、参与度先走；口径.md 二.2）
- groups：产业链分组今天的事实；ice：分评级信用利差；cnn：CNN 恐慌贪婪；status：各数据源新不新
"""
import csv, os
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

from qx import store, watch, events, options, happen, judge, notify
from qx.registry import SMALL, AI, SERIES
from qx.sentiment import longvol, NAMES, MOM_WORDS

START = "2017-01-01"
BJ = timezone(timedelta(hours=8))
SYMS = [("^SOX", "费城半导体", "SMH"), ("SMH", "SMH", None), ("^NDX", "纳指 100", None), ("^GSPC", "标普 500", None), ("NVDA", "英伟达", None),
        ("MU", "美光", None), ("TSM", "台积电", None), ("^KS11", "KOSPI", None), ("000660.KS", "SK 海力士", None), ("005930.KS", "三星电子", None),
        ("AAOI", "AAOI", None), ("CRWV", "CoreWeave", None)]
ICE = [("BAMLC0A0CM", "投资级"), ("BAMLC0A4CBBB", "BBB"), ("BAMLH0A1HYBB", "BB"), ("BAMLH0A2HYB", "B"), ("BAMLH0A3HYC", "CCC 及以下")]


def rsi(c, n=14):
    r = c.diff()
    up, dn = r.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-r.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def pivots(c, k=10):
    """摆动高低点：前后各 k 天里的最高 / 最低收盘（只用来画结构线，最新的点要等 k 天才确认）。"""
    out, v = [], c.values
    for i in range(k, len(v) - k):
        w = v[i - k: i + k + 1]
        if v[i] == w.max():
            out.append([c.index[i].strftime("%Y-%m-%d"), "H", round(float(v[i]), 2)])
        elif v[i] == w.min():
            out.append([c.index[i].strftime("%Y-%m-%d"), "L", round(float(v[i]), 2)])
    return out[-60:]


def _num(x, dg):
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), dg) if dg else int(round(float(x)))


def chart(D):
    out = []
    for src, name, volsrc in SYMS:
        if src not in D:
            continue
        d = D[src][["o", "h", "l", "c", "v"]].copy()
        if volsrc and volsrc in D:
            d["v"] = D[volsrc]["v"].reindex(d.index)
        c = d.c
        R = rsi(c)
        v50 = d.v.rolling(50).mean()
        ret = c.pct_change()
        climax = d.index[(d.v >= 2 * v50) & (ret <= -0.02) & (R <= 40)]
        hot = d.index[(R >= 75) & (c >= 1.15 * c.rolling(50).mean())]
        dd_ = d[d.index >= START]
        rows = [[t.strftime("%Y-%m-%d")] + [_num(x, 2) for x in r[:4]] + [_num(r[4], 0)] for t, r in zip(dd_.index, dd_[["o", "h", "l", "c", "v"]].values)]
        out.append(dict(k=src.replace("^", ""), n=name, vnote="SMH 成交量" if volsrc else "成交量", rows=rows,
                        rsi=[_num(x, 1) for x in R.reindex(dd_.index).values],
                        climax=[t.strftime("%Y-%m-%d") for t in climax if t >= pd.Timestamp(START)],
                        hot=[t.strftime("%Y-%m-%d") for t in hot if t >= pd.Timestamp(START)],
                        pivots=[p for p in pivots(c) if p[0] >= START]))
    return out


def group_facts(D, R):
    idx = R["P"].index
    U = R["U"]
    load = lambda ts: pd.DataFrame({t: D[t]["c"] for t in ts if t in D}).reindex(idx)
    G = {"大盘半导体": U, "小盘半导体": load(SMALL)}
    for k, v in AI.items():
        G[k] = load(v)
    out = []
    for k, Ug in G.items():
        ma = Ug.rolling(20).mean()
        n = int(ma.iloc[-1].notna().sum())
        if not n:
            continue
        out.append(dict(name=k, n=n, below=int(((Ug.iloc[-1] < ma.iloc[-1]) & ma.iloc[-1].notna()).sum()),
                        low=int((Ug.iloc[-1] <= Ug.rolling(20).min().iloc[-1]).sum()),
                        dd=_num((Ug.iloc[-1] / Ug.rolling(252, min_periods=20).max().iloc[-1] - 1).median() * 100, 0),
                        r10=_num((Ug.iloc[-1] / Ug.iloc[-11] - 1).median() * 100, 1),
                        names=" ".join(AI.get(k, [])) if k in AI else ""))
    return out


def ice(D):
    out = {}
    for sid, nm in ICE:
        if sid not in D:
            continue
        d = D[sid]["c"]
        d3 = d[d.index >= d.index[-1] - pd.Timedelta(days=3 * 365)]
        out[nm] = dict(now=_num(d.iloc[-1] * 100, 0), m1=_num(d.iloc[-21] * 100, 0), lo=_num(d3.min() * 100, 0), hi=_num(d3.max() * 100, 0),
                       date=d.index[-1].strftime("%Y-%m-%d"))
    return out


RATING = {"extreme fear": "极度恐惧", "fear": "恐惧", "neutral": "中性", "greed": "贪婪", "extreme greed": "极度贪婪"}


def cnn():
    p = os.path.join(store.HERE, "cnn.csv")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: r["date"])
    if not rows:
        return None
    last = rows[-1]
    back = lambda days: next((float(r["score"]) for r in reversed(rows) if r["date"] <= (pd.Timestamp(last["date"]) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")), None)
    return dict(date=last["date"], now=round(float(last["score"])), word=RATING.get(last["rating"], last["rating"]),
                w1=_num(back(7), 0), m1=_num(back(30), 0))


def status(D, aaii, meta):
    """各数据源最新到哪天、这次取到没有（页头提醒用）。"""
    s = {}
    for k, nm in [("BAA10Y", "信用利差（FRED）"), ("PC_EQ", "认沽认购（CBOE）"), ("^VXN", "VXN")]:
        s[nm] = dict(last=D[k].index[-1].strftime("%Y-%m-%d") if k in D else None, status=(meta.get(k) or {}).get("status", "local"))
    s["AAII 散户调查"] = dict(last=aaii.index[-1].strftime("%Y-%m-%d") if aaii is not None and len(aaii) else None,
                          status=(meta.get("_aaii") or {}).get("status", "local"))
    return s


def today(D, R, opt=None, hap=None, jud=None):
    """第 1 块"今天要知道的"：收盘版 + 盘中版 + 前几天说过的 + 接下来两个交易日 + 趋势状态表（规则在 口径.md 第三节）。"""
    import json
    t = R["P"].index[-1]
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    t_other = max([D[k].index[-1] for k in watch.NAME if k in D and k not in watch.US and D[k].index[-1] <= now] + [t])
    items = watch.close_items(D, R, t, t_other)
    try:
        q = json.load(open(os.path.join(store.HERE, "intraday.json"), encoding="utf-8"))
    except Exception:
        q = {}
    have = {(x["group"], x["date"]) for x in items if x["kind"] == "move"}
    live = [x for x in watch.live_items(D, q, t) if (x["group"], x["date"]) not in have]
    extra = ((opt or {}).get("items") or []) + ((hap or {}).get("items") or []) + ((jud or {}).get("items") or [])
    items = sorted(items + live + extra, key=lambda x: (x["kind"] != "judge", x["n10"] is None, x["n10"] or 0, not x["us"]))      # 和你的判断有关的排最前
    items = happen.attach_news(items)
    recent = []
    for d in R["P"].index[-5:-1][::-1]:
        for x in watch.close_items(D, R, d):
            recent.append(dict(x, date=d.strftime("%Y-%m-%d")))
    return dict(asof=t.strftime("%Y-%m-%d"), items=items, recent=recent, upcoming=watch.upcoming(events.load()),
                trends=watch.trends(D, t), quotes_at=(q or {}).get("fetched"))


def build(D, aaii, R, write=False):
    P, F, U = R["P"], R["F"], R["U"]
    meta = store.read_meta()
    c = P.sox
    vol = P.smh_vol
    ma20u, ma50u, ma200u = U.rolling(20).mean(), U.rolling(50).mean(), U.rolling(200).mean()
    lv = longvol(c.dropna()).reindex(P.index) / np.sqrt(252)
    med = lambda s: s.rolling(60, min_periods=40).median()
    t3 = P.vix / P.vix3m
    aaii_s = (P.aaii_bull - P.aaii_bear) * 100
    pc10 = P.pc_eq.rolling(10).mean()
    cols = {
        "state": R["stage"], "sell": R["sell"], "price": R["price"], "pos": R["pos"], "credit": R["credit"], "credn": R["credit_n"],
        "msell": R["m_sell"], "mprice": R["m_price"], "mpos": R["m_pos"], "mcredit": R["m_credit"], "regime": R["regime"], "vixmax": R["vixmax"],
        "vix": P.vix, "t3": t3, "dd": R["dd"] * 100,
        "pct50": ((U > ma50u) & ma50u.notna()).sum(1) / ma50u.notna().sum(1).replace(0, np.nan) * 100,
        "pct200": ((U > ma200u) & ma200u.notna()).sum(1) / ma200u.notna().sum(1).replace(0, np.nan) * 100,
        "nb20": ((U < ma20u) & ma20u.notna()).sum(1), "n20": ma20u.notna().sum(1), "nb20p": F["below20.lvl"],
        "nlow": ((U <= U.rolling(20).min()) & U.rolling(20).min().notna()).sum(1).rolling(5).mean(), "nlowp": F["newlow.lvl"],
        "volx": vol.rolling(5).mean() / vol.rolling(50).mean(), "volxp": F["volspk.lvl"],
        "r10": (c / c.shift(10) - 1) * 100, "r10x": np.log(c / c.shift(10)).abs() / (lv * np.sqrt(10)), "r10p": F["ret10.lvl"],
        "vixm": med(P.vix), "vixrp": F["vix.rel"], "vixlp": F["vix.lvl"], "vxn": P.vxn, "vxnm": med(P.vxn), "vxnrp": F["vxn.rel"],
        "t3m": med(t3), "t3rp": F["t3.rel"], "aaii": aaii_s, "aaiip": aaii_s.shift(5), "aaiisp": F["aaii.spd5"],
        "pc": pc10, "pcm": med(pc10), "pcrp": F["pc10.rel"], "baa20": (P.baa - P.baa.shift(20)) * 100, "baarp": F["baa20.rel"],
        "etfp": R["credit"],
    }
    DIG = {"vix": 2, "t3": 3, "dd": 1, "volx": 2, "r10": 1, "r10x": 1, "vixm": 1, "vxn": 1, "vxnm": 1, "t3m": 3, "aaii": 1, "aaiip": 1,
           "pc": 3, "pcm": 3, "nlow": 1, "vixmax": 1}
    days = P.index[P.index >= START]
    daily = {"d": [t.strftime("%Y-%m-%d") for t in days]}
    for k, s in cols.items():
        daily[k] = [_num(v, DIG.get(k, 0)) for v in s.reindex(days).values]
    turns = [[d.strftime("%Y-%m-%d"), k, kn.strftime("%Y-%m-%d")] for d, k, kn in R["turns"] if d >= pd.Timestamp(START)]
    now = datetime.now(BJ)
    opt = options.block(D)
    hap = happen.block(D)
    jud = judge.block(D, R, write=write)
    ch = chart(D)
    for c in ch:
        c["opt"] = opt["chart"].get(c["k"], [])
        c["judge"] = jud["marks"].get(c["k"], [])
    return dict(asof=days[-1].strftime("%Y-%m-%d"), updated=now.strftime("%Y-%m-%d %H:%M"), today=today(D, R, opt, hap, jud), judge=jud["cards"], fb=notify.feedback_topic() or None, options=opt, happen={k: hap[k] for k in ("news", "pm", "calendar", "day")}, chart=ch, daily=daily, turns=turns,
                groups=group_facts(D, R), ice=ice(D), cnn=cnn(), status=status(D, aaii, meta), stnames=NAMES, momwords=MOM_WORDS)
