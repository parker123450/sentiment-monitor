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
TFF_SHORT = {"13874A": "标普", "209742": "纳指", "043602": "10 年美债", "042601": "2 年美债", "020601": "长期美债"}


def side_word(r):
    """一个读数在哪边，照口径十一的 10% 门槛写（新3）：位置在 10% 以外（positioning.side() 给的 side）写"在多头一侧 / 在空头一侧"，
    在中间的写离哪头近："偏多 / 偏空"。读数高是空头拥挤的（long_is_crowded=False）反过来。
    不写位置的数（新3 复查改正）：数在紧下面"美股期指谁在场上"那一行（page/k.js 用 Math.round 取整），这里再取一遍整会和那一行差 1（0.945 → 94 / 95），
    0.104 还会写成"偏空（10%，没过 10%）"。"""
    if r.get("side") in ("多头", "空头"):
        return f"在{r['side']}一侧"
    hi = r["pos"] >= 0.5
    return "偏多" if hi == bool(r.get("long_is_crowded", True)) else "偏空"


def mixed_why(rs, market):
    """"方向不一致"写出是哪个合约、谁在哪边（新3：③ 不写"多头挤在标普和美债"，照口径十一写）。只写 TFF 分开的合约（资管、杠杆基金两个读数）里
    有读数在 10% 以外的那几个，前面带市场名，例："美股（标普：资管在多头一侧，杠杆基金偏空）方向不一致"。
    新3 复查改正：原来那版带位置的数（"……（94%），杠杆基金偏空（11%，没过 10%），方向不一致"），和紧下面"美股期指谁在场上"那一行重复，
    400 宽多折一行，过不了"高度不能变高"；数只留在那一行。两个读数都在中间的合约（今天的纳指）不写，它不是"不一致"的来由。
    写不出就给 None，页面照旧写"方向不一致"。"""
    by = {}
    for r in rs:
        if r.get("tff") and r.get("pos") is not None and r.get("code") in TFF_SHORT:
            by.setdefault(r["code"], []).append(r)
    ps = [f"{TFF_SHORT[c]}：" + "，".join(f"{r['who']}{side_word(r)}" for r in xs) for c, xs in by.items()
          if any(r.get("side") in ("多头", "空头") for r in xs)]
    return f"{market}（{'；'.join(ps)}）方向不一致" if ps else None


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
    tff = [dict(code=r["code"], name={"13874A": "标普", "209742": "纳指"}[r["code"]], who=r["who"], now=r["value"], pos=_f(r["pos"], 2) if r["pos"] is not None else None, chg=r["chg"],
                side=r.get("side"))                                                       # side：10% 以外的"多头 / 空头"（positioning.side()，没取整的位置判的；新4 复查改正）
           for r in pos["readings"] if r.get("tff") and r["code"] in ("13874A", "209742")]       # 美股期指谁在场上（TFF，口径十四.6）：新4 起并进 ③ 点开"期货持仓"那一行
    crowd_rs = lambda mk: [r for r in pos["readings"] if r["market"] == mk and r.get("crowd", True)]
    # 新3 只改标普那一句（steps2 新3："页面和现在一样，只有三处错和 ③ 那句改了"）；美债照旧写"方向不一致"，要不要也写开等新4 排版时定
    why = lambda mk: mixed_why(crowd_rs(mk), mk) if mk == "美股" and word[mk] == "方向不一致" else None
    return dict(asof=asof, pub=pub, changed=changed, still=still, nums=nums,
                calm=[dict(market=m, word=word[m], **({"why": why(m)} if why(m) else {})) for m in calm if m in ("美股", "美债", "美股波动")],
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
    只给页面用：推送读的 today.upcoming、happen.calendar 都不动。
    7 天窗口和 happen.calendar_block() 用同一个钟（qx.happen 的 datetime），两边窗口一样；钉住 happen 的钟（推送闸那样）时这里一起钉住
    （新3 复查改正：原来用墙上时钟，钉住时两边窗口不一样，每次跑结果都不同）。"""
    from datetime import timezone
    from qx import events as EV, happen as HP
    now = now or HP.datetime.now(timezone.utc)
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
      - "排不到的"那一句跟着改（新3 复查改正）：挪过的，"只排到"的日子按挪后的最后一件纳斯达克宏观事件写；非农从 BLS 表补了的，
        从"美国 CPI、非农、韩国央行"里拿出来，另写"非农：用手抄的 BLS 发布日表排（表到 …）"——原来那句还写着非农只排到 11/11，和下面列到明年的非农对不上。
    没有要改的给 None。→ dict(events, next={线: [...]}, missing=[...], moved=挪了几件, added=补了几件)"""
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
    import re
    nfp_bls = any(str(e.get("src") or "").startswith("BLS 发布日表") for e in out)
    last_nq = max((e["date"] for e in out if e.get("src") == "纳斯达克宏观日历" and e.get("kind") == "macro"), default=None)
    miss = []
    for m in (fw.get("timeline") or {}).get("missing") or []:
        g = re.match(r"美国 CPI、非农、韩国央行：只排到 (\d{4}-\d{2}-\d{2})（(.*)）$", m)
        if g:
            d = last_nq if moved and last_nq else g.group(1)
            if nfp_bls:
                miss += [f"美国 CPI、韩国央行：只排到 {d}（{g.group(2)}）", f"非农：用手抄的 BLS 发布日表排（表到 {EV.bls_table()['dates'][-1]}）"]
                continue
            m = f"美国 CPI、非农、韩国央行：只排到 {d}（{g.group(2)}）"
        miss.append(m)
    return dict(events=out, next=nxt, missing=miss, moved=moved, added=len(add))


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
        return "flow"                                 # 做市商 gamma 转向：没有后台了，③ 点开第 2 行是做市商（plan 第三节第 3 小节；新4 复查改正，原来放后台）
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


# ================================================================ 新4：页面骨架用的几个新键（只给页面用；推送读的 today、radar 的卡片和 fwd、快讯一个字节不动）
# rows：五样各一行（名字、状态词、一句话、离下一步）；状态词先放现有的结论，新5 换成登记的状态词和颜色；离下一步先空。
# changes：今天变了什么（五样的触发行 + today 条目 + CFTC 三个变化 + 阶段变了 + 新卡），每条带 ①–⑤ 和推送编号，顺序照 today 原来的；
#          前几天说过的也在里面（old=那天），标成不画。
# next5 / later：接下来 5 个美股交易日（北京时间）和"再往后"一行，事件清单照口径三.8，估的日子不算（只在"再往后"写"约 M/D（估的）"）。
# mk：各市场每类（qx/markets.py rows()，18 类）今天动得最不寻常的那个（已有的倍数 z），类按这个倍数排。
# cards：机会和风险露前 3 张，"其余 N 张"露到 8 张，8 张以外照出、不画。
NO = {"emo": 1, "price": 2, "flow": 3, "expect": 4, "fund": 5}
NEXT_LABEL = {"fomc": "议息会决议", "presser": "主席发布会", "minutes": "议息会纪要", "boj": "日本央行利率决议", "bok": "韩国央行利率决议",
              "cpi": "CPI", "nfp": "非农", "pce": "PCE", "gdp": "GDP", "retail": "零售销售", "ism": "ISM", "opex": "月度期权到期"}
BIG_SYMS = {"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AVGO", "TSM"}      # "再往后"里两周以外的 1 万亿美元以上公司（时间轴不带市值；两周以内用日历的市值）
NAME_ADD = {"BRK.A": "伯克希尔"}                     # events.NAMES 只有 BRK.B；页面补一个（events.py 不动，推送读的那几份跟着它）
ISM_LAB = (("Non-Manufacturing|Services", "ISM 服务业"), ("Manufacturing", "ISM 制造业"))   # 日历的 note 写了是哪一份（纳斯达克原名）；时间轴没写的照旧"ISM"


def _mds(d):
    return f"{int(d[5:7])}/{int(d[8:10])}" if d and len(d) >= 10 else ""


def _sg(x, dp=1):
    if x is None:
        return "—"
    return ("+" if x > 0 else "−" if x < 0 else "") + (f"{abs(x):.{dp}f}" if dp else f"{abs(round(x)):,}")


# ================================================================ 新5：五样的状态词、颜色、离下一步、"如果……就……"（只给页面用；口径十四.12 的表）
# 门槛全是已登记的：阶段（口径一）、涨过头（二.2）、日线趋势（三.4）、200 日线（十四.2）、挤在哪边 10%（十一）、两个交易日的清单（三.8）、
# 信用分档 5 日走阔 5% / 1%（十一）。颜色：red 极端档、yellow、gray（十四.12）；每个颜色旁边都有字。sec 是用的口径节号（页面不显示，自测查得到）。
STAGE_ITEMS = {1: "在卖那四项", 2: "在怕那四项", 3: "投降那三项"}


def _pc(p):
    """位置（0–1）写成百分数；取整正好是 90 / 10 的多写一位（0.904 写 90.4%），免得"90%，回到 90% 以下"看着对不上。"""
    x = float(p) * 100
    s = f"{x:.0f}"
    return (f"{x:.1f}" if s in ("90", "10") else s) + "%"


def _tdays_after(d, n):
    """d 以后第 n 个美股交易日（n ≤ 0 就是 d 自己）。"""
    d = pd.Timestamp(d).date()
    while n > 0:
        d += timedelta(days=1)
        if clock.is_trading_day(d):
            n -= 1
    return d.isoformat()


def lights(R, t):
    """照 qx/sentiment.py stage() 的顺序重走一遍到 t（只用 t 以前的读数）：走到了哪一段、各段最近一次亮在哪天、t 那天显示哪一段。
    "离出清"按代码的 10 天窗口推（口径一：某一段 10 天没再亮就退回去）：已经走到的各段里最近一次亮的那天 + 10 个交易日，
    那天收盘起都不亮了——走到过"在怕"的是"在出清"，只到过"在卖"的回"平稳"。前提是这期间没有新的亮、价格没回到 −0.3 以上。
    显示的那一段要和 R["stage"] 一样才用（不一样页面就不写这个日子；自测也查）。"""
    from qx import sentiment as S
    t = pd.Timestamp(t)
    idx = R["P"].index[R["P"].index <= t]
    F = R["F"].reindex(idx)
    on = {k: pd.DataFrame({c: F[c] >= 90 for c in cols}).any(axis=1).values for k, cols in ((1, S.S1), (2, S.S2), (3, S.S3))}
    falling = (R["ddv"].reindex(idx) <= -0.3).values
    reached, last, show = 0, {}, 0
    for i in range(len(idx)):
        if not falling[i]:
            reached, last, show = 0, {}, 0
            continue
        if on[1][i] and reached < 1:
            reached = 1
        if on[2][i] and 1 <= reached < 2:
            reached = 2
        if on[3][i] and reached >= 2:
            reached = 3
        for k in (1, 2, 3):
            if on[k][i]:
                last[k] = i
        show = next((k for k in (3, 2, 1) if k <= reached and i - last.get(k, -999) < 10), 0)
        if show == 0 and reached >= 2:
            show = 4
    n = len(idx)
    out = dict(reached=reached, show=show, falling=bool(n and falling[-1]), last={k: idx[i].strftime("%Y-%m-%d") for k, i in last.items()})
    if show in (1, 2, 3):
        j = max(i for k, i in last.items() if k <= reached) + 10
        out["out_date"], out["out_to"] = _tdays_after(idx[-1], j - (n - 1)), (4 if reached >= 2 else 0)
    return out


def _st_emo(D, R, t):
    """① 阶段名（口径一）；半导体那天涨过头（二.2）另加一个黄色的"涨过头"。离下一步按现在在哪一段写下一段的门槛（都是最极端的 10%，收盘算）。"""
    from qx import sentiment as S, export as EX
    st = R["stage"]
    st = st[st.index <= t].dropna()
    s = int(st.iloc[-1])
    k = len(st) - 1
    while k > 0 and int(st.iloc[k - 1]) == s:
        k -= 1
    nd, changed = len(st) - k, bool(len(st) > 1 and int(st.iloc[-2]) != s)
    L = lights(R, t)
    ok = L["show"] == s
    F = R["F"]
    now = lambda cols: [_f(F[c].loc[:t].iloc[-1], 0) if c in F and len(F[c].loc[:t]) else None for c in cols]
    nums = lambda xs: " / ".join("—" if x is None else f"{x:g}" for x in xs)
    top = lambda xs: max([x for x in xs if x is not None], default=None)
    ddv = _f(R["ddv"].loc[:t].iloc[-1], 2)
    o = dict(word=STAGE_NAME.get(s, "") + (f" 第 {nd} 天" if s else ""), lv="red" if s in (1, 2, 3) else "yellow" if s == 4 or changed else "gray",
             sec=["一"] + (["三.2"] if changed else []), stage=s, ndays=nd, changed=changed, chips=[], ddv=ddv)
    c = D["^SOX"]["c"].dropna() if "^SOX" in D else None
    if c is not None:
        c = c[c.index <= t]
        rs, m50 = EX.rsi(c), c.rolling(50).mean()
        hot = (rs >= 75) & (c >= 1.15 * m50)
        if len(c) and bool(hot.iloc[-1]):
            o["chips"].append(dict(w="涨过头", lv="yellow", sec=["二.2"]))
        hd = hot[hot].index
        o["hot_last"] = hd[-1].strftime("%Y-%m-%d") if len(hd) else None
    ld = [x[0] for x in R.get("turns") or [] if x[1] == "lead" and x[2] <= t]
    o["lead_last"] = max(ld).strftime("%Y-%m-%d") if ld else None
    m = [R["m_" + k_].loc[:t].iloc[-1] if ("m_" + k_) in R and len(R["m_" + k_].loc[:t]) else np.nan for k_ in ("sell", "price", "pos", "credit")]
    o["ebb"] = int(sum(1 for x in m if x == 3))                     # 四条里几条"在回落"（口径二.1：5 日变化 ≤ −10）；四条的 20 日小线页面从 RAW.daily 取
    nxt = {0: 1, 1: 2, 2: 3, 4: 3}.get(s)
    if s == 3:
        if ok and L.get("out_date"):
            o["next"] = f"离出清：不再亮的话，最早 {_mds(L['out_date'])}（收盘算）"
            o["if"] = dict(t=f"如果到 {_mds(L['out_date'])} 收盘三段都没再亮，① 就从“投降”变成“在出清”", sec=["一"])
    elif s == 0 and not L["falling"]:
        o["next"] = f"离在卖：回撤 ÷ 长期波动 {ddv:.2f}，到 −0.3 以下（收盘算）" if ddv is not None else None
        o["if"] = dict(t="如果半导体回撤 ÷ 长期波动到 −0.3 以下、在卖那四项里有一项进最极端的 10%，① 就从“平稳”变成“在卖”", sec=["一"])
    elif s == 4:
        xs = now(S.S3)
        o["next"] = f"离投降：三项 {nums(xs)}，要到 90（收盘算）" if top(xs) is not None else None        # 当天收盘的分位（和规则同一个数）
        o["if"] = dict(t=f"如果半导体回撤 ÷ 长期波动回到 −0.3 以上（现在 {ddv:.2f}），① 就从“在出清”变成“平稳”" if ddv is not None else
                       "如果半导体回撤 ÷ 长期波动回到 −0.3 以上，① 就从“在出清”变成“平稳”", sec=["一"])
    else:
        cols = {1: S.S1, 2: S.S2, 3: S.S3}[nxt]
        xs = now(cols)
        lab = {1: "离在卖：四项", 2: "离在怕：四项", 3: "离投降：三项"}[nxt]
        o["next"] = f"{lab} {nums(xs)}，要到 90（收盘算）" if top(xs) is not None else None
        o["if"] = dict(t=f"如果收盘时{STAGE_ITEMS[nxt]}里有一项进最极端的 10%，① 就从“{STAGE_NAME[s]}”{'变成' if s == 0 else '进'}“{STAGE_NAME[nxt]}”", sec=["一"])
    if ok and s in (1, 2, 3) and L.get("out_date"):
        o["out"] = dict(date=L["out_date"], to=STAGE_NAME[L["out_to"]])
    o["ok"] = ok
    return o


def _st_price(D, t):
    """② 费城半导体：日线趋势（三.4：收盘和 20 日简单均线比、20 日线和 5 天前比）；收盘在 200 日线下写"200 日线下第 N 天"（十四.2）。"""
    from qx import watch as W
    c = D["^SOX"]["c"].dropna()
    c = c[c.index <= t]
    m20, ma = c.rolling(20).mean(), c.rolling(200).mean()
    v, n = W._run(W._state(c, 20, 5))
    trend = W.WORD.get(v) if v is not None else None
    below = c < ma
    o = dict(trend=trend, trend_n=n, close=_f(c.iloc[-1], 2), m20=_f(m20.iloc[-1], 2), m20_5=_f(m20.iloc[-6], 2) if len(m20) > 5 else None,
             ma200=_f(ma.iloc[-1], 2), d200=_f((c.iloc[-1] / ma.iloc[-1] - 1) * 100), chips=[])          # 20 日小线页面从 RAW.chart 的 SOX 取
    if bool(below.iloc[-1]):
        j = len(below) - 1
        while j > 0 and bool(below.iloc[j - 1]):
            j -= 1
        o.update(word=f"200 日线下第 {len(below) - j} 天", lv="red", sec=["十四.2"], below=len(below) - j)
        o["next"] = f"站回 200 日线 {ma.iloc[-1]:,.0f} 要 {_sg((ma.iloc[-1] / c.iloc[-1] - 1) * 100)}%（收盘算）"
        o["if"] = dict(t=f"如果半导体收盘站回 {ma.iloc[-1]:,.0f}（200 日线）以上，② 就不再是“200 日线下”，换回日线趋势", sec=["十四.2", "三.4"])
    else:
        o.update(word="日线" + trend if trend else "—", lv="yellow" if trend == "下行" else "gray", sec=["三.4"], below=0)          # 照样稿写"日线下行"
        o["next"] = f"离 200 日线 {ma.iloc[-1]:,.0f} 还有 {_sg((ma.iloc[-1] / c.iloc[-1] - 1) * 100)}%（收盘算）"
        o["if"] = dict(t=f"如果半导体收盘跌破 {ma.iloc[-1]:,.0f}（200 日线），② 就变成“200 日线下第 1 天”", sec=["十四.2"])
    return o


def _crowd_edge(r):
    """一个读数离"不在 10% 以外"还差多少：位置在 90% 以上的看离 90%，10% 以下的看离 10%（口径十一）。"""
    p = r["pos"]
    return (p - 0.9, "回到 90% 以下") if p >= 0.9 else (0.1 - p, "回到 10% 以上")


def _rlab(r):
    if r.get("tff") and r.get("code") in TFF_SHORT:
        return TFF_SHORT[r["code"]] + r.get("who", "")
    return r.get("market") or r.get("name")


def _st_flow(D, t, pos, F=None, since=None):
    """③ 挤在哪边（口径十一）：挤着的市场和连挤几期。红只在新一期 CFTC 刚看到的那个交易日、有市场新挤进或不再挤（和"今天变了什么"那一行同一个条件）；
    还挤着的黄；不挤、方向不一致灰。离不挤 = 挤着的市场里离 90% / 10% 最近的那个读数（同一个市场的读数要全在同一侧 10% 以外才算挤，一个回来就不算）。"""
    if F is None:
        F = flows(D, t, pos)
    if not F:
        return None
    hot = list(dict.fromkeys([x["market"] for x in F.get("still") or []] + [x["market"] for x in F.get("changed") or [] if not x.get("runs")]))
    word = "挤：" + "、".join(hot) if hot else "不挤"
    if since is None:
        idx = D["^SOX"]["c"].dropna().index
        p = _prev_day(idx, pd.Timestamp(t))
        since = p.strftime("%Y-%m-%d") if p is not None else None
    asof = pd.Timestamp(t).strftime("%Y-%m-%d")
    new = bool(F.get("changed") and since and F.get("pub") and since < F["pub"] <= asof)
    o = dict(word=word, lv="red" if new else "yellow" if hot else "gray", sec=["十一"] + (["十四.2"] if new else []), hot=hot, new=new, chips=[])
    rs = [r for r in (pos or {}).get("readings") or [] if r.get("crowd", True) and r.get("pos") is not None]
    if hot:
        cand = [(r, *_crowd_edge(r)) for r in rs if r["market"] in hot and r.get("side") in ("多头", "空头")]
        if cand:
            r, d, how = min(cand, key=lambda x: x[1])
            rest = [m for m in hot if m != r["market"]]
            per = "下一期" if r.get("src") in ("CFTC",) or r.get("tff") else ""
            o["next"] = f"离不挤：{_rlab(r)}位置 {_pc(r['pos'])}，{how}就不挤"
            o["if"] = dict(t=f"如果{per}{_rlab(r)}的位置{how}（现在 {_pc(r['pos'])}），③ 就从“{word}”变成“{'挤：' + '、'.join(rest) if rest else '不挤'}”", sec=["十一"])
    else:
        best = None
        for mk in dict.fromkeys(r["market"] for r in rs if r.get("src") == "CFTC" or r.get("tff")):
            xs = [r for r in rs if r["market"] == mk]
            for side in (True, False):                   # True：往"读数高 = 多头挤"那边（long_is_crowded 反过来的读数取另一头）
                need = []
                for r in xs:
                    hi = side == bool(r.get("long_is_crowded", True))
                    need.append((max(0.0, 0.9 - r["pos"]) if hi else max(0.0, r["pos"] - 0.1), r, hi))
                d, r, hi = max(need, key=lambda x: x[0])
                if best is None or d < best[0]:
                    best = (d, r, hi, mk, len(xs))
        if best:
            d, r, hi, mk, nx = best
            how = "到 90% 以上" if hi else "到 10% 以下"
            o["next"] = f"离挤：{_rlab(r)}位置 {_pc(r['pos'])}，{how}才算" + ("" if nx == 1 else f"（{mk}几个读数要都过）")
            o["if"] = dict(t=f"如果下一期{_rlab(r)}的位置{how}（现在 {_pc(r['pos'])}）" + ("" if nx == 1 else f"、{mk}别的读数也在同一边") + f"，③ 就变成“挤：{mk}”", sec=["十一"])
    return o


EV_SHORT = {"日本央行利率决议": "日本央行", "韩国央行利率决议": "韩国央行", "议息会决议": "议息会", "月度期权到期": "期权到期"}   # ④ 状态词里的事件名写短


def _cat(a, b):
    """中文接在英文名后面空一格（"Celestica 财报"），中文名不空（"亚马逊财报"）。"""
    return f"{a} {b}" if a and a[-1].isascii() and a[-1].isalnum() else f"{a}{b}"


def _evword(rows):
    """几天的事合成状态词里的一串（照样稿"明后天：日本央行、ISM"，手机一行放得下）：有宏观和央行写短名，最多两件，后面还有事（别的宏观或财报）就加"等"；
    只有财报时写财报（一家写"X 财报"，几家写最大的那家"X 等 N 家财报"）。全部的事在"接下来 5 个交易日"里。"""
    ev = list(dict.fromkeys(e for r in rows for e in r.get("ev") or []))
    er = list(dict.fromkeys(e for r in rows for e in r.get("er") or []))
    if ev:
        return "、".join(ev[:2]) + ("等" if len(ev) > 2 or er else "")
    if er:
        return _cat(er[0], "财报") if len(er) == 1 else _cat(er[0], f"等 {len(er)} 家财报")
    return ""


def _st_expect(next5, later_ev):
    """④ 两个交易日的清单（三.8，估的日子不算；和"接下来 5 个交易日"那一块同一份）：有事写"明后天：事件名"，没有写"下一件：日期 事件"。
    "如果……就……"只写日历不变时下一个收盘后状态词变成什么（十四.12："就"后面只写状态怎么变）。"""
    if not next5:
        return None
    has = lambda r: bool(r.get("ev") or r.get("er"))

    def word(rows, rest, later):
        w = _evword(rows)
        if w:
            return "明后天：" + w, "yellow"
        nx = next((r for r in rest if has(r)), None)
        if nx:
            return f"下一件：{nx['md']} {_evword([nx])}", "gray"
        return (f"下一件：{later[0]} {later[1]}", "gray") if later else ("两个交易日内没事", "gray")
    w, lv = word(next5[:2], next5[2:], later_ev)
    o = dict(word=w, lv=lv, sec=["三.8"], chips=[])
    nx = next(((i, r) for i, r in enumerate(next5) if i >= 2 and has(r)), None)
    if lv == "yellow":
        o["next"] = f"再下一件：{nx[1]['md']} {_evword([nx[1]])}（北京时间）" if nx else (f"再下一件：{later_ev[0]} {later_ev[1]}（北京时间）" if later_ev else None)
    elif nx:
        o["next"] = f"离 {nx[1]['md']} 还有 {nx[0] + 1} 个交易日（北京时间）"
    if len(next5) > 1:
        w2, _ = word(next5[1:3], next5[3:], later_ev)
        o["if"] = dict(t=f"如果日历不变，到 {next5[0]['md']} 收盘 ④ 就{'变成' if w2 != w else '还是'}“{w2}”", sec=["三.8"])
    return o


def _thr(ch, q):
    """5 日走阔要到多少基点，历史上同方向至少一样极端的才不超过 q（口径十一的算法：rarity() 反过来求）。按基点取整往上一格。"""
    h = np.sort(ch.values)[::-1]
    m = int(math.floor(q * len(h)))
    if m >= len(h) or len(h) < 504:
        return None
    return int(math.floor(h[m] + 1e-9)) + 1


def _st_fund(D, t, rows=None):
    """⑤ 信用分档五档的 5 日走阔（口径十一，偏高 5%、少见 1%，ice() 同一个算法）：有一档到少见"在变差"，到偏高"在走阔"，都没到"没变差"。
    离下一步：每档还差几个基点到门槛（门槛 = 这一档 5 日变化的历史里同方向更极端的不超过 5% / 1% 的那个数），取差得最少的那档。
    新5 复查：口径十一"历史不满 504 天、读数旧过 7 天的不算"（smallsignal.rarity() / one() 同一个条件）——这样的档单独记在 na 里，
    不进状态词、离下一步和"如果"那句；五档都不算，状态词就是"不算"，那句只写算得出来的条件（攒满 504 天、7 天内有新读数）。"""
    from qx import smallsignal as SS, export as EX
    if rows is None:
        rows = credit(EX.ice(D, t), None)
    if not rows:
        return None
    t = pd.Timestamp(t)
    sid = dict((nm, s) for s, nm in EX.ICE)
    nmap = {"单 B": "B", "CCC": "CCC 及以下"}
    th, na, nlen = {}, {}, {}
    spark = None
    for x in rows:
        s, _ = SS.series(D, sid.get(nmap.get(x["name"], x["name"])), t)
        if s is None or len(s) < 22:
            na[x["name"]] = "没取到"
            continue
        ch = SS.change(s, True, SS.N5)
        nlen[x["name"]] = len(ch)
        if len(ch) < SS.MIN_DAYS:
            na[x["name"]] = "short"
        elif ch.index[-1] < t - pd.Timedelta(days=7):
            na[x["name"]] = "stale:" + ch.index[-1].strftime("%Y-%m-%d")
        else:
            th[x["name"]] = (_thr(ch, SS.HIGH), _thr(ch, SS.RARE))
        if x["name"] == "CCC":
            spark = [_f(v * 100, 0) for v in s.iloc[-20:].values]
    ok = [x for x in rows if x["name"] not in na]
    worse = [x for x in ok if x.get("up5") and x.get("lvl5") == "少见"]
    wide = [x for x in ok if x.get("up5") and x.get("lvl5") in ("偏高", "少见")]
    short = [x["name"] for x in rows if na.get(x["name"]) == "short"]
    stale = [x["name"] for x in rows if str(na.get(x["name"], "")).startswith("stale:")]
    miss = [x["name"] for x in rows if na.get(x["name"]) == "没取到"]
    why = []                                                   # 不算的原因（页面灰字、⑤ 收着那行、点开"信用利差"那行共用）
    nm = lambda xs: "、".join(xs) + (" " if xs[-1][-1].isascii() else "")      # "BB 历史……"、"投资级历史……"
    if short:
        why.append(f"{'五档' if len(short) == len(rows) == 5 else nm(short)}历史不满 504 天（{'最长' if len(short) > 1 else '只有'} {max(nlen[n] for n in short)} 天）")
    if stale:
        why.append(nm(stale) + f"读数停在 {_mds(min(na[n][6:] for n in stale))}，旧了 7 天以上")
    if miss:
        why.append(nm(miss) + "没取到")
    o = dict(word="不算" if not ok else "在变差" if worse else "在走阔" if wide else "没变差", lv="red" if worse else "yellow" if wide else "gray",
             sec=["十一"] + (["十四.2"] if wide and not worse else []),
             chips=[], spark=spark, thr={k: v for k, v in th.items()}, wide=[x["name"] for x in wide], worse=[x["name"] for x in worse],
             na={x["name"]: ("历史不满 504 天" if na[x["name"]] == "short" else "旧了 7 天以上" if na[x["name"]].startswith("stale:") else na[x["name"]])
                 for x in rows if x["name"] in na}, na_why="；".join(why) or None, n_ok=len(ok))
    if not ok:
        o["next"] = "；".join(why) + "，5 日走阔先不算"
        conds = (["攒满 504 天历史"] if short else []) + (["7 天内有新读数"] if stale else []) + (["取到读数"] if miss else [])
        o["if"] = dict(t=f"如果有一档{'、'.join(conds)}，⑤ 就从“不算”变成“没变差”“在走阔”或“在变差”", sec=["十一"])
        return o
    grp = "五档" if len(ok) == len(rows) == 5 else f"算得了的 {len(ok)} 档"
    gap = lambda x, j: (th[x["name"]][j] - (x.get("c5") or 0)) if x["name"] in th and th[x["name"]][j] is not None and x.get("c5") is not None else None
    if not wide:
        g = [(gap(x, 0), x) for x in ok if gap(x, 0) is not None]
        if g:
            d, x = min(g, key=lambda z: z[0])
            o["next"] = f"离在走阔：{x['name']} 5 日 {_sg(x['c5'], 0)}，要到 +{th[x['name']][0]} 基点（收盘算）"
        o["if"] = dict(t=f"如果{grp}里有一档的 5 日走阔到历史最极端的 5%，⑤ 就从“没变差”变成“在走阔”", sec=["十一"])
    elif not worse:
        g = [(gap(x, 1), x) for x in wide if gap(x, 1) is not None]
        if g:
            d, x = min(g, key=lambda z: z[0])
            o["next"] = f"离在变差：{x['name']} 5 日 {_sg(x['c5'], 0)}，要到 +{th[x['name']][1]} 基点（收盘算）"
        o["if"] = dict(t=f"如果{grp}里有一档的 5 日走阔到历史最极端的 1%，⑤ 就从“在走阔”变成“在变差”", sec=["十一"])
    else:
        x = max(worse, key=lambda z: z.get("c5") or 0)
        if x["name"] in th and th[x["name"]][1] is not None:
            o["next"] = f"{x['name']} 5 日 {_sg(x['c5'], 0)}，回到 +{th[x['name']][1]} 基点以下就不是最极端的 1%（收盘算）"
        o["if"] = dict(t=f"如果{grp}的 5 日走阔都不在历史最极端的 1% 里了，⑤ 就从“在变差”变成“在走阔”或“没变差”", sec=["十一"])
    return o


def five_state(D, R, t, pos=None, flow=None, credit_rows=None, next5=None, later_ev=None, since=None):
    """五样的状态词、颜色、离下一步、"如果……就……"（新5，只给页面用）。①②③⑤ 只用 t 以前的数据，截到以前重算和当天一样（自测查）；
    ④ 用日历那一份（日历没存历史，不在自测里）。"""
    t = pd.Timestamp(t)
    out = {}
    for k, f in (("emo", lambda: _st_emo(D, R, t)), ("price", lambda: _st_price(D, t)), ("flow", lambda: _st_flow(D, t, pos, flow, since)),
                 ("expect", lambda: _st_expect(next5, later_ev)), ("fund", lambda: _st_fund(D, t, credit_rows))):
        try:
            out[k] = f()
        except Exception as e:
            out[k], out[k + "_err"] = None, type(e).__name__
    return out


def page_rows(out):
    """五样各一行（只给页面用）：状态词和颜色、一句话、离下一步，从 out["five"]（five_state）来；一句话都是现有结论的短写，不跨样合成、不打分。
    新5：一件事一个家——VIX 只在 ① 点开、CFTC 那期的数只在 ③ 点开、议息会只在 ④ 点开、信用分档只在 ⑤，前台这一行不再重复写。"""
    V = out.get("five") or {}
    rows = []

    def one(k, name, line):
        o = V.get(k) or {}
        rows.append(dict(k=k, no="①②③④⑤"[NO[k] - 1], name=name, word=o.get("word") or "—", lv=o.get("lv") or "gray", sec=o.get("sec") or [],
                         chips=o.get("chips") or [], line=line or "", next=o.get("next") or "", **({"if": o["if"]} if o.get("if") else {})))
    E = V.get("emo") or {}
    one("emo", "情绪", f"四条里 {E['ebb']} 条在回落" if E.get("ebb") is not None else "")
    S = next((x for x in out.get("pos") or [] if x["k"] == "^SOX"), None)
    one("price", "价格位置", f"半导体离高 {_sg(S['dd'])}%，200 日线{'上' if S['d200'] >= 0 else '下'} {abs(S['d200']):.1f}%" if S else "")   # 照样稿；"离一年高点"写在点开第 1 行
    F = out.get("flow") or {}
    line = ""
    if F:
        by = {}
        for x in F.get("still") or []:
            by.setdefault(x["word"], []).append(x)
        runs = lambda xs: "、".join(x["market"] + f"第 {x['runs']} 期" for x in xs)
        same = lambda xs: xs[0].get("dir") and all(x.get("dir") == xs[0]["dir"] for x in xs)
        st = [runs(xs) + (f"还{w}" if len(by) > 1 else "") + (f"，这一期{'都' if len(xs) > 1 else ''}在{xs[0]['dir']}" if same(xs) else "") for w, xs in by.items()]   # 照样稿"黄金第 12 期、加密第 7 期，这一期都在减"
        ch = [f"{x['market']}{x['word']}（之前连挤 {x['runs']} 期）" if x.get("runs") else f"{x['market']}新{x['word']}" for x in F.get("changed") or []]
        parts = ch + st if (V.get("flow") or {}).get("new") else st + ch          # 红（新一期刚看到、有变化）那天先写变了的
        line = "；".join(parts) if parts else "没有挤在一边的市场"
    one("flow", "买卖方", line)
    M = next((x for x in out.get("m1") or [] if x["name"] == "费城半导体"), None)
    Rc = out.get("react") or {}
    bits = []
    if M:
        bits.append(f"期权给半导体一个月 ±{M['m']:g}%")
    if Rc:
        bits.append(f"好消息不涨占 {Rc['share']:g}%")                  # 以往几季的范围写在 ④ 点开"认不认消息"
    one("expect", "预期", "；".join(bits))
    C, Y = out.get("credit") or [], out.get("y10")
    Ff = V.get("fund") or {}
    bits = []
    if C:
        w = [x for x in C if x["name"] in (Ff.get("wide") or [])]
        na = list((Ff.get("na") or {}).keys())
        n_ok = Ff.get("n_ok", len(C))
        nas = ("、".join(na) + (" " if na and na[-1][-1].isascii() else "") + "不算") if na else ""
        # 新5 复查：历史不满 504 天、读数旧过 7 天的档不算（口径十一），单独写；"都没走阔"改成写门槛（有的档 5 日是走阔了几个基点，只是没到最极端的 5%）
        if Ff and not n_ok:
            bits.append("五档利差 5 日走阔都不算")
        elif w:
            bits.append("、".join(f"{x['name']} 5 日 {_sg(x['c5'], 0)} 基点" for x in w) + "，到了最极端的 " + ("1%" if Ff.get("worse") else "5%")
                        + (f"（{nas}）" if na else ""))
        else:
            bits.append((f"算得了的 {n_ok} 档" if na else "五档") + " 5 日走阔都没到最极端的 5%" + (f"（{nas}）" if na else ""))
    if Y:
        bits.append(f"10 年利率 20 日 {_sg(Y['c20'], 0)} 基点")
    one("fund", "基本面", "；".join(bits))
    return rows


def page_changes(out, today):
    """今天变了什么（只给页面用）：顺序照 today 原来的，后面接五样触发行里 today 以外的；前几天说过的标 old、不画。"""
    T = today or {}
    trig = out.get("trig") or {}
    home = {(x["key"], x.get("date")): k for k, _ in PILLARS for x in trig.get(k) or [] if x.get("src") == "today"}
    res = []
    for x in T.get("items") or []:
        if x.get("kind") == "judge":
            continue                                       # 判断卡在顶上判断条、"我的判断"里
        k = home.get((x["key"], x.get("date")))
        res.append(dict(p=NO.get(k, 0), key=x["key"], date=x.get("date"), title=x["title"], src="today", hide=False))   # today 条目原样都画（plan 第四节 H11）；归不到五样的标"·"
    for k, _ in PILLARS:
        for x in trig.get(k) or []:
            if x.get("src") != "today":
                res.append(dict(p=NO[k], key=x.get("key"), date=x.get("date"), title=x["title"], why=x.get("why"), src=x.get("src"), hide=False))
    E = out.get("emo") or {}
    if E.get("changed") and not any(x.get("kind") == "stage" for x in T.get("items") or []):
        res.append(dict(p=1, key=None, date=E.get("asof"), title=f"阶段换成{E.get('name')}（{_mds(E.get('asof'))} 收盘）", src="stage", hide=False))
    F = out.get("flow") or {}
    if F.get("changed") and out.get("since") and F.get("pub") and out["since"] < F["pub"] <= out.get("asof", ""):
        ch = "；".join(f"{x['market']}{x['word']}（之前连挤 {x['runs']} 期）" if x.get("runs") else f"{x['market']}新{x['word']}" for x in F["changed"])
        res.append(dict(p=3, key=None, date=F["pub"], title=f"CFTC {_mds(F.get('asof'))} 那期（{_mds(F['pub'])} 公布）：{ch}", src="cftc", hide=False))
    for x in T.get("recent") or []:
        res.append(dict(p=NO.get(_pillar_of_item(x), 0), key=x["key"], date=x.get("date"), title=x["title"], src="recent", hide=True, old=x.get("date")))
    return res


def _ev_class(kind, title):
    t = title or ""
    if kind in ("fomc", "presser", "minutes", "opex", "boj", "gdp", "pce"):
        return kind
    if kind == "earnings":
        return "E"
    for rx, c in (("日本央行", "boj"), ("韩国央行", "bok"), ("CPI", "cpi"), ("非农|失业", "nfp"), ("PCE", "pce"), ("GDP", "gdp"), ("零售", "retail"),
                  ("ISM", "ism"), ("纪要", "minutes"), ("记者会|发布会", "presser"), ("议息", "fomc")):
        if __import__("re").search(rx, t):
            return c
    return None


def page_next5(out, hap_p, cal, radar, t):
    """接下来 5 个美股交易日（北京时间）和"再往后"一行（只给页面用；名单照口径三.8，估的日子不算）。
    日历（happen 的 7 天、BLS 补的非农）先用，带市值、期权幅度；时间轴补日历没有的。同一件事（财报按代码、别的按类）同一个美东日子只算一次。"""
    from qx import events as EV
    t = pd.Timestamp(t).strftime("%Y-%m-%d")
    rows = []
    d = t
    while len(rows) < 5:
        d = _next_trading(d)
        rows.append(d)
    caps = {e.get("sym"): e.get("cap") for e in list((hap_p or {}).get("calendar") or []) + list((cal or {}).get("events") or []) if e.get("sym") and e.get("cap")}
    evs, seen = [], set()

    def add(us, cls, bj=None, untimed=False, sym=None, name=None, implied=None, cap=None, est=False, src="", lab=None):
        key = ("E", sym, us) if cls == "E" else (cls, us)
        if key in seen:
            return
        seen.add(key)
        evs.append(dict(us=us, cls=cls, bj=bj, untimed=untimed, sym=sym, name=name, implied=implied, cap=cap, est=est, lab=lab or NEXT_LABEL.get(cls)))

    def big(sym, cap):
        """口径三.8 的财报名单：关注的公司（events.WATCH，日历里 why=关注）或 1 万亿美元以上（日历的市值；没有市值的用 BIG_SYMS）。
        时间轴（qx/timeline.py）的财报名单还多收了 coverage 的代码（MSTR、COIN 这些），日历没收的不从时间轴补进来（新4 复查改正）。"""
        return sym in EV.WATCH or (cap or 0) >= 1e12 or (cap is None and sym in BIG_SYMS)

    def nm(sym, fallback):
        return EV.NAMES.get(sym) or NAME_ADD.get(sym) or short_name(fallback or sym)

    def ism(e):
        n = str(e.get("note") or "")
        return next((lab for rx, lab in ISM_LAB if __import__("re").search(rx, n)), None)

    for e in list((hap_p or {}).get("calendar") or []) + list(out.get("cal_add") or []):
        c = _ev_class(e.get("kind"), e.get("title"))
        if not c or e.get("est"):
            continue
        if c == "E":
            if not (e.get("why") == "关注" or (e.get("cap") or 0) >= 1e12):
                continue
            tm = e.get("time") or ""
            bj = pd.Timestamp(f"{e['date']} {'08:00' if tm == '盘前' else '16:00'}", tz=clock.NY).tz_convert(clock.SH) if tm in ("盘前", "盘后") else None
            add(e["date"], c, bj=bj, untimed=bj is None, sym=e.get("sym"), name=nm(e.get("sym"), e.get("name")),
                implied=(e.get("implied") or [{}])[0].get("move"), cap=e.get("cap"))
            continue
        bj = pd.Timestamp(e["utc"]).tz_convert(clock.SH) if e.get("utc") else None
        if bj is None and c in ("fomc", "presser", "minutes"):
            x = _fed_et(e)
            bj = x.tz_convert(clock.SH) if x is not None else None
        if bj is None and e.get("time"):
            x = _et_time(e["date"], (e.get("time") or "").replace(" 美东", ""))
            bj = x.tz_convert(clock.SH) if x is not None else None
        add(e["date"], c, bj=bj, untimed=bj is None and c != "opex", lab=ism(e) if c == "ism" else None)
    tl = (out.get("tlfix") or {}).get("events") or (((radar or {}).get("fwd") or {}).get("timeline") or {}).get("events") or []
    for e in tl:
        c = _ev_class(e.get("kind"), e.get("title"))
        if not c:
            continue
        b = str(e.get("bj") or "")
        bj, untimed = None, False
        if c == "E":
            if not big(e.get("sym"), caps.get(e.get("sym"))):
                continue
            if b[11:] in ("盘前", "盘后"):
                bj = pd.Timestamp(f"{e['date']} {'08:00' if b[11:] == '盘前' else '16:00'}", tz=clock.NY).tz_convert(clock.SH)
            else:
                untimed = True
            add(e["date"], c, bj=bj, untimed=untimed, sym=e.get("sym"), name=nm(e.get("sym"), str(e.get("title") or "").replace(" 财报", "")),
                cap=caps.get(e.get("sym")))
            continue
        if len(b) >= 16 and b[13] == ":":
            bj = pd.Timestamp(b[:16], tz=clock.SH)
        add(e["date"], c, bj=bj, untimed=bj is None and c != "opex")
    first, last = rows[0], rows[-1]
    slot = {d: [] for d in rows}
    for x in evs:
        if not (t < x["us"] <= last or (x["cls"] == "E" and x["us"] == t and x["bj"] is not None and x["bj"].hour < 12)):
            continue
        if x["cls"] == "E" or x["untimed"] or x["cls"] == "opex":
            ed = x["bj"].strftime("%Y-%m-%d") if x["cls"] == "E" and x["bj"] is not None else x["us"]
        else:
            ed = x["bj"].strftime("%Y-%m-%d")
        r = max([d for d in rows if d <= ed], default=first)
        x["pre"] = "" if ed == r else "次日 " if ed == (date.fromisoformat(r) + timedelta(days=1)).isoformat() else f"{_mds(ed)} "
        slot[r].append(x)
    out5 = []
    for d in rows:
        xs = slot[d]
        timed = sorted([x for x in xs if x["cls"] != "E" and not x["untimed"] and x["cls"] != "opex"], key=lambda x: x["bj"])
        txt = [f"{x['pre']}{x['bj'].strftime('%H:%M')} {x['lab']}" for x in timed]
        txt += [f"{x['lab']}（{'收盘时' if x['cls'] == 'opex' else '时间未定'}）" for x in xs if x["cls"] != "E" and (x["untimed"] or x["cls"] == "opex")]
        ev = [EV_SHORT.get(x["lab"], x["lab"]) for x in timed] + [EV_SHORT.get(x["lab"], x["lab"]) for x in xs if x["cls"] != "E" and (x["untimed"] or x["cls"] == "opex")]
        for pre in dict.fromkeys(x["pre"] for x in xs if x["cls"] == "E"):
            er = sorted([x for x in xs if x["cls"] == "E" and x["pre"] == pre], key=lambda x: -(x.get("cap") or 0))
            top = er[0]
            nm = top["name"] + (f"（±{top['implied'] * 100:.1f}%）" if top.get("implied") else "")
            txt.append(f"{pre}{nm} 等 {len(er)} 家财报" if len(er) > 1 else f"{pre}{nm} 财报")
        er = [x["name"] for x in sorted([x for x in xs if x["cls"] == "E"], key=lambda x: -(x.get("cap") or 0))]
        dd = date.fromisoformat(d)
        out5.append(dict(d=d, md=_mds(d), wd=WEEK[dd.weekday()], text=" · ".join(txt) or "—", ev=list(dict.fromkeys(ev)), er=er))   # ev / er：④ 状态词用的短名、财报公司（新5）
    # 再往后：每样取 last 以后（45 天内）的第一件；非农表管不到的月份写"约 M/D 非农（估的）"
    end = (date.fromisoformat(last) + timedelta(days=45)).isoformat()
    later, got, later_ev = [], set(), []                  # later_ev：④ "下一件"用的（日子、M/D、短名），估的日子不进（十四.12）
    for x in sorted(evs, key=lambda x: x["us"]):
        if not (last < x["us"] <= end):
            continue
        if x["cls"] == "E":
            if not ((x.get("cap") or 0) >= 1e12 or x.get("sym") in BIG_SYMS) or "E" in got:
                continue
            got.add("E")
            dd = x["us"] if x["bj"] is None else x["bj"].strftime("%Y-%m-%d")          # 北京日子（盘后的财报是第二天早上），和上面 5 天同一个口径
            later.append((dd, f"{_mds(dd)} {x['name']} 财报"))
            later_ev.append((dd, _mds(dd), _cat(x["name"], "财报")))
        elif x["cls"] in ("nfp", "cpi", "opex", "fomc") and x["cls"] not in got:
            got.add(x["cls"])
            dd = x["us"] if x["cls"] == "opex" or x["bj"] is None else x["bj"].strftime("%Y-%m-%d")
            later.append((dd, f"{_mds(dd)} {x['lab']}"))
            later_ev.append((dd, _mds(dd), EV_SHORT.get(x["lab"], x["lab"])))
    if "nfp" not in got:
        for e in out.get("nfp_later") or []:
            if last < e["date"] <= end:
                dd = pd.Timestamp(e["utc"]).tz_convert(clock.SH).strftime("%Y-%m-%d") if e.get("utc") else e["date"]
                later.append((dd, f"约 {_mds(dd)} 非农（估的）" if e.get("est") else f"{_mds(dd)} 非农"))
                break
    later = " · ".join(s for _, s in sorted(later))
    out["later_ev"] = [list(x[1:]) for x in sorted(later_ev)[:1]]
    return out5, later


def page_mk(radar):
    """各市场每类一行：这一类里今天动得最不寻常的那个（markets.rows() 已经按 |z| 排好），类按 |z| 排（只给页面用）。"""
    out = []
    for r in (radar or {}).get("mkts") or []:
        it = next((x for x in r.get("items") or [] if x.get("z") is not None), None) or ((r.get("items") or [None])[0])
        out.append(dict(cls=r["cls"], s=it and it.get("s"), n=it and it.get("n"), chg=it and it.get("chg"), z=it and it.get("z"), bp=bool(it and it.get("bp")),
                        day=it and it.get("day")))
    return sorted(out, key=lambda x: -abs(x["z"]) if x["z"] is not None else 1)


def today_lv(five, changes):
    """十四.12："今天有 ②–⑤ 的变化"（"今天变了什么"里归到这一样、没收起来的）也算黄；本来是灰的才升成黄，红不动。"""
    for k in ("price", "flow", "expect", "fund"):
        o = (five or {}).get(k)
        if o and o.get("lv") == "gray" and any(x.get("p") == NO[k] and not x.get("hide") for x in changes or []):
            o["lv"], o["sec"] = "yellow", list(o.get("sec") or []) + ["十四.3"]
            o["today"] = True


def page_keys(out, today, hap_p, cal, radar, t, D=None, R=None):
    for k, f in (("changes", lambda: page_changes(out, today)), ("next5", lambda: page_next5(out, hap_p, cal, radar, t)),
                 ("mk", lambda: page_mk(radar)),
                 ("cards", lambda: dict(show=3, more=8, keys=[c["key"] for c in ((radar or {}).get("cards") or {}).get("cards") or []]))):
        try:
            out[k] = f()
        except Exception as e:
            out[k], out[k + "_err"] = None, type(e).__name__
    if isinstance(out.get("next5"), tuple):
        out["next5"], out["later"] = out["next5"]
    if D is not None and R is not None:                   # 新5：五样的状态词、颜色、离下一步、"如果……就……"
        try:
            out["five"] = five_state(D, R, t, pos=radar.get("pos"), flow=out.get("flow"), credit_rows=out.get("credit"), next5=out.get("next5"),
                                     later_ev=(out.get("later_ev") or [None])[0], since=out.get("since"))
            today_lv(out["five"], out.get("changes"))
        except Exception as e:
            out["five"], out["five_err"] = None, type(e).__name__
    try:
        out["rows"] = page_rows(out)
    except Exception as e:
        out["rows"], out["rows_err"] = None, type(e).__name__


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
    for k, f in (("hl", lambda: W.highs_lows(D, t)),                                  # 新5：② 点开"52 周新高减新低"（口径十四.13，只作描述）
                 ("move", lambda: (lambda s: dict(now=_f(s.iloc[-1], 1), date=s.index[-1].strftime("%Y-%m-%d")))(D["^MOVE"]["c"].dropna().loc[:t]) if "^MOVE" in D else None)):
        try:
            out[k] = f()
        except Exception as e:
            out[k], out[k + "_err"] = None, type(e).__name__
    page_keys(out, today, hap_p, cal, radar, t, D, R)           # 新4：页面骨架用的新键（只给页面用）；新5 加五样的状态
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
