"""各市场时刻和给 Worker 的少见表（第四轮第 2 步，2026-10-27；口径.md 第十节）。

sessions(day)    九个市场当天的开收盘（UTC，含午休、休市）：exchange_calendars 的 XNYS、XTKS、XKRX、XTAI、XSHG、XHKG、XAMS、XETR。
                 深圳没有单独的日历（第 0 步实测没有 XSHE），和上海同一个日历 XSHG；XSHG 只排到当年年底，跨年以后要等库更新，取不到时按"开没开盘不知道"处理。
rare_table(s)    一个标的 1 日对数涨跌在当天以前 2520 天里：两个方向的 1% 和 0.5% 分位，和"涨跌幅 → 过去 10 年同方向几次"的分段表（最极端的 40 档）。
                 和"今天要知道的"同一个口径（qx/watch.py 的 _rarity）：Worker 只查表，不算。
state(D)         推给 Worker 的 markets：{syms, sessions, always, rare, names, at}。
rows(D, live)    页面"各市场一行"：每个大类一行，开没开盘、最新价时点和延迟、今天涨跌（按长期波动折算）。
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from qx import coverage as C

CALS = ["XNYS", "XTKS", "XKRX", "XTAI", "XSHG", "XHKG", "XAMS", "XETR"]
WIN, MIN_WIN, TOP = 2520, 756, 40
CAL_NAME = {"XNYS": "美股", "XTKS": "日本", "XKRX": "韩国", "XTAI": "台湾", "XSHG": "A 股", "XHKG": "香港", "XAMS": "荷兰", "XETR": "德国", "24h": "全天"}


def sessions(day=None):
    """→ {市场: {"open": bool 当天开不开, "s": [[开 ms, 收 ms], ...]（有午休就两段）, "note": 取不到的原因}}"""
    import exchange_calendars as xc
    day = pd.Timestamp(day or datetime.now(timezone.utc).date())
    out = {}
    for c in CALS:
        try:
            k = xc.get_calendar(c)
            if day > k.last_session:
                out[c] = {"open": None, "s": [], "note": "日历只排到 " + str(k.last_session.date())}
                continue
            if not k.is_session(day):
                out[c] = {"open": False, "s": []}
                continue
            o, cl = k.session_open(day), k.session_close(day)
            bs, be = k.session_break_start(day), k.session_break_end(day)
            ms = lambda t: int(t.timestamp() * 1000)
            segs = [[ms(o), ms(bs)], [ms(be), ms(cl)]] if not pd.isna(bs) else [[ms(o), ms(cl)]]
            out[c] = {"open": True, "s": segs}
        except Exception as e:
            out[c] = {"open": None, "s": [], "note": type(e).__name__}
    return out


def is_open(sess, market, now_ms):
    if market == "24h":
        return True
    x = sess.get(market) or {}
    return any(a <= now_ms < b for a, b in x.get("s") or [])


def _ret(D, s):
    if s not in D:
        return None
    c = D[s]["c"]
    c = c[c > 0] if s not in C.BP else c.dropna()
    if len(c) <= MIN_WIN:
        return None
    return (c.diff() * 100 if s in C.BP else np.log(c / c.shift(1))).dropna()


def rare_table(D, s, t=None):
    """当天以前（< t）的历史。收益率类（BP）按基点差，其余按对数涨跌。"""
    r = _ret(D, s)
    if r is None:
        return None
    if t is not None:
        r = r[r.index < t]
    h = r.iloc[-WIN:]
    if len(h) < MIN_WIN:
        return None
    up, dn = np.sort(h[h > 0].values)[::-1][:TOP], np.sort(-h[h < 0].values)[::-1][:TOP]
    # 分段表：[阈值, 同方向至少这么极端的天数]，阈值从小到大（Worker 取最后一个 ≤ 今天涨跌的档）
    tab = lambda v: [[round(float(x), 6), int(i + 1)] for i, x in enumerate(v)][::-1]
    return {"n": len(h), "bp": s in C.BP, "q": {"up1": round(float(h.quantile(0.99)), 6), "up05": round(float(h.quantile(0.995)), 6),
                                                 "dn1": round(float(h.quantile(0.01)), 6), "dn05": round(float(h.quantile(0.005)), 6)},
            "up": tab(up), "down": tab(dn), "lv": round(float(h.std()), 6)}


def state(D, now=None):
    """推给 Worker 的 markets。sessions 给今天和明天（UTC）两天：东京、首尔 UTC 0 点就开盘，Actions 跨日以后要过一阵才再推。
    rare 带 bp（收益率按基点，Worker 要按基点查表）；groups 是"今天要知道的"的分组（qx/watch.py），Worker 的盘中推送用同一个 key
    move:{组}:live|{日期}，和 Actions 推的同一件事去重；up_only 是只看涨的（VIX、VXN）。"""
    from qx import watch as W
    now = now or datetime.now(timezone.utc)
    sess, nxt = sessions(now.date()), sessions(now.date() + timedelta(days=1))
    syms = {s: C.MARKET.get(s, "XNYS") for s in C.CORE if s in D}
    rare = {}
    for s in syms:
        t = rare_table(D, s)
        if t:
            rare[s] = {"up": t["up"], "down": t["down"], "n": t["n"], "bp": t["bp"]}
    return {"syms": syms, "sessions": {k: v["s"] + (nxt.get(k) or {}).get("s", []) for k, v in sess.items()}, "always": ["24h"], "rare": rare,
            "names": {s: C.NAME.get(s, s) for s in syms}, "groups": {s: g for g, ks in W.GROUPS for s in ks if s in syms},
            "up_only": sorted(W.UP_ONLY & set(syms)), "at": int(now.timestamp() * 1000)}


def rows(D, live=None, now=None):
    """页面"各市场一行"：每个大类一行。live：盘中报价 {代码: {p, at, pc}}（Worker 的 /live 或面板 15 分钟一次的 intraday.json）。"""
    now = now or datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    sess = sessions(now.date())
    out = []
    for cls in C.CLASSES:
        all_ = [s for s in C.SCAN if C.CLASS.get(s) == cls]
        syms = [s for s in all_ if s in D and len(D[s]) > 1]
        miss = [C.NAME.get(s, s) for s in all_ if s not in syms]
        if not all_:
            continue
        if not syms:
            out.append({"cls": cls, "market": "", "open": None, "today": None, "note": None, "items": [], "miss": miss})
            continue
        mk = C.MARKET.get(syms[0], "XNYS")
        items = []
        for s in syms:
            c = D[s]["c"].dropna()
            if len(c) < 2:
                continue
            r = _ret(D, s)
            lv = float(r.std()) if r is not None and len(r) > 60 else None           # 长期日波动：全部历史（原则 2，不用最近 2520 天这种滚动窗口）
            q = (live or {}).get(s)
            last, prev = (q["p"], q.get("pc") or float(c.iloc[-1])) if q else (float(c.iloc[-1]), float(c.iloc[-2]))
            chg = (last - prev) * 100 if s in C.BP else (np.log(last / prev) if last > 0 and prev > 0 else None)
            items.append({"s": s, "n": C.NAME.get(s, s), "p": round(last, 4), "chg": None if chg is None else round(float(chg), 5),
                          "z": None if chg is None or not lv else round(float(chg) / lv, 2), "bp": s in C.BP,
                          "at": q.get("at") if q else None, "day": c.index[-1].strftime("%Y-%m-%d")})
        items.sort(key=lambda x: -abs(x["z"] or 0))
        st = sess.get(mk) or {}
        out.append({"cls": cls, "market": CAL_NAME.get(mk, mk), "open": True if mk == "24h" else is_open(sess, mk, now_ms),
                    "today": st.get("open") if mk != "24h" else True, "note": st.get("note"), "items": items, "miss": miss})
    return out
