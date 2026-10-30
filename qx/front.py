"""前台五样（第四轮五样方案，2026-10-29；口径.md 十四.2、十四.3）。

整页按用户说的五样排：情绪 → 价格位置 → 买卖方结构和变化 → 预期 → 基本面。每样只放：
  一句结论（只用这一样自己登记过的读数，按固定句式写，不跨样合成，不打分，不用模型）、
  两三个常驻的数（市场自己的数，或者检验过的信号）、
  触发行（已登记的规则给出"少见"或"新的"结果时才出现；"新"= 和上一个交易日收盘的结果比，留到下一个交易日收盘）。
这里只挑已经算好的结果、按五样摆；规则、阈值、排序一条不动，推送照旧（推送读的是 export 里原来的那几份）。
其余照样算、照样推，进后台。
"""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from qx import clock, coverage as C

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


def _plain(s):
    """页面上的白话：登记表里的英文名换成中文（只改显示，登记表和推送不动）。"""
    return (s or "").replace("neocloud", "算力云")


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


# 美联储公布的议息会决议日（两天会的第二天，美东 14:00），来源 federalreserve.gov/monetarypolicy/fomccalendars.htm。
# 时间轴只存"今天起 6 个月"，截到以前的日子（自检、量页面）要靠这张表找"那天的下一次"；以后的场次由时间轴取到了并进来（fomc() 里合在一起）。
# 2025、2026 两年和美联储公布的日程一致；2027 年只留本机时间轴（data/timeline.json，10-26 取的）里对得上的两场，其余等时间轴取到再并进来，
# 不手写没核对过的日子（写错一场，"下一次"就会多出一场不存在的会）。2026-10-30 复查后改。
FOMC_DATES = ("2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
              "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
              "2027-01-27", "2027-03-17")
FED_HM = {"fomc": "14:00", "presser": "14:30"}        # 美联储日程上没写时刻时的默认（决议 14:00、记者会 14:30，美东）


def _next_trading(d):
    d = date.fromisoformat(d) + timedelta(days=1)
    while not clock.is_trading_day(d):
        d += timedelta(days=1)
    return d.isoformat()


def _pct(x):
    """概率 → 整数百分比，只在这里取整一次（页面原样写；2026-10-30 复查后改：原来先留 3 位、页面再取整，0.2745 → 0.275 → 28%）。
    逢 5 进，和 page/k.js 的 Math.round 一样（K 线点开那块"下次议息会"用 Math.round 算 data/fomc_history.csv 的同一个数）；
    Python 的 round() 逢 5 取偶，0.705 → 70、0.245 → 24，同一页同一场会写成两个数（2026-10-30 第二次复查后改）。"""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return int(math.floor(x * 100 + 0.5)) if np.isfinite(x) else None


def fomc(cal, t, hist=None, tl=None, now=None):
    """议息会下一次和下下次（口径十四.2"常驻的数"），按数据那天 t 算，不看墙上时钟（2026-10-30 改：原来用墙上时钟，截到以前的日子也写今天的下一次和今天的概率，日历里的场次过了就整行不见；日期是美东的，和时间轴的北京时间对不上）。
    "下一次" = 决议日（美东）在 t 以后：t 当天 14:00 的决议在收盘前已经出了。
    线上盘中例外（2026-10-30 复查后补）：t 还是前一个收盘、墙上时钟已经过了下一个交易日 14:00 的决议，那一场算开过。只在墙上时钟 now 还落在
    "t 可能是最新收盘"的那段里（到 t 之后第二个交易日收盘为止，留一天给晚到的日线）才看；截到以前的日子（预览、自检）照数据那天算。
    概率只用 t 那天能看到的那一份：日历（data/calendar.json）是 t 当天到下一个交易日之间取的才用；不然用 data/fomc_history.csv 里 t 以前最近的那一行（7 天以内，只是显示时取哪一行，不是规则）。
    都没有的写"这天没存"；日历那份：ok.polymarket 为假写"没取到或还没有盘口"（qx/events.py 是 ok["polymarket"] = bool(pm)，polymarket.fetch() 网络失败和
    两场都没对上盘口都返回 {}，分不开），取了、这一场没有写"预测市场还没有盘口"，不在要取的那两场里写"没存"。
    要取的那两场（asked）用并起来的 dates 算，events.fetch() 实际只按时间轴取；时间轴没取到美联储日程时两边可能对不上，"还没有盘口 / 没存"会分错（只是显示上哪个字）。
    日期给北京时间（决议在北京是第二天凌晨）；概率给整数百分比（_pct()，三项各自取整，加起来可能是 99 或 101）。
    hist、tl、now：预测市场存档的行、时间轴的事件、墙上时钟；不给就读 data/ 下的文件、取现在（自检用构造的传进来）。"""
    from qx import happen as HP, timeline as TL
    cal = cal or {}
    day = pd.Timestamp(t).strftime("%Y-%m-%d")
    hist = HP._rows(HP.FOMC) if hist is None else hist
    tl = TL.load().get("events", []) if tl is None else tl
    dates = set(FOMC_DATES) | {e["date"] for e in tl if e.get("kind") == "fomc"} \
        | {e["date"] for e in cal.get("events", []) if e.get("kind") == "fomc"} | set(cal.get("fomc_pm") or {}) | {r["meeting"] for r in hist}
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    live = now <= pd.Timestamp(f"{_next_trading(_next_trading(day))} 16:00", tz=clock.NY)
    done = lambda d: live and pd.Timestamp(f"{d} {FED_HM['fomc']}", tz=clock.NY) <= now
    nxt = sorted(d for d in dates if d > day and not done(d))[:2]
    snap, asof, src = None, None, None
    got = cal.get("fetched")
    if got and day <= pd.Timestamp(got).tz_convert(clock.NY).date().isoformat() <= _next_trading(day):
        snap = dict(cal.get("fomc_pm") or {})
        for e in cal.get("events", []):
            if e.get("kind") == "fomc" and e.get("pm"):
                snap.setdefault(e["date"], e["pm"])
        asof, src = day, "cal"
    else:
        ds = sorted({r["date"] for r in hist if r["date"] <= day})
        if ds and (pd.Timestamp(day) - pd.Timestamp(ds[-1])).days <= 7:
            asof, src = ds[-1], "hist"
            snap = {r["meeting"]: r for r in hist if r["date"] == asof}
    # 日历那份要取的场次（qx/events.py fetch()：日历窗口里的决议 + 时间轴从取数那天起的下一次和下下次）；整个没取到时 ok.polymarket 为假
    asked = set(sorted(d for d in dates if d >= (cal.get("from") or day))[:2]) | {e["date"] for e in cal.get("events", []) if e.get("kind") == "fomc"}
    failed = (cal.get("ok") or {}).get("polymarket") is False
    out = []
    for d in nxt:
        bj = pd.Timestamp(f"{d} {FED_HM['fomc']}", tz=clock.NY).tz_convert(clock.SH)
        x = dict(date=d, bj=bj.strftime("%Y-%m-%d"), bj_hm=bj.strftime("%H:%M"))
        p = (snap or {}).get(d)
        if p:
            x.update(hold=_pct(p.get("hold")), cut=_pct(p.get("cut")), hike=_pct(p.get("hike")), vol=_f(p.get("vol"), 0), stale=bool(p.get("stale")),
                     asof=asof if asof != day else None)
        elif src == "cal":
            # 日历那份：ok.polymarket 为假 → 没取到或还没有盘口；要取了、没有 → 还没有盘口；本来就不在要取的那几场里（比如盘中跳过已开完的那场以后的再下一次）→ 没存
            x.update(why="fail" if failed else "nomkt" if d in asked else "nosave")
        else:
            x.update(why="nosave")                    # 存档那份 10-29 以前只存下一次，没有 = 那天没存
        out.append(x)
    return out


def reaction(cards):
    T = ((cards or {}).get("replay") or {}).get("tally4") or {}
    if not T:
        return None
    qs = sorted(T)
    cur = qs[-1]
    share = lambda g: g["好消息不涨"] / g["家数"] * 100 if g.get("家数") else None
    past = [share(T[q]) for q in qs[:-1] if share(T[q]) is not None]
    g = T[cur]
    bm = [T[q]["超预期中位"] for q in qs[:-1] if T[q].get("超预期中位") is not None]
    return dict(q=cur, word=QUARTER_WORD.get(int(cur[-1]), cur), n=g.get("家数"), bad=g["好消息不涨"], good=g["坏消息不跌"], share=_f(share(g)),
                past_lo=_f(min(past)) if past else None, past_hi=_f(max(past)) if past else None, past_n=len(past),
                beat_n=g.get("超预期家数"), beat_med=g.get("超预期中位"), beat_lo=min(bm) if bm else None, beat_hi=max(bm) if bm else None, beat_past_n=len(bm))


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


def _fed_et(e):
    """美联储日程上一件事（决议、记者会、纪要……）的美东时刻；决议、记者会没写时刻的用 FED_HM 的默认。
    48 小时和"接下来 7 天"都用它，同一件事落在同一个北京日子（2026-10-30 复查后改：原来 48 小时没时刻的按美东日子放、写"时间未定"）。"""
    x = _et_time(e["date"], (e.get("time") or "").replace(" 美东", ""))
    return x if x is not None or e.get("kind") not in FED_HM else _et_time(e["date"], FED_HM[e["kind"]])


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
            x = _fed_et(e)
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
            nm = "、".join(short_name(e.get("name") or e.get("sym")) + (f"（期权：一半机会超过 ±{e['implied'][0]['move'] * 100:.1f}%）" if e.get("implied") else "") for e in er)
            txt.append(f"{nm} 财报")
        dt = date.fromisoformat(dd)
        out.setdefault(dd, dict(day=f"{dt.month}/{dt.day} 周{WEEK[dt.weekday()]}", items=[]))["items"].append(dict(at=lab, text="；".join(txt)))
    return list(out.values())


def h48_all(hap, cal):
    """"全部"里旧的 48 小时列表：和前台同一个 h48()，另加褐皮书——旧列表（today.upcoming，qx/watch.py upcoming()）一直列着它，
    前台那一行照口径三.8 不列（qx/happen.py 的日历块也不收）。两天里没有褐皮书时给 None，页面用前台那份。"""
    beige = [e for e in (cal or {}).get("events", []) if e.get("kind") == "beige"]
    if not beige:
        return None
    a, b = h48((hap or {}).get("calendar")), h48(list((hap or {}).get("calendar") or []) + beige)
    return b if b != a else None


def fed_bj(cal):
    """"全部"里"接下来 7 天"那张表的议息会（决议、记者会）换成北京时间，和前台议息会那一行、48 小时、时间轴同一个写法（只给页面用，只改显示）。
    → {"fomc|美东日期": {bj: 北京日期, hm: 北京时刻}}；日历（推送读的 today.upcoming）不动。"""
    out = {}
    for e in cal or []:
        if e.get("kind") not in FED_HM:
            continue
        b = _fed_et(e).tz_convert(clock.SH)
        out[f"{e['kind']}|{e['date']}"] = dict(bj=b.strftime("%Y-%m-%d"), hm=b.strftime("%H:%M"))
    return out


def cal_late(cal, t):
    """日历是哪天取的：晚于 t 的下一个交易日（截到以前的日子做预览、自检时）才给，页面在 48 小时那几行写明"日历是哪天取的"——
    以前的日历没存，截不回那天（只改显示）。线上每次运行都重取，给 None。"""
    got = (cal or {}).get("fetched")
    if not got:
        return None
    d = pd.Timestamp(got).tz_convert(clock.NY).date().isoformat()
    return d if d > _next_trading(pd.Timestamp(t).strftime("%Y-%m-%d")) else None


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


def tw_revenue(t):
    """台积电最近一个月的营收同比：只用 t 那天已经公布的（pub ≤ t；2026-10-30 改：原来不截，截到 07-30 也写 9 月营收）。
    读 qx/fundamentals.py 的 load_tw()，自检的 extras_cut 按同一列截。"""
    from qx import fundamentals as FU
    day = pd.Timestamp(t).strftime("%Y-%m-%d")
    rows = [r for r in FU.load_tw() if r["code"] == "2330" and (r.get("pub") or "")[:10] <= day]
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
    """10 年美债收益率：和"少见的涨跌"那条规则同一个序列（口径三.1；qx/watch.py 的 GROUPS"美元和美债"、_close() 读 D["^TNX"]，Yahoo 收盘），截至 t。
    2026-10-30 改：原来读 FRED DGS10（晚一天），和前瞻、配对读数、各市场里的 10 年美债（都是 ^TNX）一页两个数。"""
    from qx import smallsignal as SS
    s, _ = SS.series(D, "^TNX", t) if "^TNX" in D else (None, True)
    if s is None or len(s) < 21:
        return None
    return dict(now=_f(s.iloc[-1], 2), c20=_f((s.iloc[-1] - s.iloc[-21]) * 100, 0), date=s.index[-1].strftime("%Y-%m-%d"), src="Yahoo")


def opt_market(D):
    """期权块"大盘"那一行的数（只给页面用）：和 qx/options.py market() 同一个算法——过去 10 年（2,520 个交易日，含当天）里不高于当天的比例，
    页面写"10 年分位 N"，不写"偏高 / 少见"（方案第五节第 5 条；options.py 的 95 / 70 / 30 只决定那几个词，不进任何规则）。
    只取整一次，就在这里按页面写的位数取（VIX 一位，SKEW、VVIX、分位整数，9 天 ÷ 30 天写成整数百分比），页面原样写，和 market() 那句的数一样
    （2026-10-30 复查后改：原来留 4 位、页面再 toFixed(1)，VIX 收盘 19.450001 → 19.45 → 页面 19.4，同一页别处是 19.5）。"""
    def one(k, dp):
        s = D[k]["c"].dropna()
        return dict(now=_f(s.iloc[-1], dp), p=_f((s.iloc[-2520:] <= s.iloc[-1]).mean() * 100, 0))
    out = {k: one(sym, dp) for k, sym, dp in (("vix", "^VIX", 1), ("skew", "^SKEW", 0), ("vvix", "^VVIX", 0)) if sym in D and len(D[sym]["c"].dropna())}
    if "vix" in out and "^VIX9D" in D and len(D["^VIX9D"]["c"].dropna()):
        r = D["^VIX9D"]["c"].dropna().iloc[-1] / D["^VIX"]["c"].dropna().iloc[-1]
        out.update(r9=_f(r * 100, 0), r9_ge1=bool(r >= 1))          # "眼前几天有事"照 market() 用没取整的比
    return out or None


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
                trig[_pillar_of_signal(x)].append(dict(src="sig", key="sig:" + x["k"], title=f"{x['text']}（历史上 {x['frac'] * 100:.1f}% 的日子更极端）"))
        # 3) 推演链走到新的一环（第 2 环以后，口径十一）
        st_p = {c["id"]: c["step"] for c in sig_p.get("chains") or []}
        for c in sig.get("chains") or []:
            if c["step"] >= 2 and c["step"] > st_p.get(c["id"], 0):
                L = c["links"][c["step"] - 1]
                trig["fund"].append(dict(src="chain", key="chain:" + c["id"], title=_plain(f"推演链 · {c['name']}走到第 {c['step']} 环（共 {c['of']} 环）：{L['name']}（{L.get('lit') or ''} 亮）"
                                         + (f"；下一环看{c['next']['name']}" if c.get("next") else ""))))
    except Exception:
        pos_p = sig_p = None
    # 4) 配对读数升级（口径十：平常 → 偏高 / 少见，偏高 → 少见）
    try:
        rank = {"平常": 0, "偏高": 1, "少见": 2}
        RG = NR.registry_at(t)                        # 门槛写成数：偏高 = 同方向更极端的不到 high_pct，少见 = 不到 rare_pct（登记/narratives.toml）
        gate = {"偏高": RG["high_pct"], "少见": RG["rare_pct"]}
        prv = {p["id"]: p["level"] for b in NR.compute(D, tp)["baskets"] for p in b.get("pairs") or []}
        seen = set()
        for b in (radar.get("narr") or {}).get("baskets") or []:
            for p in b.get("pairs") or []:
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                if rank.get(p["level"], 0) > rank.get(prv.get(p["id"], "平常"), 0):
                    k = "fund" if p["id"].startswith("BAML") or p["id"] in ("^TNX", "HYG/IEF") else "price"
                    trig[k].append(dict(src="pair", key="pair:" + p["id"], title=f"{p['name']} 20 日变化到了历史最极端的 {gate[p['level']] * 100:g}% 以内（历史上 {p['frac'] * 100:.1f}% 的日子更极端，截至 {p['asof']}）"))
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
                    trig["flow"].append(dict(src="cftc_wk", key=f"cftc_wk:{r['name']}", title=f"CFTC {r['asof'][5:]} 那期：{r['name'].replace(' ÷ 总持仓', '')}一周{'升' if r['chg'] > 0 else '降'}了 {abs(r['chg']):.1f} 个百分点到 {r['value']}%（历史上 {r['wk_frac'] * 100:.1f}% 的周变化同方向更大）"))
    except Exception:
        pass
    # 7) 三种走向的信号先出现（口径十三，first 是最近一个收盘日）
    for S in ((radar.get("fwd") or {}).get("scenarios") or []):
        for w in S["ways"]:
            for i, x in enumerate(w["signals"]):
                if x.get("first") == t.strftime("%Y-%m-%d"):
                    trig["fund"].append(dict(src="scen", key=f"scen:{S['id']}:{w['id']}:{i}", title=f"三种走向 · {S['name']}：{w['name']}的信号先出现（{x['text']}）· 登记的假设，不是买卖建议"))
    # 8) 宏观公布值对预期（口径十四.10）：上一个交易日以后、到今天公布的，每个公布时刻一行，只在公布那天
    try:
        from qx import macro
        for x in macro.between(tp, t):
            trig["fund"].append(dict(src="macro", key=x["key"], title=x["title"], date=x["date"]))
    except Exception:
        pass
    return trig, tp.strftime("%Y-%m-%d")


def judge_line(today):
    """判断卡只在两种情况出一行（五样方案三）：错的条件第一次出现、要人看的事两个交易日内。"""
    return [dict(key=x["key"], title=x["title"], date=x.get("date")) for x in (today or {}).get("items") or [] if x.get("kind") == "judge" and (":w:" in x["key"] or ":e:" in x["key"])]


# ================================================================ 合起来
def build(D, R, radar, today, hap, ice, cal):
    t = R["P"].index[-1]
    from qx import positioning as PS, watch as W
    out = dict(asof=t.strftime("%Y-%m-%d"), min_obs=PS.MIN_OBS,          # 仓位读数至少几个观测才和历史比（页面写"攒到第几期"用）
               # "今天变了什么"里"少见"换成的门槛（qx/watch.py 的常量，页面不另写一份）：单日 / 5 日涨跌美股、美股以外，保险比实际波动两头，比的是过去几年
               rare=dict(us=W.RARE_US, linked=W.RARE_LINKED, ivrv=W.RARE, yrs=round(W.WIN / 252)))
    parts = [("emo", lambda: emotion(R)), ("pos", lambda: position(D, t)), ("ends", lambda: baskets_ends(radar.get("narr"))),
             ("flow", lambda: flows(D, t, radar.get("pos"))), ("m1", lambda: m1(D, t)), ("fomc", lambda: fomc(cal, t)),
             ("react", lambda: reaction(radar.get("cards"))), ("season", lambda: earnings_season(t)), ("tw", lambda: tw_revenue(t)),
             ("credit", lambda: credit(ice, radar.get("narr"))), ("y10", lambda: yield10(D, t)),
             ("judge", lambda: judge_line(today)), ("h48", lambda: h48((hap or {}).get("calendar"))),
             ("h48all", lambda: h48_all(hap, cal)), ("fed_bj", lambda: fed_bj((hap or {}).get("calendar"))), ("cal_late", lambda: cal_late(cal, t)),
             ("optmkt", lambda: opt_market(D))]
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
            if x["key"] == "old:y10_up":                  # 这条规则读 FRED DGS10（晚一天）；同一块的 10 年美债是 Yahoo ^TNX，写明来源和观测日，免得两个数对不上
                x = dict(x, title=x["title"] + f"（FRED DGS10，截至 {int(x['date'][5:7])}/{int(x['date'][8:])}）")
            out["trig"][x["pillar"]].append(dict(src="old", key=x["key"], title=x["title"], why=x["why"]))
    except Exception as e:
        out["old_err"] = type(e).__name__
    for c in out.get("cross200") or []:                   # 跌破 200 日线（旧终端 risk below200，能衡量风险）那天出一行
        out["trig"]["price"].append(dict(src="ma200", key="ma200:" + c["k"], title=f"{c['name']}收盘跌破 200 日线（{c['ma200']}）；在线下时，60 天内再跌一大段的比例历来高 7–8 个百分点（只说风险，不说方向）"))
    return out
