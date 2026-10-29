"""前台五样（第四轮五样方案，2026-10-29；口径.md 十四.2、十四.3）。

整页按用户说的五样排：情绪 → 价格位置 → 买卖方结构和变化 → 预期 → 基本面。每样只放：
  一句结论（只用这一样自己登记过的读数，按固定句式写，不跨样合成，不打分，不用模型）、
  两三个常驻的数（市场自己的数，或者检验过的信号）、
  触发行（已登记的规则给出"少见"或"新的"结果时才出现；"新"= 和上一个交易日收盘的结果比，留到下一个交易日收盘）。
这里只挑已经算好的结果、按五样摆；规则、阈值、排序一条不动，推送照旧（推送读的是 export 里原来的那几份）。
其余照样算、照样推，进后台。
"""
import csv, os
from datetime import date, timedelta

import numpy as np
import pandas as pd

from qx import clock, coverage as C, store

PILLARS = [("emo", "情绪"), ("price", "价格位置"), ("flow", "买卖方结构和变化"), ("expect", "预期"), ("fund", "基本面")]
STAGE_NAME = {0: "平稳", 1: "在卖", 2: "在怕", 3: "投降", 4: "在出清"}
POS_MKTS = [("^SOX", "费城半导体"), ("^NDX", "纳指 100"), ("^GSPC", "标普 500"), ("^KS11", "KOSPI")]
QUARTER_WORD = {1: "1 月以来（四季报）", 2: "4 月以来（一季报）", 3: "7 月以来（二季报）", 4: "10 月以来（三季报）"}
HORIZON = 21          # 一个月期权幅度：21 个交易日（旧终端 modules/risk 的 M1，标签"能衡量幅度"）


def _f(x, dp=1):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(x) else round(x, dp)


def _prev_day(idx, t):
    before = idx[idx < t]
    return before[-1] if len(before) else None


# ================================================================ ① 情绪
def emotion(R):
    st, idx = R["stage"].dropna(), R["stage"].dropna().index
    t = idx[-1]
    s = int(st.iloc[-1])
    k = len(st) - 1
    while k > 0 and int(st.iloc[k - 1]) == s:
        k -= 1
    P, F = R["P"], R["F"]
    reg = R.get("regime")
    vix = P.vix.dropna()
    out = dict(asof=t.strftime("%Y-%m-%d"), stage=s, name=STAGE_NAME.get(s, ""), since=idx[k].strftime("%Y-%m-%d"), ndays=len(st) - k,
               changed=bool(len(st) > 1 and int(st.iloc[-2]) != s),
               regime=None if reg is None or pd.isna(reg.iloc[-1]) else int(reg.iloc[-1]), vixmax=_f(R["vixmax"].iloc[-1]) if "vixmax" in R else None,
               read={k_: _f(R[k_].iloc[-1], 0) for k_ in ("sell", "price", "pos", "credit")},
               vix=_f(vix.iloc[-1]), vix_pct=_f(F["vix.lvl"].iloc[-1], 0) if "vix.lvl" in F else None,
               t3=_f((P.vix / P.vix3m).dropna().iloc[-1], 2))
    return out


# ================================================================ ② 价格位置
def _old_lv(c):
    """旧终端 core/tools.px_features 的长期年化波动：252 日年化波动的扩张中位数（只用当天以前）。M1 的检验用的就是它，原样搬。"""
    lr = np.log(c).diff()
    return (lr.rolling(252, min_periods=120).std() * np.sqrt(252)).expanding(min_periods=250).median()


def position(D, t):
    rows, cross = [], []
    for k, nm in POS_MKTS:
        if k not in D:
            continue
        c = D[k]["c"].dropna()
        c = c[c.index <= pd.Timestamp.now().normalize()]
        if len(c) < 260:
            continue
        hi = c.rolling(252, min_periods=60).max()
        ma = c.rolling(200).mean()
        i_hi = c.iloc[-252:].idxmax()
        below = c < ma
        r = dict(k=k, name=nm, asof=c.index[-1].strftime("%Y-%m-%d"), close=_f(c.iloc[-1], 2), dd=_f((c.iloc[-1] / hi.iloc[-1] - 1) * 100),
                 hi=_f(c.loc[i_hi], 2), hi_date=i_hi.strftime("%Y-%m-%d"), ma200=_f(ma.iloc[-1], 2), d200=_f((c.iloc[-1] / ma.iloc[-1] - 1) * 100))
        if bool(below.iloc[-1]):
            j = len(below) - 1
            while j > 0 and bool(below.iloc[j - 1]):
                j -= 1
            r["below_since"], r["below_days"] = below.index[j].strftime("%Y-%m-%d"), len(below) - j
            if len(below) > 1 and not bool(below.iloc[-2]):
                cross.append(dict(k=k, name=nm, date=r["asof"], ma200=r["ma200"], close=r["close"]))
        rows.append(r)
    return rows, cross


def baskets_ends(narr):
    B = [b for b in (narr or {}).get("baskets") or [] if not b.get("control") and b.get("z") is not None]
    if not B:
        return None
    lo, hi = min(B, key=lambda b: b["z"]), max(B, key=lambda b: b["z"])
    top = lambda b: sorted(((b.get("names") or {}).get(m, m), z) for m, z in (b.get("members") or {}).items())
    return dict(lo=dict(name=lo["name"], z=lo["z"], members=sorted(top(lo), key=lambda x: x[1])[:4]),
                hi=dict(name=hi["name"], z=hi["z"], members=sorted(top(hi), key=lambda x: -x[1])[:4]), main=(narr or {}).get("main"))


# ================================================================ ③ 买卖方
def flows(D, t, pos):
    """CFTC "挤在哪边"：这一期对上一期（新挤进 / 退出、连挤了几期、挤着的这一期在加还是在减）。只用口径十一已登记的结果。"""
    from qx import positioning as PS
    if not pos:
        return None
    cf = [r for r in pos["readings"] if r["src"] == "CFTC" and r.get("crowd", True)]
    on = pos.get("tff_on")                                # 往期按本期用的同一个口径算（口径十四.6：版本换了不算市场变了）
    if not cf:
        return None
    asof = max(r["asof"] for r in cf)
    pub = max(r["pub"] for r in cf if r["asof"] == asof)[:10]
    word = {c["market"]: c["word"] for c in pos["crowd"]}
    hist = []                                             # 往前每一期的"挤在哪边"（按那一期能看到的那天算）
    d = date.fromisoformat(asof)
    for n in range(1, 31):
        dd = d - timedelta(days=7 * n)
        seen = PS.cftc_pub(dd)
        try:
            hist.append({c["market"]: c["word"] for c in PS.compute(D, pd.Timestamp(seen), tff=on)["crowd"]})
        except Exception:
            break
    prev = hist[0] if hist else {}
    hot = lambda w: w in ("挤在多头", "挤在空头")
    changed, still = [], []
    for mk, w in word.items():
        p = prev.get(mk)
        if hot(w) and not (p == w):
            changed.append(dict(market=mk, word=w, was=p))
        elif hot(p) and not hot(w):
            k = 0
            while k < len(hist) and hist[k].get(mk) == p:
                k += 1
            changed.append(dict(market=mk, word="不再" + p.replace("挤在", "挤在"), was=p, runs=k))
        elif hot(w):
            k = 1
            while k - 1 < len(hist) and hist[k - 1].get(mk) == w:
                k += 1
            still.append(dict(market=mk, word=w, runs=k))
    prev_rows = {r["name"]: r for r in PS.compute(D, pd.Timestamp(PS.cftc_pub(d - timedelta(days=7))), tff=on)["readings"] if r["src"] == "CFTC"} if hist else {}
    nums = []
    for r in cf:
        if r["market"] in {x["market"] for x in still + changed}:
            p = prev_rows.get(r["name"])
            nums.append(dict(market=r["market"], name=r["name"], lab=PS.TFF[r["code"]][0] + r["who"] if r.get("tff") else r["market"],
                             now=r["value"], prev=p["value"] if p else None, pos=_f(r["pos"], 2) if r["pos"] is not None else None))
    for x in still:
        ns = [n for n in nums if n["market"] == x["market"] and n["prev"] is not None]
        x["dir"] = None if not ns else ("加" if all((n["now"] - n["prev"]) * (1 if x["word"] == "挤在多头" else -1) > 0 for n in ns)
                                         else "减" if all((n["now"] - n["prev"]) * (1 if x["word"] == "挤在多头" else -1) < 0 for n in ns) else "有加有减")
    calm = sorted({mk for mk, w in word.items() if not hot(w) and w not in ("数据不够",) and mk not in {c["market"] for c in changed}})
    tff = [dict(code=r["code"], name={"13874A": "标普", "209742": "纳指"}[r["code"]], who=r["who"], now=r["value"], pos=_f(r["pos"], 2) if r["pos"] is not None else None, chg=r["chg"])
           for r in pos["readings"] if r.get("tff") and r["code"] in ("13874A", "209742")]       # 美股期指谁在场上（TFF，口径十四.6）：常驻
    return dict(asof=asof, pub=pub, changed=changed, still=still, nums=nums, calm=[dict(market=m, word=word[m]) for m in calm if m in ("美股", "美债", "美股波动")],
                tff=tff, tff_on=on, letf=pos.get("letf"))


# ================================================================ ④ 预期
def m1(D, t):
    """一个月期权幅度（旧终端 modules/risk M1，标签"能衡量幅度"，原样搬，口径十四.4）：标普用 VIX，纳指用 VXN，
    费城半导体用 VXN × 半导体比纳指的长期年化波动倍数（_old_lv）。幅度 = 隐含波动 × √(21/252)。只说幅度，不说方向。"""
    out = []
    for nm, px, iv, ref in (("费城半导体", "^SOX", "^VXN", "^NDX"), ("纳指 100", "^NDX", "^VXN", None), ("标普 500", "^GSPC", "^VIX", None)):
        if px not in D or iv not in D:
            continue
        c = D[px]["c"].dropna()
        c = c[c.index <= t]
        v = D[iv]["c"].dropna()
        v = v[v.index <= t]
        if not len(c) or not len(v):
            continue
        x = float(v.iloc[-1])
        if ref:
            if ref not in D:
                continue
            r = D[ref]["c"].dropna()
            ratio = _old_lv(c).iloc[-1] / _old_lv(r[r.index <= t]).iloc[-1]
            if not np.isfinite(ratio):
                continue
            x *= float(ratio)
        m = x / 100 * np.sqrt(HORIZON / 252)
        out.append(dict(name=nm, iv=_f(x), m=_f(m * 100), lo=_f(c.iloc[-1] * np.exp(-m), 0), hi=_f(c.iloc[-1] * np.exp(m), 0), close=_f(c.iloc[-1], 2)))
    return out


def fomc(cal):
    pm = dict((cal or {}).get("fomc_pm") or {})
    for e in (cal or {}).get("events", []):
        if e.get("kind") == "fomc" and e.get("pm"):
            pm.setdefault(e["date"], e["pm"])
    today = clock.ny_now().date().isoformat()
    xs = sorted((d, p) for d, p in pm.items() if d >= today)[:2]
    return [dict(date=d, hold=_f(p.get("hold"), 3), cut=_f(p.get("cut"), 3), hike=_f(p.get("hike"), 3), vol=_f(p.get("vol"), 0), stale=bool(p.get("stale"))) for d, p in xs]


def reaction(cards):
    T = ((cards or {}).get("replay") or {}).get("tally4") or {}
    if not T:
        return None
    qs = sorted(T)
    cur = qs[-1]
    share = lambda g: g["好消息不涨"] / g["家数"] * 100 if g.get("家数") else None
    past = [share(T[q]) for q in qs[:-1] if share(T[q]) is not None]
    g = T[cur]
    return dict(q=cur, word=QUARTER_WORD.get(int(cur[-1]), cur), n=g.get("家数"), bad=g["好消息不涨"], good=g["坏消息不跌"], share=_f(share(g)),
                past_lo=_f(min(past)) if past else None, past_hi=_f(max(past)) if past else None, past_n=len(past))


WEEK = "一二三四五六日"
SUFFIX = __import__("re").compile(r",?\s+(Inc\.?|Corp(oration)?\.?|Holdings?,? (Inc\.?|LLC|Ltd\.?|PLC)?|N\.V\.|plc|PLC|Ltd\.?|Limited|LLC|S\.A\.|AG|SE|Co\.?|Company)$")


def short_name(n):
    """公司名去掉 Inc. / Corporation / N.V. 这类后缀，不截断（五样方案第五节"一张名字表"）。"""
    n = (n or "").strip().rstrip(",")
    for _ in range(3):
        m = __import__("re").sub(r"\s+(and|&)$", "", SUFFIX.sub("", n).strip().rstrip(","))
        if m == n:
            break
        n = m
    return n


def _et_time(d, s):
    """"2:00 p.m." / "14:00" → 美东那天那一刻（带时区）。认不出返回 None。"""
    import re
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([ap])?\.?m?\.?", (s or "").lower())
    if not m:
        return None
    h, mi = int(m[1]), int(m[2])
    if m[3] == "p" and h < 12:
        h += 12
    if m[3] == "a" and h == 12:
        h = 0
    return pd.Timestamp(f"{d} {h:02d}:{mi:02d}", tz=clock.NY)


def h48(cal, now=None):
    """接下来两个美股交易日的日历，换成北京时间、按北京的日子合成几行（五样方案三；只改显示，名单照口径三.8）。"""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    ny = now.tz_convert(clock.NY)
    d = ny.date() if ny.hour < 16 else ny.date() + timedelta(days=1)
    days = []
    while len(days) < 2:
        if clock.is_trading_day(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    from qx import events as EV
    ev = [dict(e, name=EV.NAMES.get(e.get("sym")) or e.get("name")) for e in cal or [] if e["date"] in days and (e["kind"] != "earnings" or e.get("why") == "关注" or (e.get("cap") or 0) >= 1e12)]
    slots = {}
    for e in ev:
        when, label = None, None
        if e.get("utc"):
            when = pd.Timestamp(e["utc"]).tz_convert(clock.SH)
        elif e["kind"] in ("fomc", "presser", "minutes", "chair", "beige"):
            x = _et_time(e["date"], (e.get("time") or "").replace(" 美东", ""))
            when = x.tz_convert(clock.SH) if x is not None else None
        elif e["kind"] == "earnings":
            if e.get("time") == "盘前":
                when, label = pd.Timestamp(f"{e['date']} 08:00", tz=clock.NY).tz_convert(clock.SH), f"晚上（美东 {int(e['date'][8:])} 日盘前）"
            elif e.get("time") == "盘后":
                when = pd.Timestamp(f"{e['date']} 16:00", tz=clock.NY).tz_convert(clock.SH)
                label = when.strftime("%H:%M") + f" 后（美东 {int(e['date'][8:])} 日盘后）"
            else:
                label = f"时间未定（美东 {int(e['date'][8:])} 日）"
        elif e["kind"] == "opex":
            when, label = pd.Timestamp(f"{e['date']} 16:00", tz=clock.NY).tz_convert(clock.SH), "美股收盘时"
        if when is not None and when < now:
            continue                                  # 已经过去的不列
        day = (when.date() if when is not None else date.fromisoformat(e["date"]))
        key = (day.isoformat(), when.strftime("%H:%M") if when is not None else "99:99", label or (when.strftime("%H:%M") if when is not None else "时间未定"))
        slots.setdefault(key, []).append(e)
    out = {}
    for (dd, hm, lab), es in sorted(slots.items()):
        er = [e for e in es if e["kind"] == "earnings"]
        txt = []
        for e in es:
            if e["kind"] == "earnings":
                continue
            s = {"议息会（决议）": "议息会决议"}.get(e["title"], e["title"])
            if e.get("pm"):
                s += f"（不变 {round(e['pm']['hold'] * 100)}%、降息 {round(e['pm']['cut'] * 100)}%、加息 {round(e['pm']['hike'] * 100)}%"
                s += "；期权给 " + "、".join(f"{x['sym']} ±{x['move'] * 100:.1f}%" for x in e.get("implied") or []) + "）" if e.get("implied") else "）"
            txt.append(s)
        if er:
            nm = "、".join(short_name(e.get("name") or e.get("sym")) + (f"（期权 ±{e['implied'][0]['move'] * 100:.1f}%）" if e.get("implied") else "") for e in er)
            txt.append(f"{nm} 财报")
        dt = date.fromisoformat(dd)
        out.setdefault(dd, dict(day=f"{dt.month}/{dt.day} 周{WEEK[dt.weekday()]}", items=[]))["items"].append(dict(at=lab, text="；".join(txt)))
    return list(out.values())


# ================================================================ ⑤ 基本面
def earnings_season(t):
    from qx import earn
    t = pd.Timestamp(t)
    q = t.to_period("Q")
    rs = [r for r in earn.rows() if earn.in_sample(r) and r.get("seen") and pd.Timestamp(r["seen"]) <= t and pd.Timestamp(r["date"]).to_period("Q") == q]
    sp = [float(r["surprise"]) for r in rs if r.get("surprise") not in ("", None)]
    ai = [r for r in rs if r["sym"] in C.AI_SYMS]
    beat = lambda xs: sum(1 for r in xs if r.get("surprise") not in ("", None) and float(r["surprise"]) > 0)
    return dict(word=QUARTER_WORD.get(q.quarter, str(q)), n=len(rs), beat=beat(rs), med=_f(float(np.median(sp))) if sp else None,
                ai_n=len(ai), ai_beat=beat(ai))


def tw_revenue():
    p = os.path.join(store.HERE, "tw_revenue.csv")
    if not os.path.exists(p):
        return None
    rows = [r for r in csv.DictReader(open(p, encoding="utf-8")) if r["code"] == "2330"]
    if not rows:
        return None
    r = max(rows, key=lambda r: r["ym"])
    return dict(ym=r["ym"], pub=r["pub"], yoy=_f(r["yoy"]), ytd=_f(r["ytd_yoy"]))


def credit(ice, narr):
    """融资环境：分档利差（和规则同一个观测日）+ 配对读数 20 日变化（口径十）。"""
    pairs = {}
    for b in (narr or {}).get("baskets") or []:
        for p in b.get("pairs") or []:
            if p.get("bp") and p["id"].startswith("BAML"):
                pairs[p["id"]] = p
    rows = []
    for nm, v in (ice or {}).items():
        p = pairs.get(v.get("sid"))
        rows.append(dict(name={"B": "单 B", "CCC 及以下": "CCC"}.get(nm, nm), now=v["now"], date=v["date"], c5=v.get("c5"), lvl5=v.get("lvl5"), up5=v.get("up"),
                         c20=_f(p["chg"], 0) if p else None, lvl20=p.get("level") if p and p.get("level") != "平常" else None, f5=v.get("f5"), f20=p.get("frac") if p else None))
    return rows


def yield10(D, t):
    from qx import smallsignal as SS
    s, _ = SS.series(D, "DGS10", t) if "DGS10" in D else (None, True)
    if s is None or len(s) < 21:
        return None
    return dict(now=_f(s.iloc[-1], 2), c20=_f((s.iloc[-1] - s.iloc[-21]) * 100, 0), date=s.index[-1].strftime("%Y-%m-%d"))


# ================================================================ 触发行：今天（上一个交易日收盘以来）新的
def _pillar_of_signal(x):
    k, cls = x.get("k", ""), x.get("cls", "")
    if k.startswith("JGB") or cls in ("信用", "利率"):
        return "fund"
    if cls == "波动":
        return "emo"
    return "price"


def _pillar_of_item(x):
    kind = x.get("kind")
    if kind in ("stage", "line", "term", "small", "ivrv"):
        return "emo"
    if kind == "move":
        g = x.get("group", "")
        if g == "美股保险":
            return "emo"
        if g == "美元和美债" and "美债" in x.get("title", "").split("：")[-1][:8]:
            return "fund"
        return "price"
    if kind in ("trend", "relation"):
        return "price"
    if kind == "pm":
        return "expect"
    if kind == "gamma":
        return None                                   # 做市商 gamma 是简化模型，放后台（五样方案第八节第 5 条）
    return None


def triggers(D, t, radar, today, hap, R):
    from qx import smallsignal as SS, positioning as PS, narrative as NR, radar as RA
    trig = {k: [] for k, _ in PILLARS}
    t = pd.Timestamp(t)
    idx = D["^SOX"]["c"].dropna().index
    tp = _prev_day(idx, t)
    # 1) "今天变了什么"的条目（口径三）：条目本身就是已登记规则的结果，按读数归家；判断卡的不进五样
    for x in (today or {}).get("items") or []:
        if x.get("kind") == "judge":
            continue
        k = _pillar_of_item(x)
        if k:
            trig[k].append(dict(src="today", key=x["key"], title=x["title"], n10=x.get("n10"), date=x.get("date")))
    if tp is None:
        return trig, None
    sig, pos = radar.get("sig") or {}, radar.get("pos")
    # 2) 小信号新到"少见"（口径十一，前一个交易日还不是少见）
    try:
        pos_p = PS.compute(D, tp)
        sig_p = SS.compute(D, tp, pos_p)
        was = {x["k"] for x in sig_p.get("signals") or [] if x["level"] == "少见"}
        have = {x["key"] for v in trig.values() for x in v}
        for x in sig.get("signals") or []:
            if x["level"] == "少见" and x["k"] not in was:
                trig[_pillar_of_signal(x)].append(dict(src="sig", key="sig:" + x["k"], title=f"{x['text']}（少见，历史上 {x['frac'] * 100:.1f}% 的日子更极端）"))
        # 3) 推演链走到新的一环（第 2 环以后，口径十一）
        st_p = {c["id"]: c["step"] for c in sig_p.get("chains") or []}
        for c in sig.get("chains") or []:
            if c["step"] >= 2 and c["step"] > st_p.get(c["id"], 0):
                L = c["links"][c["step"] - 1]
                trig["fund"].append(dict(src="chain", key="chain:" + c["id"], title=f"推演链 · {c['name']}走到第 {c['step']} 环：{L['name']}（{L.get('lit') or ''} 亮）"
                                         + (f"；下一环看{c['next']['name']}" if c.get("next") else "")))
    except Exception:
        pos_p = sig_p = None
    # 4) 配对读数升级（口径十：平常 → 偏高 / 少见，偏高 → 少见）
    try:
        rank = {"平常": 0, "偏高": 1, "少见": 2}
        prv = {p["id"]: p["level"] for b in NR.compute(D, tp)["baskets"] for p in b.get("pairs") or []}
        seen = set()
        for b in (radar.get("narr") or {}).get("baskets") or []:
            for p in b.get("pairs") or []:
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                if rank.get(p["level"], 0) > rank.get(prv.get(p["id"], "平常"), 0):
                    k = "fund" if p["id"].startswith("BAML") or p["id"] in ("^TNX", "HYG/IEF") else "price"
                    trig[k].append(dict(src="pair", key="pair:" + p["id"], title=f"{p['name']} 20 日变化到了{p['level']}（历史上 {p['frac'] * 100:.1f}% 的日子更极端，截至 {p['asof']}）"))
    except Exception:
        pass
    # 5) 卡新满足（口径十二；第 1、3 类归买卖方，第 5 类归预期，第 6 类归价格；第 2、4 类放后台）
    try:
        now_c = (radar.get("cards") or {}).get("cards") or []
        prev_c = {c["key"] for c in RA.compute(D, tp, pos_p, sig_p, None)["cards"]} if pos_p is not None else set()
        home = {1: "flow", 3: "flow", 5: "expect", 6: "price"}
        for c in now_c:
            if c["cls"] in home and c["key"] not in prev_c:
                if c["cls"] == 3 and "开始出清" not in c["title"]:
                    continue                          # 第 3 类只在"开始出清"新出现时上前台（"拥挤"一年 224 天都挂着）
                trig[home[c["cls"]]].append(dict(src="card", key="card:" + c["key"], title=f"{c['cls_name']}：{c['title']}", why=c.get("why")))
    except Exception:
        pass
    # 6) CFTC 周变化少见（口径十四.6）：这一期刚看到（前一个交易日还看不到），只看进"挤在哪边"的读数
    try:
        if pos and pos_p is not None:
            had = {(r["name"], r["asof"]) for r in pos_p["readings"] if r["src"] == "CFTC"}
            for r in pos["readings"]:
                if r["src"] == "CFTC" and r.get("crowd", True) and r.get("wk") == "少见" and (r["name"], r["asof"]) not in had:
                    trig["flow"].append(dict(src="cftc_wk", key=f"cftc_wk:{r['name']}", title=f"CFTC {r['asof'][5:]} 那期：{r['name'].replace(' ÷ 总持仓', '')}一周{'升' if r['chg'] > 0 else '降'}了 {abs(r['chg']):.1f} 个百分点到 {r['value']}%（少见，历史上 {r['wk_frac'] * 100:.1f}% 的周变化同方向更大）"))
    except Exception:
        pass
    # 7) 三种走向的信号先出现（口径十三，first 是最近一个收盘日）
    for S in ((radar.get("fwd") or {}).get("scenarios") or []):
        for w in S["ways"]:
            for x in w["signals"]:
                if x.get("first") == t.strftime("%Y-%m-%d"):
                    trig["fund"].append(dict(src="scen", key=f"scen:{S['id']}:{w['id']}", title=f"三种走向 · {S['name']}：{w['name']}的信号先出现（{x['text']}）· 登记的假设，不是买卖建议"))
    return trig, tp.strftime("%Y-%m-%d")


def judge_line(today):
    """判断卡只在两种情况出一行（五样方案三）：错的条件第一次出现、要人看的事两个交易日内。"""
    return [dict(key=x["key"], title=x["title"]) for x in (today or {}).get("items") or [] if x.get("kind") == "judge" and (":w:" in x["key"] or ":e:" in x["key"])]


# ================================================================ 合起来
def build(D, R, radar, today, hap, ice, cal):
    t = R["P"].index[-1]
    out = dict(asof=t.strftime("%Y-%m-%d"))
    parts = [("emo", lambda: emotion(R)), ("pos", lambda: position(D, t)), ("ends", lambda: baskets_ends(radar.get("narr"))),
             ("flow", lambda: flows(D, t, radar.get("pos"))), ("m1", lambda: m1(D, t)), ("fomc", lambda: fomc(cal)),
             ("react", lambda: reaction(radar.get("cards"))), ("season", lambda: earnings_season(t)), ("tw", tw_revenue),
             ("credit", lambda: credit(ice, radar.get("narr"))), ("y10", lambda: yield10(D, t)),
             ("judge", lambda: judge_line(today)), ("h48", lambda: h48((hap or {}).get("calendar")))]
    for k, f in parts:
        try:
            out[k] = f()
        except Exception as e:
            out[k], out[k + "_err"] = None, type(e).__name__
    if out.get("pos"):
        out["pos"], out["cross200"] = out["pos"]
    try:
        out["trig"], out["since"] = triggers(D, t, radar, today, hap, R)
    except Exception as e:
        out["trig"], out["trig_err"] = {k: [] for k, _ in PILLARS}, type(e).__name__
    try:                                                  # 旧终端检验过的规则（qx/oldrules.py，口径十四.4）：20 个交易日里第一次进入那天出一行
        from qx import oldrules
        xs, out["ddv_pct"] = oldrules.today(D, t)
        for x in xs:
            out["trig"][x["pillar"]].append(dict(src="old", key=x["key"], title=x["title"], why=x["why"]))
    except Exception as e:
        out["old_err"] = type(e).__name__
    for c in out.get("cross200") or []:                   # 跌破 200 日线（旧终端 risk below200，能衡量风险）那天出一行
        out["trig"]["price"].append(dict(src="ma200", key="ma200:" + c["k"], title=f"{c['name']}收盘跌破 200 日线（{c['ma200']}）；在线下时，60 天内再跌一大段的比例历来高 7–8 个百分点（只说风险，不说方向）"))
    return out
