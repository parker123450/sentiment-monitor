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

from qx import store, watch, events, options, happen, judge, notify, flash, narrative, markets
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
    return [x for x in (chart_one(D, src, name, volsrc) for src, name, volsrc in SYMS) if x]


def kfile(sym):
    """按需加载的文件名（代码里的 ^ = . 换掉）。"""
    return "".join(ch if ch.isalnum() or ch == "-" else "_" for ch in sym) + ".enc"


def write_k(D, site_dir=None, password=None, preview_dir=None):
    """扫描范围里不在页面里的标的，每个写一个 K 线文件：发布用的加密（site/k/），本机预览用明文（本机预览/k/）。返回清单。"""
    import json
    from qx import coverage, crypt
    have = {s for s, _, _ in SYMS}
    out = []
    for s in coverage.SCAN:
        if s in have or s not in D or len(D[s]) < 60:
            continue
        x = chart_one(D, s, coverage.NAME.get(s, s), None)
        if not x:
            continue
        txt = json.dumps(x, ensure_ascii=False, separators=(",", ":"))
        f = kfile(s)
        if site_dir and password:
            os.makedirs(os.path.join(site_dir, "k"), exist_ok=True)
            open(os.path.join(site_dir, "k", f), "wb").write(crypt.encrypt_blob(txt, password))
        if preview_dir:
            os.makedirs(os.path.join(preview_dir, "k"), exist_ok=True)
            open(os.path.join(preview_dir, "k", f), "w", encoding="utf-8").write(txt)
        out.append({"k": x["k"], "n": x["n"], "f": f, "v": D[s].index[-1].strftime("%Y%m%d"), "cls": coverage.CLASS.get(s, "")})   # v：最后一根日线，页面按它取，旧缓存不会冒充新图
    return out


def write_views(data, site_dir=None, password=None, preview_dir=None):
    """说明、状态两个视图（第四轮后台精简第 2 步，方案第四节），点了才加载，和 K 线文件同一个做法：发布用页面同一把钥匙加密（site/v/），
    本机预览写明文（本机预览/v/）。内容在 qx/front.py views() 里按 data 写好；只给页面用，推送不读。返回清单 {名字: {f, v}}，v 是内容的指纹（旧缓存不会冒充新的）。"""
    import hashlib, json
    from qx import crypt, front
    out = {}
    for name, h in front.views(data).items():
        txt = json.dumps({"html": h}, ensure_ascii=False, separators=(",", ":"))
        f = name + ".enc"
        if site_dir and password:
            os.makedirs(os.path.join(site_dir, "v"), exist_ok=True)
            open(os.path.join(site_dir, "v", f), "wb").write(crypt.encrypt_blob(txt, password))
        if preview_dir:
            os.makedirs(os.path.join(preview_dir, "v"), exist_ok=True)
            open(os.path.join(preview_dir, "v", f), "w", encoding="utf-8").write(txt)
        out[name] = {"f": f, "v": hashlib.sha256(txt.encode("utf-8")).hexdigest()[:12]}
    return out


def chart_one(D, src, name, volsrc=None):
    if src not in D:
        return None
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
    return dict(k=src.replace("^", ""), n=name, vnote="SMH 成交量" if volsrc else "成交量", rows=rows,
                rsi=[_num(x, 1) for x in R.reindex(dd_.index).values],
                climax=[t.strftime("%Y-%m-%d") for t in climax if t >= pd.Timestamp(START)],
                hot=[t.strftime("%Y-%m-%d") for t in hot if t >= pd.Timestamp(START)],
                pivots=[p for p in pivots(c) if p[0] >= START])


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


def ice(D, t=None):
    """信用分档利差（家在基本面"融资环境"，2026-10-29）。和规则用同一个观测日：FRED 次一个观测日才能用（smallsignal.series）。
    5 日变化的偏高 / 少见按口径十一；三年里的位置只放后台（FRED 只给 3 年，是滚动的，不进规则）。"""
    from qx import smallsignal as SS
    t = pd.Timestamp(t) if t is not None else None
    out = {}
    for sid, nm in ICE:
        if sid not in D:
            continue
        s, _ = SS.series(D, sid, t) if t is not None else (D[sid]["c"].dropna(), True)
        if s is None or len(s) < 22:
            continue
        ch5 = SS.change(s, True, SS.N5)
        f5 = SS.rarity(ch5)
        d3 = s[s.index >= s.index[-1] - pd.Timedelta(days=3 * 365)]
        out[nm] = dict(sid=sid, now=_num(s.iloc[-1] * 100, 0), m1=_num(s.iloc[-21] * 100, 0), c5=_num(ch5.iloc[-1], 0), f5=_num(f5, 4),
                       lvl5=SS._level(f5, False), up=bool(ch5.iloc[-1] > 0),
                       lo=_num(d3.min() * 100, 0), hi=_num(d3.max() * 100, 0), date=s.index[-1].strftime("%Y-%m-%d"))
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
    try:
        fl = flash.block()
    except Exception:
        fl = None
    radar = {}
    from qx import smallsignal, positioning
    t_last = max(D[k].index[-1] for k in ("^SOX", "^GSPC") if k in D)
    pos = {}
    def _pos():
        pos["v"] = positioning.compute(D, t_last)
        return pos["v"]
    for k, f in (("narr", lambda: narrative.block(D)), ("mkts", lambda: markets.rows(D)), ("pos", _pos),
                 ("sig", lambda: smallsignal.compute(D, t_last, pos.get("v")))):
        try:
            radar[k] = f()
        except Exception as e:
            radar[k] = None
            radar[k + "_err"] = type(e).__name__
    try:
        from qx import radar as RA
        radar["cards"] = RA.compute(D, t_last, radar.get("pos"), radar.get("sig"), (hap or {}).get("items"))
    except Exception as e:
        radar["cards"], radar["cards_err"] = None, type(e).__name__
    try:
        from qx import forward as FW                      # 前瞻（第四轮第 5 步）：六条线、时间轴、三种走向、AI 账本
        radar["fwd"] = FW.block(D, t_last, radar, write=write)
    except Exception as e:
        radar["fwd"], radar["fwd_err"] = None, type(e).__name__
    wu, wt = os.environ.get("WORKER_URL", "").strip(), os.environ.get("WORKER_READ_TOKEN", "").strip()
    radar["live"] = {"url": wu, "token": wt} if wu and wt else None          # 只读令牌，放在加密页里（口径.md 第十节）
    radar["built"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        from qx import notify as NT
        radar["pushed"] = NT.recent()                     # Worker 连不上时云端直接发的（口径十四.11）
    except Exception:
        radar["pushed"] = []
    td, ic = today(D, R, opt, hap, jud), ice(D, days[-1])
    try:
        from qx import front as FR                         # 前台五样（第四轮五样方案，口径十四）：只挑已算好的结果按五样摆
        fr = FR.build(D, R, radar, td, hap, ic, events.load(), opt=opt)
    except Exception as e:
        fr = {"err": type(e).__name__}
    return dict(flash=fl, radar=radar, front=fr, asof=days[-1].strftime("%Y-%m-%d"), updated=now.strftime("%Y-%m-%d %H:%M"), today=td, judge=jud["cards"], fb=notify.feedback_topic() or None, options=opt, happen={k: hap[k] for k in ("news", "pm", "calendar", "day")}, chart=ch, daily=daily, turns=turns,
                groups=group_facts(D, R), ice=ic, cnn=cnn(), status=status(D, aaii, meta), stnames=NAMES, momwords=MOM_WORDS, mkmap=mkmap())


def mkmap():
    """新4：qx/watch.py GROUPS 的组名 → 这个组的代码在"各市场"的哪几类（类来自 qx/coverage.py CLASS）。只给页面用：
    盘中涨跌推送 move:{组}:live 落到"各市场"里 [data-mk~="组名"] 的那几行。"""
    from qx import coverage
    return {g: sorted({coverage.CLASS[s] for s in syms if s in coverage.CLASS}, key=coverage.CLASSES.index) for g, syms in watch.GROUPS}
