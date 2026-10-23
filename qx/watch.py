"""今天要知道的（第 2 步，2026-10-23）。规则在 口径.md 第三节，先写的定义再写的代码。

close_items(D, R, t)：截至 t 收盘的"值得看"，只用 t 以前的数据（qx/selftest.py 会核对）。
live_items(D, intraday)：盘中版，用 15 分钟一次的报价对同一份日线历史。
trends(D, t)：每个品种日 / 周 / 月的趋势状态和持续多久（折叠的表）。
upcoming(calendar, now)：接下来两个交易日的日历。
每一条都带 n10 = 过去 10 年发生过几次，页面按它从少到多排。这里把数字写成白话，页面只画。
"""
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from qx import clock
from qx.registry import SMALL
from qx.sentiment import pct, NAMES as STAGE_NAMES, S1, S2, S3

WIN, MIN_WIN, RARE = 2520, 756, 0.02
# 第一次核对条数后改（口径.md 三.10）：美股 1%、联动市场 0.5%；5 日涨跌只看美股
RARE_US, RARE_LINKED = 0.01, 0.005
NAME = {"^SOX": "费城半导体", "SMH": "SMH", "NVDA": "英伟达", "MU": "美光", "TSM": "台积电", "AVGO": "博通", "AMD": "AMD",
        "^GSPC": "标普 500", "^NDX": "纳指 100", "IWM": "罗素 2000", "^VIX": "VIX", "^VXN": "VXN", "^N225": "日经",
        "JPY=X": "美元兑日元", "^KS11": "KOSPI", "000660.KS": "SK 海力士", "005930.KS": "三星电子", "KRW=X": "美元兑韩元",
        "^TWII": "台湾加权", "^HSI": "恒生指数", "000300.SS": "沪深 300", "GC=F": "黄金", "CL=F": "原油", "DX-Y.NYB": "美元指数",
        "^TNX": "10 年美债收益率", "BTC-USD": "比特币"}
GROUPS = [("半导体", ["^SOX", "SMH", "NVDA", "MU", "TSM", "AVGO", "AMD"]), ("美股大盘", ["^GSPC", "^NDX", "IWM"]),
          ("美股保险", ["^VIX", "^VXN"]), ("日本", ["^N225", "JPY=X"]), ("韩国", ["^KS11", "000660.KS", "005930.KS", "KRW=X"]),
          ("台湾", ["^TWII"]), ("中国和香港", ["^HSI", "000300.SS"]), ("黄金", ["GC=F"]), ("原油", ["CL=F"]),
          ("美元和美债", ["DX-Y.NYB", "^TNX"]), ("比特币", ["BTC-USD"])]
US = {"^SOX", "SMH", "NVDA", "MU", "TSM", "AVGO", "AMD", "^GSPC", "^NDX", "IWM", "^VIX", "^VXN"}
UP_ONLY = {"^VIX", "^VXN"}
BP = {"^TNX"}
FX_NOTE = {"JPY=X": ("日元走弱", "日元走强"), "KRW=X": ("韩元走弱", "韩元走强"), "DX-Y.NYB": ("美元走强", "美元走弱")}
TREND_FOCUS = ["^SOX", "^NDX", "^GSPC"]
MONTH_FOCUS = TREND_FOCUS + ["^N225", "^KS11"]
TREND_ROWS = ["^SOX", "^NDX", "^GSPC", "IWM", "NVDA", "MU", "TSM", "AVGO", "AMD", "^N225", "^KS11", "000660.KS", "005930.KS", "^TWII",
              "^HSI", "000300.SS", "GC=F", "CL=F", "JPY=X", "DX-Y.NYB", "^TNX", "BTC-USD"]
PAIRS = [("^SOX", "^KS11", "半导体和 KOSPI"), ("^SOX", "^TWII", "半导体和台湾"), ("^N225", "JPY=X", "日经和美元兑日元"),
         ("^NDX", "^TNX", "纳指和 10 年美债收益率"), ("BTC-USD", "^NDX", "比特币和纳指"), ("GC=F", "DX-Y.NYB", "黄金和美元指数")]
LINE_NAMES = {"sell": "抛售恐慌（成分股一起跌、创新低）", "price": "定价恐慌（科技股保险比平时贵）", "pos": "仓位恐慌（抢买认沽、散户转空）",
              "credit": "信用压力（信用 ETF 跑输国债）"}
STAGE_MEAN = {1: "历史上在卖多在最低点前 3 到 5 周出现；半导体 21 次大跌都经过这一段。", 2: "在怕多在最低点前 1 到 3 周；21 次大跌全都到了在怕，19 次到了投降。",
              3: "投降多在最低点前后几天；但进入投降只有约两成在 3 周内见底。", 4: "恐慌在退。留意二次探底：价格回到低点附近、恐慌没跟上。",
              0: "回撤收窄到长期波动的 0.3 倍以内，这一段下跌结束了。"}


def first_in(flag, n):
    """flag 今天亮、前 n 天都没亮。"""
    f = flag.fillna(False).astype(bool)
    return f & ~(f.astype(float).shift(1).rolling(n, min_periods=1).max().fillna(0) > 0)


def _close(D, k, t):
    if k not in D:
        return None
    s = D[k]["c"]
    s = s[(s.index <= t) & (s > 0 if k not in BP else s.notna())]
    return s if len(s) > MIN_WIN else None


def _ret(s, k, n):
    return (s - s.shift(n)) * 100 if k in BP else np.log(s / s.shift(n))


def sp(name):
    """名字是英文结尾的，后面接中文时加个空格（"VXN 一天"）。"""
    return name + (" " if name and name[-1].isascii() else "")


def _fmt_move(k, x, n):
    """一个涨跌写成白话。"""
    if k in BP:
        return f"{'升' if x > 0 else '降'}了 {abs(x):.0f} 个基点"
    p = (np.exp(x) - 1) * 100
    return f"{'涨' if p > 0 else '跌'}了 {abs(p):.1f}%"


def _rarity(r, today):
    """r：历史收益（不含今天）。返回 (同方向至少一样极端的天数, 窗口长度)。"""
    h = r.iloc[-WIN:]
    k = int((h <= today).sum()) if today < 0 else int((h >= today).sum())
    return k, len(h)


def _after(s, r, today, k_, n=20):
    """过去 10 年同样极端的那些天（相隔 5 天以内算一次）之后 n 天：几次、几次涨、中位数。"""
    h = r.iloc[-WIN:]
    hit = h[(h <= today) if today < 0 else (h >= today)].index
    ev, last = [], None
    pos = {d: i for i, d in enumerate(s.index)}
    for d in hit:
        i = pos[d]
        if last is not None and i - last <= 5:
            continue
        last = i
        if i + n < len(s):
            ev.append(s.iloc[i + n] / s.iloc[i] - 1 if k_ not in BP else None)
    ev = [x for x in ev if x is not None]
    if len(ev) < 5:
        return None
    return dict(n=len(ev), up=int(sum(x > 0 for x in ev)), med=float(np.median(ev) * 100))


def _move_one(D, k, t, n):
    s = _close(D, k, t)
    if s is None:
        return None
    r = _ret(s, k, n).dropna()
    if len(r) < MIN_WIN + 1:
        return None
    today, d = float(r.iloc[-1]), r.index[-1]
    if today == 0 or (k in UP_ONLY and today < 0):
        return None
    hist = r.iloc[:-1]
    kk, w = _rarity(hist, today)
    if kk / w > (RARE_US if k in US else RARE_LINKED):
        return None
    if n > 1:      # 5 日：比前 5 天的 5 日涨跌都更极端才说
        prev = r.iloc[-6:-1]
        if (today < 0 and (prev <= today).any()) or (today > 0 and (prev >= today).any()):
            return None
    yrs = w / 252
    return dict(k=k, n=n, date=d, x=today, cnt=kk, win=w, yrs=yrs, n10=kk * WIN / w, after=_after(s, hist, today, k) if n == 1 else None)


def _move_text(m, live=False):
    nm = NAME.get(m["k"], m["k"])
    span = "一天" if m["n"] == 1 else f"{m['n']} 天"
    yrs = "过去 10 年" if m["yrs"] >= 9.5 else f"过去 {m['yrs']:.0f} 年"
    unit = "天" if m["n"] == 1 else f"个 {m['n']} 天"
    more = ("升得" if m["x"] > 0 else "降得") if m["k"] in BP else ("涨得" if m["x"] > 0 else "跌得")
    note = FX_NOTE.get(m["k"])
    note = f"（{note[0] if m['x'] > 0 else note[1]}）" if note else ""
    return f"{sp(nm)}{span}{_fmt_move(m['k'], m['x'], m['n'])}{note}，{yrs}只有 {m['cnt']} {unit}{more}更多"


def _move_group(name, ms, live=False):
    ms = sorted(ms, key=lambda m: m["cnt"] / m["win"])
    head = ms[0]
    others = [m for m in ms[1:] if m["k"] != head["k"]]
    facts = []
    if others:
        facts.append("也少见：" + "、".join(f"{sp(NAME.get(m['k'], m['k']))}{'' if m['n'] == 1 else '5 天'}{_fmt_move(m['k'], m['x'], m['n'])}" for m in others))
    mean = ""
    a = head.get("after")
    if a:
        word = "跌" if head["x"] < 0 else "涨"
        mean = f"过去 10 年同样大的单日{word}幅有 {a['n']} 次（相隔 5 天以内算一次），之后 20 个交易日 {a['up']} 次是涨的，中位数 {a['med']:+.1f}%。这是历史，不是预测。"
    return dict(kind="move", key=f"move:{name}", group=name, title=f"{name}：{_move_text(head, live)}", facts=facts, mean=mean,
                n10=round(head["n10"], 1), date=head["date"].strftime("%Y-%m-%d"), live=live, us=head["k"] in US)


def moves(D, t, t_other=None):
    """t：美股最近收盘日。t_other：非美股品种可以用到哪天（亚洲比美股早收盘，第二天下午就有新日线）；自检时等于 t。"""
    out = []
    for g, ks in GROUPS:
        ms = [m for k in ks for n in ((1, 5) if k in US else (1,)) for m in [_move_one(D, k, t if k in US or t_other is None else t_other, n)] if m]
        ms = [m for m in ms if m["date"] >= pd.Timestamp(t)]
        if ms:
            out.append(_move_group(g, ms))
    return out


# ---------------------------------------------------------------- 情绪阶段、读数、倒挂（第 2、3 条）
def _count_in(flag, t):
    f = flag[flag.index <= t].iloc[-WIN:]
    return int(f.sum())


def sentiment_items(R, t):
    out = []
    st = R["stage"][R["stage"].index <= t]
    if len(st) < 2:
        return out
    s, s0 = int(st.iloc[-1]), int(st.iloc[-2])
    F = R["F"][R["F"].index <= t]
    lines = {k: R[k][R[k].index <= t] for k in ("sell", "price", "pos", "credit")}
    cross = {k: first_in(L >= 90, 10) for k, L in lines.items()}
    crossed_today = [k for k in cross if bool(cross[k].iloc[-1])]
    d = st.index[-1].strftime("%Y-%m-%d")
    if s != s0:
        ent = (st == s) & (st.shift(1) != s)
        lit = {1: S1, 2: S2, 3: S3}.get(s, {})
        facts = [("今天到了历史上少见的：" + "、".join(nm for c, nm in lit.items() if F[c].iloc[-1] >= 90))] if lit and any(F[c].iloc[-1] >= 90 for c in lit) else []
        if crossed_today:
            facts.append("第一次到少见的读数：" + "、".join(LINE_NAMES[k] for k in crossed_today))
        title = f"情绪阶段：{'进入' + STAGE_NAMES[s] if s else '回到平稳'}（之前是{STAGE_NAMES[s0]}）"
        out.append(dict(kind="stage", key=f"stage:{s}", title=title, facts=facts, mean=STAGE_MEAN.get(s, ""), n10=_count_in(ent, t), date=d, live=False, us=True))
    else:
        for k in crossed_today:
            out.append(dict(kind="line", key=f"line:{k}", title=f"{LINE_NAMES[k].split('（')[0]}第一次到了历史上少见的程度（10 天里第一次）",
                            facts=[LINE_NAMES[k]], mean="阶段没变；单独一条读数到少见，不等于进了下一段。", n10=_count_in(cross[k], t), date=d, live=False, us=True))
    P = R["P"][R["P"].index <= t]
    t3 = (P.vix / P.vix3m).dropna()
    if len(t3) > 20:
        inv = t3 >= 1
        start = first_in(inv, 10)
        prev = inv.astype(float).shift(1)
        end = ~inv & (prev > 0) & (prev.rolling(3, min_periods=3).sum() >= 3)
        if bool(start.iloc[-1]):
            out.append(dict(kind="term", key="term:start", title=f"近月保险比远月贵了（VIX ÷ VIX3M = {t3.iloc[-1]:.2f}）",
                            facts=[f"1 个月的保险比 3 个月的贵，说明大家怕的就是眼前。前 10 天都没有这样。"], mean="倒挂常出现在急跌里；倒挂结束多半是恐慌在退。",
                            n10=_count_in(start, t), date=t3.index[-1].strftime("%Y-%m-%d"), live=False, us=True))
        if bool(end.iloc[-1]):
            out.append(dict(kind="term", key="term:end", title=f"近月保险不再比远月贵（倒挂结束，VIX ÷ VIX3M = {t3.iloc[-1]:.2f}）",
                            facts=["倒挂了至少 3 天以后第一次回到正常。"], mean="倒挂结束多半是眼前的恐慌在退。", n10=_count_in(end, t),
                            date=t3.index[-1].strftime("%Y-%m-%d"), live=False, us=True))
    return out


# ---------------------------------------------------------------- 趋势状态（第 4 条）
WORD = {1: "上行", -1: "下行", 0: "震荡"}


def _state(c, ma, slope_n):
    m = c.rolling(ma).mean()
    up, dn = (c > m) & (m > m.shift(slope_n)), (c < m) & (m < m.shift(slope_n))
    return pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=c.index).where(m.notna() & m.shift(slope_n).notna())


def _next_trading(d):
    d = d + timedelta(days=1)
    while not clock.is_trading_day(d):
        d += timedelta(days=1)
    return d


def _weekly(s, t):
    w = s[s.index <= t].resample("W-FRI").last().dropna()
    if len(w) and w.index[-1] > pd.Timestamp(t):
        w = w.iloc[:-1]
    return w


def _monthly(s, t):
    m = s[s.index <= t].resample("ME").last().dropna()
    if len(m) and _next_trading(pd.Timestamp(t).date()).month == pd.Timestamp(t).month:
        m = m[m.index < pd.Timestamp(t).to_period("M").start_time]
    return m


def _run(st):
    st = st.dropna()
    if not len(st):
        return None, 0
    v = st.iloc[-1]
    n = 0
    for x in reversed(st.values):
        if x != v:
            break
        n += 1
    return int(v), n


def trends(D, t):
    rows = []
    for k in TREND_ROWS:
        if k not in D:
            continue
        s = D[k]["c"]
        s = s[s.index <= t].dropna()
        if len(s) < 300:
            continue
        dS, wS, mS = _state(s, 20, 5), _state(_weekly(s, t), 10, 2), _state(_monthly(s, t), 10, 2)
        r = {"k": k, "name": NAME.get(k, k)}
        for p, S in (("d", dS), ("w", wS), ("m", mS)):
            v, n = _run(S)
            r[p], r[p + "n"] = (WORD.get(v), n) if v is not None else (None, 0)
        rows.append(r)
    return rows


def trend_items(D, t):
    out = []
    for k in TREND_ROWS:
        if k not in D:
            continue
        s = D[k]["c"]
        s = s[s.index <= t].dropna()
        if len(s) < 300:
            continue
        last = s.index[-1]
        if k in TREND_FOCUS:
            w = _weekly(s, t)
            S = _state(w, 10, 2).dropna()
            if len(S) >= 3 and w.index[-1].normalize() == last.normalize():       # 这一周就在 last 这天走完
                conf = (S == S.shift(1)) & (S.shift(1) != S.shift(2))
                if bool(conf.iloc[-1]):
                    out.append(dict(kind="trend", key=f"trend:w:{k}", title=f"{NAME[k]}周线从{WORD[int(S.iloc[-3])]}转成{WORD[int(S.iloc[-1])]}（已经连续 2 周）",
                                    facts=["周线：收盘和 10 周均线比，均线比 2 周前。只用走完的周。"], mean="", n10=int(conf.iloc[-520:].sum()),
                                    date=last.strftime("%Y-%m-%d"), live=False, us=k in US))
        if k not in MONTH_FOCUS:
            continue
        m = _monthly(s, t)
        S = _state(m, 10, 2).dropna()
        if len(S) >= 2 and len(m) and m.index[-1].to_period("M") == last.to_period("M"):
            ch = (S != S.shift(1)) & (S != 0)          # 只说转成上行 / 下行
            if bool(ch.iloc[-1]):
                out.append(dict(kind="trend", key=f"trend:m:{k}", title=f"{NAME.get(k, k)}月线从{WORD[int(S.iloc[-2])]}转成{WORD[int(S.iloc[-1])]}",
                                facts=["月线：收盘和 10 个月均线比，均线比 2 个月前。只用走完的月。"], mean="", n10=int(ch.iloc[-120:].sum()),
                                date=last.strftime("%Y-%m-%d"), live=False, us=k in US))
    return out


# ---------------------------------------------------------------- 关系断了（第 5 条）
def _wret(D, k, t):
    if k not in D:
        return None
    s = _weekly(D[k]["c"].dropna(), t)
    return (s.diff() * 100) if k in BP else np.log(s / s.shift(1))


def relation_items(D, t):
    out = []
    for a, b, nm in PAIRS:
        ra, rb = _wret(D, a, t), _wret(D, b, t)
        if ra is None or rb is None:
            continue
        X = pd.concat([ra, rb], axis=1).dropna()
        if len(X) < 120:
            continue
        lng, sht = X.iloc[:, 0].rolling(104).corr(X.iloc[:, 1]), X.iloc[:, 0].rolling(12).corr(X.iloc[:, 1])
        brk = (lng.abs() >= 0.3) & (sht.abs() >= 0.3) & (np.sign(lng) != np.sign(sht))
        first = first_in(brk, 8)
        if X.index[-1].normalize() != pd.Timestamp(t).normalize() or not bool(first.iloc[-1]):
            continue
        out.append(dict(kind="relation", key=f"rel:{a}:{b}", title=f"{nm}平常的关系断了",
                        facts=[f"过去两年周涨跌的相关是 {lng.iloc[-1]:+.2f}（{'一起动' if lng.iloc[-1] > 0 else '反着动'}），最近 12 周变成 {sht.iloc[-1]:+.2f}。"],
                        mean="平常一起动的东西突然反着走，常常是市场在换主线的早期迹象；也可能只是噪音，看接下来几周。", n10=int(first.iloc[-520:].sum()),
                        date=pd.Timestamp(t).strftime("%Y-%m-%d"), live=False, us=a in US))
    return out


# ---------------------------------------------------------------- 小盘先崩、保险比实际（第 6、7 条）
def small_first(D, R, t):
    idx = R["P"].index[R["P"].index <= t]
    U = pd.DataFrame({k: D[k]["c"] for k in SMALL if k in D}).reindex(idx)
    ma = U.rolling(20).mean()
    n20 = ma.notna().sum(1)
    lo20 = ((U <= U.rolling(20).min()) & U.rolling(20).min().notna()).sum(1) / n20.replace(0, np.nan) * 100
    nl = lo20.where(n20 >= 10).rolling(5).mean()
    p = pct(nl)
    cond = (p >= 90) & (R["sell"].reindex(idx) < 90)
    first = first_in(cond, 20)
    if not len(first) or not bool(first.iloc[-1]):
        return []
    lows = int(((U.iloc[-1] <= U.rolling(20).min().iloc[-1]) & U.rolling(20).min().iloc[-1].notna()).sum())
    return [dict(kind="small", key="small", title=f"小盘半导体先崩：{int(n20.iloc[-1])} 只里今天 {lows} 只创 20 天新低，大盘半导体还没跟上",
                 facts=["小盘和次新半导体创新低的比例到了历史上最恐慌的 10%，28 只大盘股那条还没到。"],
                 mean="研究里小盘创新低最多的那天，中位数在最低点前 17 天，大盘在前 9 天：小盘常常早一步。", n10=_count_in(first, t),
                 date=idx[-1].strftime("%Y-%m-%d"), live=False, us=True)]


def ivrv(D, R, t):
    P = R["P"][R["P"].index <= t]
    spx = D["^GSPC"]["c"].reindex(P.index) if "^GSPC" in D else None
    if spx is None:
        return []
    rv = np.log(spx).diff().rolling(21).std() * np.sqrt(252) * 100
    x = (P.vix / rv).replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) < MIN_WIN:
        return []
    def pct_win(s):
        return s.rolling(WIN, min_periods=MIN_WIN).apply(lambda w: (w <= w[-1]).mean(), raw=True)
    pw = pct_win(x)
    hi, lo = pw >= 1 - RARE, pw <= RARE
    out = []
    for flag, word, mean in ((hi, "贵", "保险价格远高于最近真实的波动：大家怕的比实际发生的多。"), (lo, "便宜", "最近真实的波动比保险定价的还大：要么是恐慌还没被定价，要么是急跌刚发生。")):
        first = first_in(flag, 20)
        if bool(first.iloc[-1]):
            out.append(dict(kind="ivrv", key=f"ivrv:{word}", title=f"大盘保险比实际波动{word}得少见：VIX {P.vix.iloc[-1]:.1f}，标普最近 21 天实际波动 {rv.iloc[-1]:.1f}",
                            facts=[f"VIX 是实际波动的 {x.iloc[-1]:.2f} 倍，过去 10 年两头各 2% 以内。"], mean=mean, n10=_count_in(first, t),
                            date=x.index[-1].strftime("%Y-%m-%d"), live=False, us=True))
    return out


# ---------------------------------------------------------------- 汇总
def close_items(D, R, t=None, t_other=None):
    t = pd.Timestamp(t if t is not None else R["P"].index[-1])
    items = sentiment_items(R, t) + moves(D, t, t_other) + trend_items(D, t) + relation_items(D, t) + small_first(D, R, t) + ivrv(D, R, t)
    return sorted(items, key=lambda x: (x["n10"], not x["us"]))


def live_items(D, intraday, t):
    """盘中版：报价的日期比这个品种最新日线晚，就用报价的涨跌对同一份历史。"""
    q = (intraday or {}).get("quotes") or {}
    out = []
    for g, ks in GROUPS:
        ms = []
        for k in ks:
            v = q.get(k) or {}
            if not v.get("p") or not v.get("pc") or k not in D:
                continue
            s = D[k]["c"].dropna()
            qd = pd.Timestamp(v["t"][:10]) if v.get("t") else None
            if qd is None or qd <= s.index[-1] or len(s) < MIN_WIN + 1:
                continue
            x = (v["p"] - v["pc"]) * 100 if k in BP else float(np.log(v["p"] / v["pc"]))
            if x == 0 or (k in UP_ONLY and x < 0):
                continue
            r = _ret(s, k, 1).dropna()
            kk, w = _rarity(r, x)
            if kk / w <= (RARE_US if k in US else RARE_LINKED):
                ms.append(dict(k=k, n=1, date=qd, x=x, cnt=kk, win=w, yrs=w / 252, n10=kk * WIN / w, after=_after(s, r, x, k), live=v.get("live")))
        if ms:
            it = _move_group(g, ms, live=True)
            it["state"] = "盘中" if any(m["live"] for m in ms) else "已收盘，日线还没更新"
            it["key"] += ":live"
            out.append(it)
    return sorted(out, key=lambda x: (x["n10"], not x["us"]))


def upcoming(cal, now=None):
    """接下来两个交易日的日历（美东日期）。"""
    now = now or datetime.now(timezone.utc)
    ny = now.astimezone(clock.NY)
    d = ny.date() if ny.hour < 16 else ny.date() + timedelta(days=1)
    days = []
    while len(days) < 2:
        if clock.is_trading_day(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    keep = set(days)
    ev = [e for e in (cal or {}).get("events", []) if e["date"] in keep]
    ev = [e for e in ev if e["kind"] != "earnings" or e.get("why") == "关注" or (e.get("cap") or 0) >= 1e12]
    return ev
