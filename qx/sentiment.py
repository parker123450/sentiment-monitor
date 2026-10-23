"""情绪模块：阶段（在卖 → 在怕 → 投降 → 在出清）、四条恐慌读数、信用、产业链分组、转折标签。

从 研究/情绪算法重算 的 核心.py、阶段.py、信用.py、样本.py 搬过来（2026-10-23）。口径不改，只改了 FRED 的时间对齐（见 fred_avail）；
搬完和研究版逐日对账：阶段、四条读数、回撤、信用 ETF 那条 8005 天完全一致（阶段只有 2002-01-24 一天因 FRED 对齐不同）。
新加的（转折标签、加速 / 减速、分型）定义写在 口径.md，先写定义再算，不按结果回头调。

所有计算只用当天以前的数据：分位只和当天以前的全部历史比（expanding），FRED 只用观测日早于当天的值，AAII 按"公布后一天才可用"对齐。
全局自检（截断重算必须和全量一致）在 qx/selftest.py。
"""
import numpy as np
import pandas as pd

from qx.registry import SEMIS, SMALL, AI, CREDIT_ETF

MIN_N = 250
START = "1995-01-01"


# ================================================================ 基础工具（研究 核心.py，原样）
def pct(s, min_n=MIN_N):
    x = s.replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) < min_n:
        return pd.Series(np.nan, index=s.index)
    return (x.expanding(min_periods=min_n).rank(pct=True) * 100).reindex(s.index)


def longvol(px):
    r = np.log(px).diff()
    return r.expanding(MIN_N).std() * np.sqrt(252)


def ddv(px):
    lv = longvol(px)
    dd = px / px.rolling(252, min_periods=60).max() - 1
    return dd / lv, dd, lv


def _chg(s, n, kind):
    return np.log(s / s.shift(n)) if kind == "ratio" else s - s.shift(n)


def attributes(sign, kind, s, idx):
    """六个属性（研究 核心.attributes）。分位都转成"恐惧方向"（100 = 最恐惧）。"""
    o = (lambda p: p) if sign >= 0 else (lambda p: 100 - p)
    s = s.reindex(idx)
    med60 = s.rolling(60, min_periods=40).median()
    rel = np.log(s / med60) if kind == "ratio" else s - med60
    sp5, sp20 = _chg(s, 5, kind), _chg(s, 20, kind)
    acc = sp5 - sp5.shift(5)
    A = {"lvl": o(pct(s)), "rel": o(pct(rel)), "spd5": o(pct(sp5)), "spd20": o(pct(sp20)), "acc": o(pct(acc))}
    return pd.DataFrame(A)


# ================================================================ 对齐成日表（研究 数据.py）
def _close(D, name, adj=False):
    f = D.get(name)
    if f is None:
        return pd.Series(dtype=float)
    s = (f["a"] if adj else f["c"]).astype(float)
    return s.where(s > 0).dropna()


def align_weekly(w, idx, lag_days):
    """周度数据：观测日 + lag_days 天之后的第一个交易日起才能用。"""
    w = w.copy()
    w.index = w.index + pd.Timedelta(days=lag_days)
    return w.reindex(idx.union(w.index)).sort_index().ffill().reindex(idx)


def fred_avail(s, idx):
    """FRED：交易日 t 只用观测日早于 t 的最后一个值（FRED 次一个工作日才公布）。
    研究版是"按观测平移一格"，债市休市、股市开门的日子（哥伦布日、退伍军人节）会多滞后一天，而且当天算的和事后重算不一样；
    正式版改成按日期，自检（截断重算）才能一致。8005 天里阶段只有 2002-01-24 一天不同（2026-10-23 对账）。"""
    s = s.dropna().sort_index()
    pos = np.searchsorted(s.index.values, idx.values, side="left") - 1
    return pd.Series(np.where(pos >= 0, s.values[np.clip(pos, 0, None)], np.nan), index=idx)


def panel(D, aaii):
    """D：{序列名: DataFrame(c, a, v, o, h, l)}（qx.store.load）；aaii：DataFrame(index=日期, bull, bear)。"""
    sox = _close(D, "^SOX")
    idx = sox.index[sox.index >= START]
    P = pd.DataFrame(index=idx)
    P["sox"] = sox.reindex(idx)
    for k, n in {"vix": "^VIX", "vxn": "^VXN", "vix3m": "^VIX3M"}.items():
        P[k] = _close(D, n).reindex(idx)
    for k, n in {"ief": "IEF", "spy": "SPY", "shy": "SHY"}.items():
        P[k] = _close(D, n, adj=True).reindex(idx)
    for k, n in {"baa": "BAA10Y", "aaa": "AAA10Y", "cp": "DCPF3M", "tb3": "DTB3"}.items():
        P[k] = fred_avail(D[n]["c"], idx) if n in D else np.nan
    P["pc_eq"] = _close(D, "PC_EQ").reindex(idx)
    P["smh_vol"] = D["SMH"]["v"].reindex(idx) if "SMH" in D else np.nan
    if aaii is not None and len(aaii):
        P[["aaii_bull", "aaii_bear"]] = align_weekly(aaii[["bull", "bear"]], idx, 1)
    else:
        P["aaii_bull"] = P["aaii_bear"] = np.nan
    U = pd.DataFrame({t: _close(D, t) for t in SEMIS if t in D}).reindex(idx)
    return P, U


# ================================================================ 特征（研究 核心.raw_features 里阶段和页面要用的那些）
FEATS = {  # id: (方向, 类型)
    "ret10": (-1, "diff"), "volspk": (1, "ratio"), "below20": (1, "diff"), "newlow": (1, "diff"),
    "vix": (1, "ratio"), "vxn": (1, "ratio"), "t3": (1, "ratio"), "aaii": (-1, "diff"), "pc10": (1, "ratio"), "baa20": (1, "diff"),
}


def raw_series(P, U):
    idx = P.index
    px = P.sox
    lvd = longvol(px.dropna()).reindex(idx) / np.sqrt(252)
    vol = P.smh_vol
    ma20 = U.rolling(20).mean()
    n20 = ma20.notna().sum(1)
    b20 = ((U < ma20) & ma20.notna()).sum(1) / n20.replace(0, np.nan) * 100
    lo20 = ((U <= U.rolling(20).min()) & U.rolling(20).min().notna()).sum(1) / n20.replace(0, np.nan) * 100
    return {
        "ret10": np.log(px / px.shift(10)) / (lvd * np.sqrt(10)),
        "volspk": vol.rolling(5).mean() / vol.rolling(50).mean(),
        "below20": b20.where(n20 >= 10),
        "newlow": lo20.where(n20 >= 10).rolling(5).mean(),
        "vix": P.vix, "vxn": P.vxn, "t3": P.vix / P.vix3m,
        "aaii": P.aaii_bull - P.aaii_bear,
        "pc10": P.pc_eq.rolling(10).mean(),
        "baa20": (P.baa - P.baa.shift(20)) * 100,
    }


def features(P, U):
    R = raw_series(P, U)
    out = {}
    for fid, (sign, kind) in FEATS.items():
        A = attributes(sign, kind, R[fid], P.index)
        for a in A:
            out[f"{fid}.{a}"] = A[a]
        out[f"{fid}.raw"] = R[fid].reindex(P.index)
    return pd.DataFrame(out, index=P.index)


# ================================================================ 阶段（研究 阶段.py，原样）
S1 = {"below20.lvl": "成分股跌破 20 日线", "volspk.lvl": "放量", "ret10.lvl": "10 日跌幅", "newlow.lvl": "成分股创新低"}
S2 = {"vix.rel": "大盘保险比平时贵", "vxn.rel": "科技股保险比平时贵", "t3.rel": "近月保险比远月贵", "aaii.spd5": "散户突然转空"}
S3 = {"pc10.rel": "大家抢买认沽", "baa20.rel": "信用利差走阔", "vix.lvl": "VIX 冲高"}
NAMES = ["平稳", "在卖", "在怕", "投降", "在出清"]


def lines(F):
    sell = F["newlow.lvl"]
    price = F["vxn.rel"].where(F["vxn.rel"].notna(), F["vix.rel"])
    pos = F[["pc10.rel", "aaii.spd5"]].max(axis=1)
    return sell, price, pos


def stage(F, P):
    """按顺序：一段下跌（回撤 ÷ 长期波动 ≤ −0.3）里，先亮'在卖'，之后亮'在怕'才算，再之后亮'投降'才算。
    价格回到回撤 > −0.3 就重新开始。显示已经走到的段里最近 10 天还亮着的最高那段；都不亮了 → 在出清（走到过在怕以后）。"""
    idx = P.index
    v, dd, lv = ddv(P.sox.dropna())
    v, dd = v.reindex(idx), dd.reindex(idx)
    on1 = pd.DataFrame({c: F[c] >= 90 for c in S1}).any(axis=1).values
    on2 = pd.DataFrame({c: F[c] >= 90 for c in S2}).any(axis=1).values
    on3 = pd.DataFrame({c: F[c] >= 90 for c in S3}).any(axis=1).values
    falling = (v <= -0.3).values
    st = np.zeros(len(idx), int)
    reached, last = 0, {}
    for i in range(len(idx)):
        if not falling[i]:
            reached, last = 0, {}
            st[i] = 0
            continue
        if on1[i] and reached < 1:
            reached = 1
        if on2[i] and reached >= 1 and reached < 2:
            reached = 2
        if on3[i] and reached >= 2:
            reached = 3
        for k, o in ((1, on1), (2, on2), (3, on3)):
            if o[i]:
                last[k] = i
        show = 0
        for k in (3, 2, 1):
            if k <= reached and i - last.get(k, -999) < 10:
                show = k
                break
        if show == 0 and reached >= 2:
            show = 4
        st[i] = show
    return pd.Series(st, index=idx), v, dd


# ================================================================ 信用（研究 信用.py，原样；信用 ETF 不算进投降，第 11 轮定）
def credit_readings(D, P):
    idx = P.index
    R = {}
    R["Baa 利差 20 日走阔"] = (P.baa - P.baa.shift(20)) * 100
    q = (P.baa - P.aaa) * 100
    R["低评级比高评级多要（Baa − Aaa）比平时"] = q - q.rolling(60, min_periods=40).median()
    lows = []
    for t, b in CREDIT_ETF.items():
        e = _close(D, t, adj=True).reindex(idx)
        base = P.shy if b == "SHY" else P.ief
        r20 = np.log((e / base) / (e / base).shift(20))
        lows.append((pct(r20) <= 10).where(r20.notna() & pct(r20).notna()))
    L = pd.concat(lows, axis=1)
    R["信用 ETF 跑输国债的比例"] = (L.sum(1) / L.notna().sum(1).replace(0, np.nan) * 100).where(L.notna().sum(1) >= 3)
    kre = _close(D, "KRE", adj=True).reindex(idx) / P.spy
    R["区域银行跑输标普（20 日）"] = -np.log(kre / kre.shift(20))
    cp = (P.cp - P.tb3) * 100
    R["商业票据比国库券多要（比平时）"] = cp - cp.rolling(60, min_periods=40).median()
    return pd.DataFrame(R)


# ================================================================ 全部算一遍
def compute(D, aaii):
    P, U = panel(D, aaii)
    F = features(P, U)
    st, v, dd = stage(F, P)
    sell, price, pos = lines(F)
    X = credit_readings(D, P)
    credit = pct(X["信用 ETF 跑输国债的比例"])
    credit = credit.where(credit.notna(), F["baa20.lvl"])
    lit = pd.DataFrame({k: (pct(X[k]) >= 90).where(pct(X[k]).notna()) for k in X})
    credit_n = lit.sum(1).where(lit.notna().sum(1) >= 4)
    return dict(P=P, U=U, F=F, stage=st, ddv=v, dd=dd, sell=sell, price=price, pos=pos, credit=credit, credit_n=credit_n, X=X)


# ================================================================ 2026-10-23 新加（定义在 口径.md 第二节，先写定义再算）
MOM_WORDS = ["持平", "在加速", "还在升，但在减速", "在回落"]


def momentum(L):
    """0 持平、1 在加速、2 还在升但在减速、3 在回落（口径.md 二.1）。"""
    spd = L - L.shift(5)
    acc = spd - spd.shift(5)
    m = pd.Series(np.where(spd >= 10, np.where(acc > 0, 1, 2), np.where(spd <= -10, 3, 0)), index=L.index).astype(float)
    return m.where(spd.notna() & (acc.notna() | (spd < 10)))


def regime(v, vix):
    """分型：0 不在下跌、1 宏观冲击型（这一段开始以来 VIX 到过 30）、2 板块自己跌型（口径.md 二.3）。同时给这一段以来 VIX 最高。"""
    falling = (v <= -0.3)
    ep = (falling != falling.shift()).cumsum().where(falling)
    vmax = vix.groupby(ep).cummax().where(falling)
    return pd.Series(np.where(falling, np.where(vmax >= 30, 1, 2), 0), index=v.index), vmax


def turns(P, U, st, v, sell, price, pos):
    """转折标签（口径.md 二.2）→ [(日期, 种类, 哪天才知道)]。种类：peak 恐慌高峰、ebb 恐慌退潮、retest 二次探底、lead 参与度先走。"""
    idx = P.index
    avg = pd.concat([sell, price, pos], axis=1).mean(axis=1)
    sox = P.sox
    out = []
    falling = (v <= -0.3).values
    i = 0
    n = len(idx)
    while i < n:
        if not falling[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and falling[j + 1]:
            j += 1
        seg = range(i, j + 1)
        t4 = next((k for k in seg if st.iloc[k] == 4), None)
        if t4 is not None:
            out.append((idx[t4], "ebb", idx[t4]))
            w = avg.iloc[i: t4 + 1]
            if w.notna().any():
                pk = int(np.nanargmax(w.values)) + i
                out.append((idx[pk], "peak", idx[t4]))
                pk_avg = avg.iloc[pk]
                low = sox.iloc[i: t4 + 1].min()
                for k in range(t4 + 1, j + 1):
                    low = min(low, sox.iloc[k])
                    if sox.iloc[k] <= low * 1.03 and np.isfinite(avg.iloc[k]) and avg.iloc[k] <= pk_avg - 20:
                        out.append((idx[k], "retest", idx[k]))
                        break
        i = j + 1
    ma50 = U.rolling(50).mean()
    n50 = ma50.notna().sum(1)
    p50 = (((U > ma50) & ma50.notna()).sum(1) / n50.replace(0, np.nan) * 100).where(n50 >= 10)
    near_hi = sox >= 0.97 * sox.rolling(252, min_periods=60).max()
    drop = p50 <= p50.rolling(60, min_periods=40).max() - 20
    cond = (near_hi & drop).values
    last = -999
    for k in range(n):
        if cond[k] and k - last > 20:
            out.append((idx[k], "lead", idx[k]))
            last = k
    return sorted(out)


def compute_all(D, aaii):
    R = compute(D, aaii)
    for k in ("sell", "price", "pos", "credit"):
        R["m_" + k] = momentum(R[k])
    R["regime"], R["vixmax"] = regime(R["ddv"], R["P"].vix)
    R["turns"] = turns(R["P"], R["U"], R["stage"], R["ddv"], R["sell"], R["price"], R["pos"])
    return R
