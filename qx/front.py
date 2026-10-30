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


def nfp_add(cal7, now=None):
    """非农的后备（新3，口径十四.1 更正）："接下来 7 天"那张表（happen.calendar，按美东今天起 7 天）里纳斯达克漏了的非农，
    从 BLS 发布日表补（qx/events.py bls_nfp()；同一天已经有"美国非农就业"的不补）。估的（表管不到的月份）不进这里。
    只给页面用：推送读的 today.upcoming、happen.calendar 都不动。"""
    from datetime import datetime, timezone
    from qx import events as EV
    now = now or datetime.now(timezone.utc)
    d0 = now.astimezone(clock.NY).date()
    have = {(e["date"], e["title"]) for e in cal7 or []}
    return [e for e in EV.bls_nfp(d0.isoformat(), (d0 + timedelta(days=7)).isoformat()) if not e.get("est") and (e["date"], e["title"]) not in have]


def nfp_later(t, days=45):
    """"再往后"那一行（新4 画）用的非农：数据日以后 45 天里，BLS 表里的（真的）和表管不到的月份估的（est，写"约 M/D（估的）"）。只给页面用。"""
    from qx import events as EV
    t = pd.Timestamp(t)
    return EV.bls_nfp((t + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), (t + pd.Timedelta(days=days)).strftime("%Y-%m-%d"))


def tl_fix(radar, t):
    """时间轴给页面用的改正版（新3，口径十四.1 更正）。推送也读的 radar.fwd.timeline、前瞻六条线不动，页面换成这一份：
      - 纳斯达克宏观日历的事件差一天：data/timeline.json 是 10-29 改正以前的 qx/timeline.py 生成的（查 q 得到的是 q 前一天的事件，
        旧代码把它记成 q 那天），这一版的标志是链接里的日子和事件日子一样；这种往前挪一天（日子和北京时间都挪）。改正后的代码重新生成以后就没有要挪的了。
      - 纳斯达克漏了的非农，从 BLS 发布日表补（qx/events.py bls_nfp()，估的不进）。
      - 六条线"接下来的检验"里读宏观日历的那几条线（forward.NEXT_KIND 里有 macro 的）按改正后的事件重排。
    没有要改的给 None。→ dict(events, next={线: [...]}, moved=挪了几件, added=补了几件)"""
    from qx import events as EV, forward as FW, timeline as TL
    fw = (radar or {}).get("fwd") or {}
    ev = (fw.get("timeline") or {}).get("events") or []
    if not ev:
        return None
    out, moved = [], 0
    for e in ev:
        if e.get("src") == "纳斯达克宏观日历" and e.get("kind") == "macro" and str(e.get("url") or "").endswith("date=" + e["date"]):
            d = (date.fromisoformat(e["date"]) - timedelta(days=1)).isoformat()
            bj = e.get("bj") or ""
            bj = (date.fromisoformat(bj[:10]) - timedelta(days=1)).isoformat() + bj[10:] if len(bj) >= 10 else d
            e = dict(e, date=d, bj=bj)
            moved += 1
        out.append(e)
    tl = TL.load()
    lo, hi = tl.get("start") or min(e["date"] for e in ev), tl.get("end") or max(e["date"] for e in ev)
    have = {(e["date"], e["title"]) for e in out}
    add = [dict(date=e["date"], bj=pd.Timestamp(e["utc"]).tz_convert(clock.SH).strftime("%Y-%m-%d %H:%M"), kind="macro", title=e["title"], src=e["src"], url=e["url"])
           for e in EV.bls_nfp(lo, hi) if not e.get("est") and (e["date"], e["title"]) not in have]
    if not moved and not add:
        return None
    out = sorted(out + add, key=lambda e: e["date"])                     # 同一天里的先后照原来的（sorted 是稳定的）
    ts, te = pd.Timestamp(t).strftime("%Y-%m-%d"), (pd.Timestamp(t) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    soon = [e for e in out if ts <= e["date"] <= te]
    nxt = {}
    for L in fw.get("lines") or []:
        ks = FW.NEXT_KIND.get(L["id"], set())
        if "macro" in ks and L["id"] != "industry":
            n = [f"{e['bj']} {e['title']}" for e in soon if e["kind"] in ks][:6]
            if n != L.get("next"):
                nxt[L["id"]] = n
    return dict(events=out, next=nxt, moved=moved, added=len(add))


def opt_dates(opt, t):
    """期权链是哪天的、比数据日晚几个交易日（新3：做市商 gamma 和期权最大押注写明用的是哪天的期权链）。只给页面用。
    日子是 qx/options.py 每个代码那一行的 date（qx/cboe.py 存下的那天的链）。→ {代码: {date, lag}}；盘中现取的不给；
    链比数据日还晚（截到以前的日子预览时会这样）lag 给 None。"""
    t = pd.Timestamp(t).date()
    out = {}
    for r in (opt or {}).get("rows") or []:
        d = r.get("date")
        if not d or r.get("live"):
            continue
        c = date.fromisoformat(d)
        lag, x = 0, c
        while x < t:
            x += timedelta(days=1)
            lag += clock.is_trading_day(x)
        out[r["sym"]] = dict(date=d, lag=lag if c <= t else None)
    return out


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
def build(D, R, radar, today, hap, ice, cal, opt=None):
    t = R["P"].index[-1]
    try:                                                  # 非农后备（新3）：纳斯达克漏了的非农补进页面的 48 小时、"接下来 7 天"（推送读的那几份不动）
        hap_p = dict(hap or {}, calendar=sorted(list((hap or {}).get("calendar") or []) + nfp_add((hap or {}).get("calendar")),
                                                key=lambda e: (e["date"], e["kind"] != "fomc", e.get("time") or "", e.get("sym") or "")))
    except Exception:
        hap_p = hap
    from qx import positioning as PS, watch as W
    out = dict(asof=t.strftime("%Y-%m-%d"), min_obs=PS.MIN_OBS,          # 仓位读数至少几个观测才和历史比（页面写"攒到第几期"用）
               # "今天变了什么"里"少见"换成的门槛（qx/watch.py 的常量，页面不另写一份）：单日 / 5 日涨跌美股、美股以外，保险比实际波动两头，比的是过去几年
               rare=dict(us=W.RARE_US, linked=W.RARE_LINKED, ivrv=W.RARE, yrs=round(W.WIN / 252)))
    parts = [("emo", lambda: emotion(R)), ("pos", lambda: position(D, t)), ("ends", lambda: baskets_ends(radar.get("narr"))),
             ("flow", lambda: flows(D, t, radar.get("pos"))), ("m1", lambda: m1(D, t)), ("fomc", lambda: fomc(cal, t)),
             ("react", lambda: reaction(radar.get("cards"))), ("season", lambda: earnings_season(t)), ("tw", lambda: tw_revenue(t)),
             ("credit", lambda: credit(ice, radar.get("narr"))), ("y10", lambda: yield10(D, t)),
             ("judge", lambda: judge_line(today)), ("h48", lambda: h48((hap_p or {}).get("calendar"))),
             ("h48all", lambda: h48_all(hap_p, cal)), ("fed_bj", lambda: fed_bj((hap or {}).get("calendar"))), ("cal_late", lambda: cal_late(cal, t)),
             ("optmkt", lambda: opt_market(D)),
             ("cal_add", lambda: [e for e in (hap_p or {}).get("calendar") or [] if e.get("src") == "BLS 发布日表"]),
             ("nfp_later", lambda: nfp_later(t)), ("tlfix", lambda: tl_fix(radar, t)), ("optdate", lambda: opt_dates(opt, t))]
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


# ---------- 说明 / 状态（第四轮后台精简第 2 步，方案第四节）：两个点了才加载的视图。HTML 在这里写好，export.write_views 用页面同一把钥匙加密成 v/*.enc，
# k.js 点了才取回、解开、放进页面。只读已经算好的 data（推送读的那几份不动），一样不删：从页面搬过来的每一处都记进 MOVED（说明第一节的索引）。
import html as _html

_e = lambda s: _html.escape(str("" if s is None else s), quote=True)
_md = lambda s: f"{int(s[5:7])} 月 {int(s[8:10])} 日" if s and len(s) >= 10 else "—"

# 从页面移到这里的：（原来在哪，搬了什么，现在在哪）。"现在在哪"写视图和那一节的名字；原处只留一行指过来
MOVED = [
    ("① 情绪 · 全部，最下面的折叠", "四条恐慌读数是怎么算的（含三段、在加速 / 在减速、哪一型、转折标签、抛售和涨过头标签）", "说明 · 四条读数怎么算的"),
    ("① 情绪 · 全部，四条读数下面", "CNN 恐慌贪婪那一行（今天的数、一周前、一个月前）", "说明 · CNN 恐慌贪婪"),
    ("前台 K 线 · 图的全部", "\"怎么看\"那一段（含电脑上的操作）；原处留一句手机也通的说法", "说明 · K 线怎么看"),
    ("② 价格位置 · 全部，趋势状态表上面", "上行、下行、震荡怎么定（均线、持续多久）", "说明 · 趋势状态怎么定"),
    ("④ 预期 · 全部，期权块", "\"这五个问题是什么意思\"（保险贵不贵、更怕跌还是更想涨、押在哪个价位、做市商对冲、定价了多大的涨跌）", "说明 · 期权五个问题"),
    ("新闻和日历，表尾", "新闻从哪几家取、日历里期权幅度怎么算", "说明 · 新闻和日历"),
    ("页面最下面", "数据来源清单（只留来源名；绕路和没接的接口写在状态）", "说明 · 数据来源；状态 · 接口备注"),
    ("快讯，\"各条路的健康和延迟\"", "每条路多久前取到、延迟中位数、延迟怎么算、过去 30 天回补到哪", "状态 · 快讯各条路"),
    ("② 各市场，每行末尾", "\"缺：…\"（没取到的品种）", "状态 · 缺的品种和序列"),
    ("⑤ AI 账本", "写\"缺\"或\"没有免费可自动化的数\"的几行（含 SEC 接口要联系邮箱那一行）", "状态 · 缺的品种和序列"),
    ("⑤ AI 账本，每行的来源小字", "接口名\"财政部 Fiscal Data\"（页面上改写成\"美国财政部\"），和 TreasuryDirect 的 robots.txt 全挡、所以走这个接口那句", "状态 · 接口备注"),
    ("顶栏第一行（有路断了时）", "状态的生成时刻（北京时间），让位给\"N 条路断了 ›\"", "状态 · 最上面一行（页面生成于…）"),
    ("全部卡 · 回放清单末尾", "\"第 N 类：数据从……起攒，攒满一年才够回放\"", "状态 · 在攒什么、哪天能用"),
]
KEPT = [   # 方案第四节列了、这一步没搬的（理由），说明里一并写出来，免得以为丢了
    ("前台 K 线 · 图的全部", "标签说明（阶段、转折、抛售 / 涨过头、gamma、判断）", "留在图下：看图时要对着标签看"),
    ("④ 期权块", "\"期权链攒了几天\"那句", "留在块里；状态的\"在攒什么\"里也有一行"),
    ("各块", "定义句和版本注脚", "S3 / S5 改写各块时再搬（这一步各块的文字还没定）"),
]

SHUO_FOUR = """<p><b>抛售恐慌</b>：28 只半导体股里，最近 5 天平均每天有几只创 20 天新低，和历史比排第几。股票池扩大到 63 只（加小盘、次新）结论一样。历次大跌的最低点前后，费城半导体、纳指、标普 84% 到 100% 的次数都到了历史上最高的 10%，2015 年前后都成立。</p>
<p><b>定价恐慌</b>：科技股保险（VXN）比它自己最近 3 个月的平常水平贵多少。和"自己最近"比，不和 2001、2008 年比。</p>
<p><b>仓位恐慌</b>（美股期权和散户）：两样取较高的：股票期权里买跌和买涨的比例比平时高多少；散户看多减看空一周里掉了多少。</p>
<p><b>信用压力</b>：7 只信用 ETF（高收益债、贷款、堕落天使、投资级、新兴市场债）里，有几只 20 天跑输国债到了历史最差的 10%。历次底部亮 82% 到 90%，随机日子只有三成。</p>
<p><b>三段</b>：历次底部都是先在卖（成分股普跌、放量），再在怕（保险变贵、散户转空），最后投降（抢买保护、信用利差走阔、VIX 冲高）。按这个顺序算，价格回升就重新开始；某一段 10 天没再亮就退回去。半导体 21 次大跌全都到了"在怕"，19 次到了"投降"。进入"投降"不等于到底，只有约两成在 3 周内见底。阶段只有研究做的样本内核对，没有前瞻检验。</p>
<p><b>在加速 / 在减速</b>：每条读数 5 天里升了多少、比 5 天前升得快还是慢。研究里加速度最先到顶，所以"还在升，但在减速"多半在第一、二段之间，不是最后。</p>
<p><b>哪一型</b>：这一段下跌以来 VIX 到过 30，是<b>宏观冲击型</b>，大盘读数都会亮；没到过，是<b>板块自己跌型</b>（像 2026 年 7 月、10 月），大盘读数看不出来，要看"比自己最近"的读数和成分股。</p>
<p><b>转折标签</b>：<b>恐慌高峰</b> = 一段下跌里三条读数平均最高的那天（要等恐慌退了才标出来，是事后标的）；<b>恐慌退潮</b> = 怕过以后各项读数都退了的第一天；<b>二次探底</b> = 退潮以后价格回到这一段最低点 3% 以内，但恐慌比高峰低很多；<b>参与度先走</b> = 指数离一年高点不到 3%，站上 50 日线的成分股却比最近少了 20 个百分点以上（顶部历史上测不出来，只是描述）。</p>
<p><b>抛售</b>标签：成交量是 50 日均量 2 倍以上、当天跌 2% 以上、RSI 低于 40。<b>涨过头</b>标签：RSI 高于 75、价格比 50 日线高 15% 以上，只说明涨得急。所有读数只和当天以前的历史比。这是描述，不是买卖建议。</p>"""
SHUO_K = """<p><b>手机上</b>：点图上某一天，图下那一行就换成那天；左右拖动平移，两指缩放；图下的滑条也能左右移动。<b>电脑上</b>：鼠标移到某一天看那天，Ctrl＋滚轮缩放，方向键一天一天走，+ / − 缩放。</p>
<p>价格区最下面的色带是每天在哪一段（<b style="color:var(--s1i)">在卖</b> → <b style="color:var(--s2i)">在怕</b> → <b style="color:var(--s3i)">投降</b> → <b style="color:var(--s4i)">在出清</b>），空白是平稳。副图默认是<b>恐慌热度</b>：抛售、定价、仓位、信用四行，颜色越深越恐慌，最深的是历史上最恐慌的一成；"工具"里可以换副图、打开阶段标签、抛售 / 涨过头标签和别的均线。<b>gamma 转负</b>：按期权持仓估的做市商对冲会放大波动（简化模型）；<b>判断</b>：你提出判断的那天。可以自己画水平线和趋势线。</p>"""
SHUO_TREND = "<p>上行 = 收盘在均线上方、均线在升；下行反过来；其他是震荡。日线 20 日均线，周线 10 周，月线 10 个月；数字是这个状态持续了多久。</p>"
SHUO_NEWS = """<p>新闻只从路透、彭博、华尔街日报、金融时报、CNBC、日经亚洲、美联储、韩联社、CoinDesk 和华尔街见闻"重要"快讯里取。</p>
<p>日历里的期权幅度：财报是反应日（时间未定的是当天加下一天）的涨跌，拆掉了别的日子平常的波动，写一半机会超过多少；议息会是到期以前的总幅度，包含到期前的正常波动，偏大一点。</p>"""
SHUO_SRC = ("<p>Yahoo（行情、VIX、VXN、成分股、信用 ETF）、CBOE（认沽认购、期权链）、AAII 散户调查、FRED（信用利差、美债收益率）、CFTC 期货持仓、"
            "纳斯达克（财报、宏观日历）、美联储和日本央行日程、美国经济分析局、Polymarket、台湾证交所、美国财政部（美债拍卖结果）、"
            "日本财务省、TradingView 和谷歌新闻里的路透、CNBC、华尔街见闻、CNN 恐慌贪婪。云厂商资本开支还没接（见 状态）。</p>")
SHUO_API = ("<p>美债拍卖结果走财政部的 Fiscal Data 接口：TreasuryDirect 的 robots.txt 全挡，不绕。"
            "云厂商资本开支和自由现金流要走 SEC 的 XBRL 接口，要给联系邮箱（SEC_CONTACT）才接，没给以前 AI 账本那一行写\"缺\"。</p>")

# 关键词配错的新闻（方案第四节"状态"）：按词组挑"chip"不是芯片的标题，只列出来，词表不改（改词表要登记新版本，方案第七节）
# "chips in" 不算：标题里多半是真芯片（"Cools Its Chips in Saudi Arabia"）；人名只认"Chip 某某," / says / said / appoint 这几种写法
_MISKW = __import__("re").compile(r"\b(bargaining|poker|blue)[- ]chips?\b|\bchips? away\b|\bchocolate chip|\bChip [A-Z][a-z]+(,| says\b| said\b| appoints?\b)", __import__("re").I)


def ready_by(asof, have, need, per="bday"):
    """还要攒多少、大约哪天够：per="bday" 按交易日（周一到周五），"half" 按半个月一期（空头回补天数，纳斯达克每月两期）。
    只是按日历推的估计（不算节假日），页面写"约"。"""
    left = max(0, int(need) - int(have))
    t = pd.Timestamp(asof)
    if left == 0:
        return t.strftime("%Y-%m-%d")
    if per == "half":
        return (t + pd.Timedelta(days=round(left * 365.25 / 24))).strftime("%Y-%m")
    return (t + pd.offsets.BDay(left)).strftime("%Y-%m-%d")


def broken_routes(fl):
    """快讯里停了 / 没取到的路（顶栏"N 条路断了 ›"和状态页用同一个数）。"""
    return [h for h in ((fl or {}).get("health") or []) if not h.get("ok")]


def _stale(status, asof):
    """和页面顶部"数据提醒"同一个算法（k.js head()）：AAII 落后 9 天以上、其余 4 天以上算没更新。"""
    out = []
    for nm, v in (status or {}).items():
        if not v.get("last"):
            out.append(f"{nm}没有数据")
            continue
        lag = (pd.Timestamp(asof) - pd.Timestamp(v["last"])).days
        if lag > (9 if nm.startswith("AAII") else 4):
            out.append(f"{nm}最新只到 {_md(v['last'])}")
    return out


def accrue(data):
    """"在攒什么、哪天能用"：每行（什么，现在攒了多少 / 要多少，大约哪天够，说明）。只读已经算好的数。"""
    from qx import options as OP, positioning as PS
    asof, R = data.get("asof"), data.get("radar") or {}
    rows = []
    O = data.get("options") or {}
    if O.get("days") is not None and O["days"] < OP.MIN_HIST:
        rows.append(("期权链（和自己历史比）", f"{O['days']} 天 / {OP.MIN_HIST} 个交易日", "约 " + ready_by(asof, O["days"], OP.MIN_HIST), "攒满以前期权读数不叫\"少见\""))
    H = (R.get("narr") or {}).get("heat") or {}
    if H.get("note") and not H.get("rows"):
        m = __import__("re").search(r"从 (\d{4}-\d{2}-\d{2}) 起攒", H["note"])
        if m:
            from qx import news as NW
            got = len(NW.load()[1])        # 和 narrative.heat() 同一个数：存下条数的天数（heat 不按页面那天截，这里也不截）
            rows.append(("主题热度（新闻条数）", f"{got} / 10 天（从 {m.group(1)} 起）", "约 " + (pd.Timestamp(m.group(1)) + pd.Timedelta(days=9)).strftime("%Y-%m-%d"), "满 10 天才算"))
        else:
            rows.append(("主题热度（新闻条数）", H["note"], "—", "满 10 天才算"))
    by = {}
    for r in ((R.get("pos") or {}).get("readings") or []):
        if r.get("pos") is None and r.get("n") is not None and r["n"] <= PS.MIN_OBS:
            kind = "空头回补天数" if "空头回补" in r["name"] else r["name"]
            by.setdefault((kind, r["src"]), []).append(r)
    for (kind, src), xs in by.items():
        n = min(x["n"] for x in xs)
        half = kind == "空头回补天数"
        rows.append((f"{kind}（{src}，{len(xs)} 个）" if len(xs) > 1 else f"{kind}（{src}）", f"{n} {'期' if half else '天'} / 第 {PS.MIN_OBS + 1} {'期' if half else '天'}才和历史比",
                     "约 " + ready_by(asof, n, PS.MIN_OBS + 1, "half" if half else "bday"), "不够以前只写数，不说挤不挤"))
    from qx.radar import NAMES as CN
    for k, v in sorted(((R.get("cards") or {}).get("pending") or {}).items()):
        m = __import__("re").search(r"（(\d{4}-\d{2}-\d{2})）", v)
        rows.append((f"第 {k} 类卡的回放（{CN.get(int(k), '')}）", v, m.group(1) if m else "—", "回放以前卡上写\"还没有回放\""))
    fl = data.get("flash") or {}
    if fl and not fl.get("backfill_done"):
        rows.append(("快讯过去 30 天回补", "还没回补完", "—", "回补完以前\"第一次\"只标不推"))
    return rows


def _table(head, rows):
    return ("<table class=\"tbl\"><tr>" + "".join(f"<th>{_e(h)}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>")


def _sec(id_, title, body):
    return f"<h3 class=\"vh\" id=\"{id_}\">{_e(title)}</h3>{body}"


def view_shuo(data):
    h = "<p class=\"knote\">怎么算的、怎么看、数据从哪来。页面上只留一行指到这里；内容和原来一样，一样没删。</p>"
    h += _sec("s-moved", "从页面移到这里的", _table(["原来在哪", "搬了什么", "现在在哪"], [(_e(a), _e(b), _e(c)) for a, b, c in MOVED])
              + "<p class=\"knote\">方案里列了、这一步没搬的：" + "；".join(f"{_e(a)}的{_e(b)}：{_e(c)}" for a, b, c in KEPT) + "。</p>")
    h += _sec("s-four", "四条读数怎么算的", SHUO_FOUR)
    C = data.get("cnn")
    cnn = (f"<p>CNN 恐慌贪婪 {_e(C['now'])}，{_e(C['word'])}（{_md(C['date'])}"
           + (f"；一周前 {_e(C['w1'])}，一个月前 {_e(C['m1'] if C.get('m1') is not None else '—')}" if C.get("w1") is not None else "") + "）。</p>") if C else "<p>这次没有 CNN 的数。</p>"
    h += _sec("s-cnn", "CNN 恐慌贪婪", cnn + "<p>CNN 公布的合成指数，只作参考，不进阶段（口径二.4）。它用的都是大盘读数，板块自己跌的时候常常看不出来。</p>")
    h += _sec("s-k", "K 线怎么看", SHUO_K)
    h += _sec("s-trend", "趋势状态怎么定", SHUO_TREND)
    X = (data.get("options") or {}).get("explain") or {}
    Q = [("保险贵不贵", "q1"), ("更怕跌还是更想涨", "q2"), ("大家押在哪个价位", "q3"), ("做市商对冲会放大还是压住波动", "q4"), ("定价了多大的涨跌", "q5")]
    if X:
        h += _sec("s-opt", "期权五个问题", "<dl class=\"ox\">" + "".join(f"<dt>{q}</dt><dd>{_e(X.get(k, ''))}</dd>" for q, k in Q) + "</dl>")
    h += _sec("s-news", "新闻和日历", SHUO_NEWS)
    h += _sec("s-src", "数据来源", SHUO_SRC)
    return h


def view_zt(data):
    asof = data.get("asof")
    h = f"<p class=\"knote\">数据和各条路的状态：哪条路断了、哪些在攒、缺了什么。页面截至 {_md(asof)}，页面生成于北京时间 {_e(data.get('updated'))}。</p>"
    fl = data.get("flash") or {}
    bad = broken_routes(fl)
    warn = _stale(data.get("status"), asof)
    st = data.get("status") or {}
    h += _sec("z-src", "各数据源到哪天", (f"<p><b style=\"color:var(--alert)\">数据提醒：</b>{_e('；'.join(warn))}。相关读数沿用最近一次的。</p>" if warn else f"<p>{len(st)} 个数据源都没落后。</p>")
              + _table(["数据源", "最新到", "这次"], [(_e(k), _e(v.get("last") or "没有数据"), _e({"ok": "取到了", "local": "用存下的"}.get(v.get("status"), v.get("status")))) for k, v in st.items()]))
    if fl.get("health"):
        lag = lambda x: f"中位 {x['lag']['med']} 分钟（90% {x['lag']['p90']}，{x['lag']['n']} 条）" if x.get("lag") else "还没攒够"
        rows = [(_e(x["src"]) + (" · 经" + _e(x["via"]) if x.get("via") else "") + (f"<small>（{_e(x['sec'])} 栏目）</small>" if x.get("sec") else ""),
                 (f"<span class=\"bad\">" if not x.get("ok") else "<span>") + ("云端每 5 分钟取" if x.get("cloud") else ("—" if x.get("ago") is None else f"{x['ago']} 分钟前取到") if x.get("ok") else "停了 / 没取到") + "</span>",
                 lag(x)) for x in fl["health"]]
        h += _sec("z-flash", "快讯各条路", (f"<p><b style=\"color:var(--alert)\">{len(bad)} 条路断了：</b>{_e('、'.join(x['src'] + ('（' + x['sec'] + ' 栏目）' if x.get('sec') else '') for x in bad))}。</p>" if bad else "<p>各条路都通。</p>")
                  + _table(["路", "取到没有", "延迟"], rows)
                  + "<p class=\"knote\">延迟 = 我们看到的时间 − 发布时间，只算每条路开始取以后新出现的条目；云端每 15 分钟取一次，所以含最多 15 分钟的等待。"
                  + ("" if fl.get("backfill_done") else "过去 30 天还没回补完，\"第一次\"只标不推。") + "路透经 TradingView、谷歌新闻取，是你 10-27 定的。</p>")
    A = accrue(data)
    h += _sec("z-accrue", "在攒什么、哪天能用", _table(["什么", "攒了多少", "大约哪天够", "够以前"], [tuple(_e(c) for c in r) for r in A]) if A else "<p>没有在攒的。</p>")
    R = data.get("radar") or {}
    miss = [(_e("各市场 · " + m["cls"]), _e("、".join(m["miss"])), "没取到行情") for m in (R.get("mkts") or []) if m.get("miss")]
    miss += [(_e("AI 账本 · " + _plain(x.get("chain"))), _e(x["name"]), _e(x["value"]) + (f"<small>（{_e(x['src'])}）</small>" if x.get("src") and x["src"] != "—" else ""))
             for x in ((R.get("fwd") or {}).get("ledger") or []) if str(x.get("value", "")).startswith(("缺", "没有免费"))]
    h += _sec("z-miss", "缺的品种和序列", _table(["在哪", "缺什么", "为什么"], miss) if miss else "<p>这次没有缺的。</p>")
    h += _sec("z-api", "接口备注", SHUO_API)
    h += _sec("z-kw", "关键词可能配错的新闻", (_table(["哪天", "配进的话题", "标题"], mis) if (mis := miskw(data)) else "<p>这次没挑出来。</p>")
              + "<p class=\"knote\">扫新闻块和 K 线每天存下的新闻（这一页那天以前的），按词组挑（bargaining chip、blue chip、人名 Chip 这类，\"chip\" 不是芯片），可能漏。只列出来，词表没改：改词表要登记新版本。</p>")
    return h


def miskw(data):
    """关键词可能配错的新闻：扫 新闻块（要闻、各话题）和 K 线每天存下的新闻（happen.day.news，只看这一页那天以前的），同一个标题只列一次。"""
    asof = data.get("asof") or "9999"
    Hp = data.get("happen") or {}
    N = Hp.get("news") or {}
    seen, out = set(), []
    for g in [{"topic": "要闻", "items": N.get("top") or []}] + (N.get("more") or []):
        for n in g.get("items") or []:
            t = n.get("t") or ""
            if t not in seen and _MISKW.search(t):
                seen.add(t)
                out.append(("新闻块", _e(g.get("topic", "")), _e(t)))
    for d, xs in sorted(((Hp.get("day") or {}).get("news") or {}).items(), reverse=True):
        if d > asof:
            continue
        for x in xs:
            t = x[1] if len(x) > 1 else ""
            if t not in seen and _MISKW.search(t or ""):
                seen.add(t)
                out.append((_md(d), _e(x[0]), _e(t)))
    return out


def views(data):
    """说明、状态两个视图的 HTML（export.write_views 写成 v/shuo.enc、v/zt.enc）。"""
    return {"shuo": view_shuo(data), "zt": view_zt(data)}
