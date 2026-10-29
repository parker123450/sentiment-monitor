"""从旧终端（trading-terminal）原样搬过来的、已经有检验标签的几条规则（口径.md 十四.4，2026-10-29 用户说"按推荐做"）。

定义一字不改，标签跟着定义走（旧终端 研究结论.md）：
  ddv_deep   费城半导体离一年高点（按长期波动折算）进入自己历史最深的 10%          有历史支持（只对费城半导体检验过）
  crash      费城半导体 5 日涨跌（按长期波动折算）在最低的 2%，同时 VIX 5 日变化在最高的 2%   有迹象
  baa_top    Baa 利差 20 日变化进入最低的 10%（收窄最快，"贪"那一侧）             有迹象
  curve_up   期限利差 10 年 − 2 年 20 日变化进入最高的 10%                         有历史支持（对费城半导体）
  y10_up     10 年国债收益率 20 日变化进入最高的 10%                               有迹象（对费城半导体）
旧终端的口径：长期年化波动 = 252 日年化波动的扩张中位数（core/tools.px_features）；分位 = 当天以前全部历史里的位置（exp_pct，至少 250 个）；
FRED 序列晚一天才能用；"进入" = 今天在极端、昨天不在。前台只在"20 个交易日里第一次进入"那天出一行（显示规则，和口径三.6、三.7 同一个 20 天）。
"""
import numpy as np
import pandas as pd

MIN_N = 250
GAP = 20


def exp_pct(s, min_n=MIN_N):
    out = pd.Series(np.nan, index=s.index)
    x = s.dropna()
    if len(x) < min_n:
        return out
    out.loc[x.index] = x.expanding(min_periods=min_n).rank(pct=True) * 100
    return out


def old_lv(c):
    lr = np.log(c).diff()
    return (lr.rolling(252, min_periods=120).std() * np.sqrt(252)).expanding(min_periods=250).median()


def _close(D, k, t):
    if k not in D:
        return None
    s = D[k]["c"].dropna()
    return s[s.index <= t]


def _fred(D, k, t):
    """FRED：t 那天只能看到 t 以前的观测（口径第八节）。"""
    if k not in D:
        return None
    s = D[k]["c"].dropna()
    return s[s.index < t]


def _enter(on):
    on = on.astype(bool)
    return on & ~on.shift(1, fill_value=False)


def _first_in(enter, gap=GAP):
    """20 个交易日里第一次进入。"""
    out = pd.Series(False, index=enter.index)
    last = -10 ** 9
    for i, x in enumerate(enter.values):
        if x:
            if i - last > gap:
                out.iloc[i] = True
            last = i
    return out


def series(D, t):
    """→ {id: DataFrame(on, enter, first, pct, val)}，都截到 t。"""
    t = pd.Timestamp(t)
    out = {}
    c = _close(D, "^SOX", t)
    if c is not None and len(c) > 300:
        lv = old_lv(c)
        dd = c / c.rolling(252, min_periods=60).max() - 1
        ddv = dd / lv
        p = exp_pct(ddv)
        on = (p <= 10) & p.notna()
        out["ddv_deep"] = pd.DataFrame(dict(on=on, pct=p, val=ddv))
        z5 = np.log(c / c.shift(5)) / (lv / np.sqrt(252) * np.sqrt(5))
        v = _close(D, "^VIX", t)
        if v is not None:
            pz = exp_pct(z5)
            pv = exp_pct(np.log(v / v.shift(5))).reindex(c.index)
            on = (pz <= 2) & (pv >= 98) & pz.notna() & pv.notna()
            out["crash"] = pd.DataFrame(dict(on=on, pct=pz, val=z5))
    b = _fred(D, "BAA10Y", t)
    if b is not None and len(b) > 300:
        ch = (b - b.shift(20)) * 100
        p = exp_pct(ch)
        out["baa_top"] = pd.DataFrame(dict(on=(p <= 10) & p.notna(), pct=p, val=ch))
    y10, y2 = _fred(D, "DGS10", t), _fred(D, "DGS2", t)
    if y10 is not None and len(y10) > 300:
        ch = (y10 - y10.shift(20)) * 100
        p = exp_pct(ch)
        out["y10_up"] = pd.DataFrame(dict(on=(p >= 90) & p.notna(), pct=p, val=ch))
        if y2 is not None:
            cv = (y10 - y2.reindex(y10.index)) * 100
            ch = cv - cv.shift(20)
            p = exp_pct(ch)
            out["curve_up"] = pd.DataFrame(dict(on=(p >= 90) & p.notna(), pct=p, val=ch))
    for k, f in out.items():
        f["enter"] = _enter(f["on"])
        f["first"] = _first_in(f["enter"])
    return out


TEXT = {
    "ddv_deep": ("price", "费城半导体离一年高点（按长期波动折算）进入自己历史最深的 10%", "旧终端检验：有历史支持，之后 60 天比同样跌深的日子好（只对费城半导体检验过）"),
    "crash": ("emo", "费城半导体 5 日急跌（历史最快的 2%），同时 VIX 5 日急升（历史最快的 2%）", "旧终端检验：有迹象，恐惧跟上了价格，之后常比同样跌深的日子好"),
    "baa_top": ("emo", "Baa 信用利差 20 日收窄到历史最快的一成（贪的那一侧）", "旧终端检验：有迹象，之后常比同样位置的日子差"),
    "curve_up": ("expect", "期限利差（10 年 − 2 年）20 日变陡到历史最快的一成", "旧终端检验：有历史支持，对费城半导体之后 60 天"),
    "y10_up": ("fund", "10 年美债收益率 20 日升到历史最快的一成", "旧终端检验：有迹象，对费城半导体之后 60 天常更差"),
}


def today(D, t):
    """t 那天"20 个交易日里第一次进入"的 → [dict(pillar, key, title, why, date)]；另给费城半导体回撤的历史分位。"""
    t = pd.Timestamp(t)
    S = series(D, t)
    out = []
    for k, f in S.items():
        if len(f) and bool(f["first"].iloc[-1]):
            pl, title, why = TEXT[k]
            out.append(dict(pillar=pl, key="old:" + k, title=title, why=why, date=f.index[-1].strftime("%Y-%m-%d")))
    dp = S.get("ddv_deep")
    return out, (None if dp is None or pd.isna(dp["pct"].iloc[-1]) else round(float(dp["pct"].iloc[-1]), 1))
