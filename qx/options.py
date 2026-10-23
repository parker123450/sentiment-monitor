"""期权助手（第 3 步，2026-10-23）。规则在 口径.md 第四节。

数字在 qx/cboe.py 从完整期权链算好（data/chains_latest.json 最新一份，data/options_history.csv 每天一行）；这里写成五个问题的白话：
保险贵不贵、更怕跌还是更想涨、大家押在哪个价位、做市商对冲会放大还是压住波动、定价了多大的涨跌。只描述，不说买卖。
"""
import csv, json, os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from qx import store, clock
from qx.registry import CHAIN_SYMBOLS, OPTIONS_FILE

RICH, CHEAP, INVERT = 1.2, 0.8, 1.0
PC_HI, PC_LO = 1.2, 0.6
MIN_HIST = 250
SHORT = {"SPY": "标普 SPY", "QQQ": "纳指 QQQ", "SMH": "半导体 SMH", "SOXX": "半导体 SOXX", "NVDA": "英伟达", "AVGO": "博通", "AMD": "AMD",
         "TSM": "台积电", "MU": "美光", "EWY": "韩国 EWY"}
FLIP_SYMS = ["SPY", "QQQ", "SMH"]
CHART_SYMS = {"SMH": "SMH", "NVDA": "NVDA", "MU": "MU", "TSM": "TSM"}
EXPLAIN = {
    "q1": "期权像保险：隐含波动是保险的价格，实际波动是最近真实晃了多少。隐含比实际高很多，说明大家愿意多花钱买保护；近月比远月还贵，说明怕的是眼前几周。",
    "q2": "同样离现价那么远，买跌的保护（认沽）通常比买涨的押注（认购）贵一点。贵得越多，越怕跌。当天认沽和认购的成交比，看的是今天大家在买哪边。",
    "q3": "持仓最多的行权价是大家押得最重的地方。上方大量认购常常像天花板，下方大量认沽像地板；临近到期，价格容易被持仓最多的价位吸过去（磁铁）。",
    "q4": "做市商卖期权给客户以后要对冲。正 gamma 时，涨了他们卖、跌了他们买，把波动压住；负 gamma 时，涨了要追着买、跌了要追着卖，把波动放大。翻转价是两种状态的分界。这里假设做市商持有客户卖的认购、卖出客户买的认沽，是近似。",
    "q5": "从期权价格倒推：到期前市场定价了多大的涨跌（上下各一倍），以及跌超 10%、涨超 10% 的概率。这是风险中性的定价，不是真实概率。",
}


def _hist():
    p = os.path.join(store.HERE, OPTIONS_FILE)
    if not os.path.exists(p):
        return pd.DataFrame()
    d = pd.read_csv(p)
    d["date"] = pd.to_datetime(d["date"])
    return d


def _latest():
    try:
        return json.load(open(os.path.join(store.HERE, "chains_latest.json"), encoding="utf-8"))
    except Exception:
        return {}


def _rv(D, sym, n=21):
    if sym not in D:
        return None
    c = D[sym]["c"].dropna()
    if len(c) < n + 1:
        return None
    return float(np.log(c).diff().iloc[-n:].std() * np.sqrt(252) * 100)


def _yi(x):
    return f"{x / 1e8:,.0f} 亿美元" if abs(x) >= 1e8 else f"{x / 1e4:,.0f} 万美元"


def _px(x):
    return f"{x:,.0f}" if x >= 100 else f"{x:,.1f}"


def _is_live(date_str, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(clock.NY)
    return date_str == now.date().isoformat() and (now.hour, now.minute) < (16, 15)


def answers(sym, m, H, D):
    """一个标的的五句白话（每句一个 dict：q 问题、a 一句话、warn 是否值得注意）。"""
    spot, iv = m.get("spot"), m.get("iv30")
    out = []
    rv = _rv(D, sym)
    h = H[H.symbol == sym] if len(H) else H
    n = h.date.nunique() if len(h) else 0
    rng = f"（期权链攒了 {n} 天，30 天保险这段时间最低 {h.iv30.min():.0f}%、最高 {h.iv30.max():.0f}%）" if n >= 2 and n < MIN_HIST else ""
    if iv and rv:
        r = iv / rv
        w = "贵" if r >= RICH else "便宜" if r <= CHEAP else "和实际差不多"
        t = m.get("term")
        tt = "；近月比 3 个月还贵（倒挂），怕的是眼前" if t and t >= INVERT else "；近月比 3 个月便宜，正常" if t else ""
        out.append(dict(q="保险贵不贵", a=f"30 天保险 {iv:.0f}%，最近一个月实际{'只' if iv > rv else ''}波动了 {rv:.0f}%：保险{w}（{r:.1f} 倍）{tt}。{rng}", warn=bool(t and t >= INVERT)))
    sk, pc = m.get("skew25"), m.get("pc_vol")
    if sk is not None and iv:
        rel = sk / iv * 100
        word = "今天买跌的多" if pc and pc >= PC_HI else "今天买涨的多" if pc and pc <= PC_LO else "今天两边差不多"
        out.append(dict(q="更怕跌还是更想涨", a=f"下跌保护比上涨押注贵 {rel:.0f}%；{word}（认沽成交是认购的 {pc:.1f} 倍）。" if pc else f"下跌保护比上涨押注贵 {rel:.0f}%。",
                        warn=bool(pc and pc >= PC_HI)))
    if m.get("cwall") or m.get("pwall"):
        parts = []
        if m.get("cwall"):
            parts.append(f"上方最大押注 {_px(m['cwall'])}（{m['cwall_oi']:,} 张认购，比现价高 {(m['cwall'] / spot - 1) * 100:.1f}%）")
        if m.get("pwall"):
            parts.append(f"下方最大押注 {_px(m['pwall'])}（{m['pwall_oi']:,} 张认沽，比现价低 {(1 - m['pwall'] / spot) * 100:.1f}%）")
        mg = f"；持仓最集中的价位（磁铁）是 {_px(m['magnet'])}" if m.get("magnet") else ""
        out.append(dict(q="大家押在哪个价位", a="；".join(parts) + mg + "。只算 45 天内到期的。", warn=False))
    if m.get("gex") is not None:
        g, f = m["gex"], m.get("flip")
        if g >= 0:
            a = f"做市商大概是正 gamma：涨了卖、跌了买，会压住波动。每涨跌 1%，对冲要反向买卖约 {_yi(abs(g))}。"
            if f and f < spot:
                a += f"跌破 {_px(f)} 附近（低 {(1 - f / spot) * 100:.1f}%）会翻成放大波动。"
        else:
            a = f"做市商大概是负 gamma：涨了追着买、跌了追着卖，会放大波动。每涨跌 1%，对冲要顺着买卖约 {_yi(abs(g))}。"
            if f and f > spot:
                a += f"涨回 {_px(f)} 以上（高 {(f / spot - 1) * 100:.1f}%）才会翻回压住波动。"
        out.append(dict(q="做市商对冲会放大还是压住波动", a=a, warn=g < 0))
    pr = m.get("prob") or {}
    if pr.get("sd") and spot:
        sd = pr["sd"]
        out.append(dict(q="定价了多大的涨跌", a=f"{pr['dte']} 天后上下各约 {sd * 100:.1f}%（{_px(spot * (1 - sd))} 到 {_px(spot * (1 + sd))}）；"
                                                f"跌超 10% 的定价概率 {pr['dn10'] * 100:.0f}%，涨超 10% {pr['up10'] * 100:.0f}%。", warn=False))
    return out


def market(D):
    """大盘期权的长历史读数（和过去 10 年比，写词不写分位）。"""
    def word(k, x):
        s = D[k]["c"].dropna().iloc[-2520:]
        p = (s <= x).mean() * 100
        return "10 年里少见地高" if p >= 95 else "偏高" if p >= 70 else "偏低" if p <= 30 else "平常"
    out = []
    if "^VIX" in D:
        v = D["^VIX"]["c"].dropna()
        out.append(f"VIX {v.iloc[-1]:.1f}（{word('^VIX', v.iloc[-1])}）")
        if "^VIX9D" in D:
            r = D["^VIX9D"]["c"].dropna().iloc[-1] / v.iloc[-1]
            out.append(f"9 天保险是 30 天的 {r * 100:.0f}%" + ("：眼前几天有事" if r >= 1 else ""))
    if "^SKEW" in D:
        x = D["^SKEW"]["c"].dropna().iloc[-1]
        out.append(f"SKEW {x:.0f}（买极端下跌保护的程度，{word('^SKEW', x)}）")
    if "^VVIX" in D:
        x = D["^VVIX"]["c"].dropna().iloc[-1]
        out.append(f"VVIX {x:.0f}（保险本身的波动，{word('^VVIX', x)}）")
    return "；".join(out) + "。"


def flips(H):
    """每个标的 gamma 由正转负 / 由负转正的日子（每天一行的期权链摘要；当天那行盘中会被覆盖）。"""
    out = {}
    if not len(H) or "gex" not in H:
        return out
    for sym, h in H.dropna(subset=["gex"]).groupby("symbol"):
        h = h.sort_values("date")
        sg = np.sign(h.gex.values)
        ev = [(h.date.iloc[i].strftime("%Y-%m-%d"), "转负" if sg[i] < 0 else "转正") for i in range(1, len(sg)) if sg[i] != sg[i - 1] and sg[i] != 0]
        out[sym] = ev
    return out


def watch_items(H, latest):
    """进"今天要知道的"：SPY、QQQ、SMH 的做市商 gamma 转向（口径.md 四）。"""
    out = []
    F = flips(H)
    for sym in FLIP_SYMS:
        ev = F.get(sym) or []
        m = latest.get(sym) or {}
        if not ev or ev[-1][0] != m.get("date"):
            continue
        d, w = ev[-1]
        live = _is_live(d)
        g, f = m.get("gex"), m.get("flip")
        fact = (f"现在每涨跌 1%，对冲要顺着买卖约 {_yi(abs(g))}" + (f"；涨回 {_px(f)} 以上才会翻回去" if f and g < 0 and f > m['spot'] else "")) if w == "转负" else \
               (f"现在每涨跌 1%，对冲要反向买卖约 {_yi(abs(g))}" + (f"；跌破 {_px(f)} 会再翻过去" if f and g > 0 and f < m['spot'] else ""))
        out.append(dict(kind="gamma", key=f"gamma:{sym}", group=sym, title=f"{SHORT[sym]}：做市商 gamma {w}（{'会放大波动' if w == '转负' else '会压住波动'}）",
                        facts=[fact + "。"], mean="负 gamma 时涨跌容易被对冲盘放大，正 gamma 时容易被压住。这是近似，真实持仓方向不知道。",
                        n10=None, hist="期权链从 10-19 起攒的", date=d, live=live, state="盘中" if live else "", us=True))
    return out


def block(D):
    H = _hist()
    L = _latest()
    rows = []
    for sym, _ in CHAIN_SYMBOLS:
        m = L.get(sym)
        if not m:
            continue
        rows.append(dict(sym=sym, name=SHORT.get(sym, sym), date=m.get("date"), live=_is_live(m.get("date") or ""), spot=m.get("spot"),
                         gex=m.get("gex"), sd=(m.get("prob") or {}).get("sd"), ans=answers(sym, m, H, D)))
    days = H.date.nunique() if len(H) else 0
    summ = []
    for r in rows:
        if r["sym"] in ("SPY", "SMH") and r["gex"] is not None:
            summ.append(f"{r['name']} {'负' if r['gex'] < 0 else '正'} gamma" + (f"、一个月定价 ±{r['sd'] * 100:.0f}%" if r["sd"] else ""))
    return dict(rows=rows, market=market(D), days=days, explain=EXPLAIN, summary="；".join(summ),
                chart={CHART_SYMS[s]: ev for s, ev in flips(H).items() if s in CHART_SYMS}, items=watch_items(H, L))
