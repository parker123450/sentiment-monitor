"""全局自检：不用未来数据（做法照旧终端 core/selftest.py）。

把原始数据截到过去某天 t（FRED 和 AAII 只留观测日早于 t 的，因为第二天才公布；其余留到 t），用同样的代码重算，
t 那天的每个读数都要和全量计算完全一致（相对误差 1e-9）；转折标签里"t 那天已经知道的"也要一样。
模块忘了按公布滞后对齐，或者用了以后的数据，这里会对不上。

用法：python -m qx.selftest [--n 5]
"""
import argparse, contextlib, sys
import numpy as np
import pandas as pd

from qx import sentiment as S, watch as W
from qx.registry import SERIES

KEYS = ["stage", "sell", "price", "pos", "credit", "credit_n", "dd", "ddv", "m_sell", "m_price", "m_pos", "m_credit", "regime", "vixmax"]


def cut(D, aaii, t):
    t = pd.Timestamp(t)
    out = {}
    for k, f in D.items():
        late = k in SERIES and SERIES[k]["source"] == "FRED"
        out[k] = f[f.index < t] if late else f[f.index <= t]
    return out, (aaii[aaii.index < t] if aaii is not None else None)


@contextlib.contextmanager
def extras_cut(t):
    """第四轮新攒的文件，按各自"能看到的时间"截到 t（规划第〇节：cut() 按这一列截断）：
      仓位（cftc、letf、short_interest、jgb）和美债拍卖、FactSet、台湾月营收：pub 的日期 ≤ t；
      财报反应：seen（反应日）≤ t；快讯：能看到的时间（seen，回补的用 pub）在 t 那天结束以前（模块的口径是"收盘日当天看到的都算"）。
    模块自己也按这一列过滤，所以两边应该一样；哪个模块忘了过滤、用了 t 以后才看得到的行，这里会对不上。"""
    from qx import positioning as PS, flash as FL, earn as EA, fundamentals as FU, ledger as LG, store as ST
    t = pd.Timestamp(t)
    day = t.strftime("%Y-%m-%d")
    end = (pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1)).isoformat()
    pub = lambda rows: [r for r in rows if (r.get("pub") or "")[:10] <= day]
    saved = (PS._rows, LG._rows, FL.load_rows, EA.rows, FU.load_tw, ST.load_aaii)
    PS._rows = lambda p, f=saved[0]: pub(f(p))
    LG._rows = lambda p, f=saved[1]: pub(f(p))
    FL.load_rows = lambda f=saved[2]: [r for r in f() if FL.visible(r) < end]
    EA.rows = lambda f=saved[3]: [r for r in f() if (r.get("seen") or "")[:10] <= day]
    FU.load_tw = lambda f=saved[4]: pub(f())
    ST.load_aaii = lambda f=saved[5]: (lambda a: None if a is None else a[a.index < t])(f())     # AAII 第二天才用（和 cut() 一样）
    try:
        yield
    finally:
        PS._rows, LG._rows, FL.load_rows, EA.rows, FU.load_tw, ST.load_aaii = saved


def radar_values(D, t):
    """第四轮第 3–5 步的读数（小信号、仓位、卡、三种走向的信号、前瞻六条线），自检比对用。"""
    from qx import smallsignal as SS, positioning as PS, radar as RA, narrative as NR, forward as FW
    p = PS.compute(D, t)
    s = SS.compute(D, t, p)
    c = RA.compute(D, t, p, s)
    v = {**PS.values(p), **SS.values(s), **{"卡:" + k: x for k, x in RA.values(c).items()}}
    n = NR.compute(D, t)
    sc, _ = FW.scenarios(D, t, n, write=False)
    v.update({f"走向:{S['id']}:{w['id']}:{i}": str(x["hit"]) for S in sc for w in S["ways"] for i, x in enumerate(w["signals"])})
    for L in FW.lines(D, t, dict(sig=s, pos=p, narr=n, cards=c)):
        v["前瞻:" + L["id"]] = "；".join(L["signals"] + L["now"])
    from qx import front as FR
    v["前台:台积电营收"] = str(FR.tw_revenue(t))              # 前台⑤：只用 t 那天已经公布的月份
    return v


def values_at(R, t):
    v = {k: R[k].get(t, np.nan) for k in KEYS}
    v.update({c: R["F"][c].get(t, np.nan) for c in R["F"].columns})
    v.update({"X." + c: R["X"][c].get(t, np.nan) for c in R["X"].columns})
    return v


def same(a, b):
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def run(D, aaii, R=None, n=5, seed=None, log=print):
    R = R or S.compute_all(D, aaii)
    idx = R["P"].index
    rng = np.random.default_rng(seed)
    pool = idx[(idx >= "2000-01-01") & (idx < idx[-5])]
    days = list(idx[-2:]) + list(pd.DatetimeIndex(rng.choice(pool.values, size=n, replace=False)))
    recent = idx[(idx >= "2024-01-01") & (idx < idx[-2])]           # 雷达（第四轮）的新文件多是最近才有：另抽 2 个 2024 年以后的日子
    days += [d for d in pd.DatetimeIndex(rng.choice(recent.values, size=min(2, len(recent)), replace=False)) if d not in days]
    bad = []
    for t in days:
        Dt, at = cut(D, aaii, t)
        Rt = S.compute_all(Dt, at)
        full, part = values_at(R, t), values_at(Rt, t)
        diff = [k for k in full if not same(full[k], part.get(k, np.nan))]
        tf = [x for x in R["turns"] if x[2] <= t]
        tp = [x for x in Rt["turns"] if x[2] <= t]
        if tf != tp:
            diff.append("转折标签")
        if [x["title"] for x in W.close_items(D, R, t)] != [x["title"] for x in W.close_items(Dt, Rt, t)]:
            diff.append("今天要知道的")
        if t >= pd.Timestamp("2010-01-01"):                  # 市场在交易什么（第四轮第 2 步）：篮子的成员多数 2010 年以后才有
            from qx import narrative as NR
            a, b = NR.values(NR.compute(D, t)), NR.values(NR.compute(Dt, t))
            eq = lambda x, y: x == y if isinstance(x, str) or isinstance(y, str) else same(x, y)
            diff += ["在交易什么 " + k for k in a if not eq(a[k], b.get(k, np.nan))]
        if t >= pd.Timestamp("2024-01-01"):                  # 小信号、仓位、卡、三种走向、前瞻（第四轮第 3–5 步）：ICE 利差 FRED 只给最近 3 年
            a = radar_values(D, t)                            # 全量：所有攒下的文件都在，模块自己按"能看到的时间"过滤
            with extras_cut(t):                               # 截断：行情截到 t，新攒的文件也截到 t 那一刻能看到的
                b = radar_values(Dt, t)
            diff += ["雷达 " + k for k in set(a) | set(b) if not eq(a.get(k, np.nan), b.get(k, np.nan))]
        log(f"  {t.date()}：" + ("一致" if not diff else "不一致 " + "、".join(diff[:8])))
        if diff:
            bad.append((t, diff))
    if not flash_check(rng, log):
        bad.append(("快讯", ["第一次"]))
    if not parity_check(log):
        bad.append(("和 Worker 对拍", ["打标签、第一次或推送规则"]))
    if not event_check(log):
        bad.append(("期权拆财报", ["event_move"]))
    if not front_check(log):
        bad.append(("前台议息会", ["fomc、北京时间或日历取的日子"]))
    if not optmkt_check(log):
        bad.append(("前台期权大盘", ["只取整一次"]))
    if not views_check(log):
        bad.append(("状态页", ["哪天够、断了几条路或没更新"]))
    return not bad


def parity_check(log=print):
    """和 Worker 对拍（第四轮第 1 步）：Worker 的测试（cd worker && npm test）读同一组样例，两边的结果都要等于样例里写的。
    parity.json：按样例自己带的词表打标签、标"第一次"（不依赖现在的 登记/entities.toml，改词表不会让自检失败）；
    push_cases.json：推送总规则（qx/notify.py 的 gate、digest，只判断，不发）。"""
    import json, os
    from datetime import datetime
    from qx import flash, notify
    fx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker", "test", "fixtures")
    ok = True
    P = json.load(open(os.path.join(fx, "parity.json"), encoding="utf-8"))
    E = [(x["id"], flash._alias_re(x["alias"])) for x in P["rules"]["entities"]]
    L = [(x["id"], flash._kw_re(x["kw"])) for x in P["rules"]["lines"]]
    good = all([i for i, rx in E if rx.search(c["t"])] == c["ents"] and [i for i, rx in L if rx.search(c["t"])] == c["lines"] for c in P["cases"])
    if P["rules"]["white"] == sorted(flash.WHITE) and P["rules"]["first_days"] == flash.FIRST_DAYS:
        good &= {k[1]: v for k, v in flash.firsts([dict(r) for r in P["rows"]]).items()} == P["firsts"]
    ok &= good
    log("  和 Worker 对拍（打标签、第一次）：" + ("一致" if good else "不一致"))
    C = json.load(open(os.path.join(fx, "push_cases.json"), encoding="utf-8"))
    if C["rules"] != {"day_cap": notify.DAY_CAP, "day_start_bj": notify.DAY_START_H, "repeat_h": notify.REPEAT_H}:
        log("  和 Worker 对拍（推送规则）：样例的上限和现在的不一样，要重新写 push_cases.json")
        return False
    st, good = {}, True
    for s in C["steps"]:
        now = datetime.fromisoformat(s["at"].replace("Z", "+00:00"))
        dg = notify.digest(st, now)
        out, n_held = notify.gate(st, [dict(m) for m in s["msgs"]], now)
        good &= [m["key"] for m in out] == s["send"] and ("held" not in s or n_held == s["held"]) \
            and ("digest" not in s or [{"title": m["title"], "body": m["body"]} for m in dg] == s["digest"])
    ok &= good
    log(f"  和 Worker 对拍（推送规则 {len(C['steps'])} 步）：" + ("一致" if good else "不一致"))
    return ok


def event_check(log=print):
    """期权拆"财报这一下"（口径十四.9）：拿一条答案已知的曲线算回去——平常每天 2%、财报那一下 8%，
    11-02（周一）取数，11-04 盘后发、反应日 11-05，到期日 11-06、11-13：反应日涨跌 = √(8%² + 2%²)，两天合计 = √(8%² + 2 × 2%²)；
    还要认出"第一个到期日太远""只有一个到期日""取数那天已经是反应日（两天合计的第一天，感恩节前一天也算）"拆不出来；
    反应日要和实际涨跌那边是同一天。"""
    from datetime import date
    from qx import cboe
    day, ev = 0.02 ** 2, 0.08 ** 2
    v1, v2 = 4 * day + ev, 9 * day + ev                      # 11-02 收盘到 11-06 收盘 4 个交易日，到 11-13 9 个
    iv = lambda v, cal: round((v * 365 / cal) ** 0.5 * 100, 6)
    c = {"date": "2026-11-02", "curve": [["2026-11-06", 4, iv(v1, 4)], ["2026-11-13", 11, iv(v2, 11)]]}
    r = cboe.event_move(c, date(2026, 11, 5))
    r2 = cboe.event_move(c, date(2026, 11, 5), two=True)
    good = bool(r) and abs(r["sd"] - (ev + day) ** 0.5) < 1e-6 and abs(r["jump"] - 0.08) < 1e-6 and abs(r["day"] - 0.02) < 1e-6 \
        and abs(r["med"] - (ev + day) ** 0.5 * cboe.MED_Z) < 1e-6 \
        and bool(r2) and abs(r2["sd"] - (ev + 2 * day) ** 0.5) < 1e-6 \
        and cboe.event_move(dict(c, date="2026-11-05"), date(2026, 11, 5)) is None \
        and cboe.event_move(dict(c, date="2026-11-04"), date(2026, 11, 5), two=True) is None \
        and cboe.event_move({"date": "2026-11-25", "curve": [["2026-11-27", 2, 60.0], ["2026-12-04", 9, 50.0]]}, date(2026, 11, 27), two=True) is None \
        and cboe.chain_at(dict(c, date="2026-11-03", prev=c), "2026-11-02") is c \
        and cboe.event_move({"date": "2026-11-02", "curve": [["2026-11-20", 18, 60.0], ["2026-12-18", 46, 50.0]]}, date(2026, 11, 5)) is None \
        and cboe.event_move({"date": "2026-11-02", "curve": [["2026-11-06", 4, 60.0]]}, date(2026, 11, 5)) is None
    # 反应日和 qx/earn.py 算实际涨跌的同一天（公布日是周末、假日的也算）；马丁·路德·金纪念日公布、时间未定的，前一个周五收盘的链能用
    from datetime import timedelta
    from qx import clock, earn
    ds = [date(2025, 1, 2) + timedelta(days=i) for i in range(800)]
    rs = [(d.isoformat(), 100 + i * 0.1) for i, d in enumerate(x for x in ds if clock.is_trading_day(x))]
    code = {"盘前": "time-pre-market", "盘后": "time-after-hours", "时间未定": "time-not-supplied"}
    for d in ("2026-01-16", "2026-01-17", "2026-01-19", "2026-04-02", "2026-04-03", "2026-11-05", "2026-11-25", "2026-11-26", "2026-12-24"):
        for tm, tc in code.items():
            x = earn._react_rows(rs, date.fromisoformat(d), tc)
            good &= bool(x) and x[0] == cboe.react_day(date.fromisoformat(d), tm).isoformat()
    good &= cboe.event_move(dict(c, date="2026-01-16", curve=[["2026-01-23", 7, 60.0], ["2026-01-30", 14, 50.0]]),
                            cboe.react_day(date(2026, 1, 19), "时间未定"), two=True) is not None
    # 分开的两天：日线从公布以后才开始的不算（不当成上市第一天）；元旦公布、日线从 1-2 开始的才是上市第一天（r0 na，r1 照算）
    good &= all(isinstance(x, float) for x in earn._split(rs, "2026-11-05")) and earn._split(rs[10:], "2025-01-03") == (None, None) \
        and earn._split(rs, "2025-01-01")[0] == "na" and isinstance(earn._split(rs, "2025-01-01")[1], float)
    # 日线漏了一根（Yahoo 偶尔整天没有收盘价）：隔着洞不算，等补上
    hole = lambda d: [x for x in rs if x[0] != d]
    good &= earn._split(hole("2026-11-04"), "2026-11-05")[0] is None and earn._split(hole("2026-11-06"), "2026-11-05")[1] is None \
        and earn._split(hole("2026-11-05"), "2026-11-05") == (None, None) and isinstance(earn._split(hole("2026-11-04"), "2026-11-05")[1], float) \
        and all(earn._react_rows(hole(h), date(2026, 11, 5), tc) is None
                for h, tc in (("2026-11-04", "time-pre-market"), ("2026-11-06", "time-after-hours"), ("2026-11-06", "time-not-supplied")))
    log("  期权拆财报（已知答案的曲线）：" + ("一致" if good else "不一致"))
    return good


def front_check(log=print):
    """前台议息会那一行（qx/front.py fomc()）、"接下来 7 天"表和 48 小时的北京时间、"日历是哪天取的"：拿构造的日历、预测市场存档、时间轴算，答案已知。
    下一次 = 决议日在 t 以后（决议日当天算已经开过）；线上盘中墙上时钟过了下一个交易日 14:00 的决议，那一场也算开过（只在 t 之后第二个交易日收盘以前）；
    概率只用 t 那天能看到的那一份——日历是 t 到下一个交易日之间取的才用，不然用存档里 t 以前最近、7 天以内的那一行；
    那份里没有这一场：日历那份 ok.polymarket 为假写"没取到或还没有盘口"、要取了没有写"还没有盘口"、不在要取的场次里写"没存"，存档那份写"这天没存"；概率是整数百分比、只取整一次；
    北京时间：夏令时（10-28）决议是第二天 02:00，冬令时（12-09）是第二天 03:00，记者会晚半小时；没写时刻的决议按 14:00；三处写法一样。"""
    from qx import front as FR
    hist = [dict(date="2026-10-23", meeting="2026-10-28", hold="0.935", cut="0.002", hike="0.0685"),
            dict(date="2026-10-27", meeting="2026-10-28", hold="0.95", cut="0.002", hike="0.048"),
            dict(date="2026-10-27", meeting="2026-12-09", hold="0.6", cut="0.38", hike="0.02")]
    tl = [dict(kind="fomc", date="2027-04-28")]
    cal = dict(fetched="2026-10-27T21:00+00:00", events=[dict(kind="fomc", date="2026-10-28", pm=dict(hold=0.97, cut=0.01, hike=0.02))],
               fomc_pm={"2026-12-09": dict(hold=0.7, cut=0.29, hike=0.01)})
    far = pd.Timestamp("2030-01-01", tz="UTC")                 # 墙上时钟远在以后 = 截到以前的日子，照数据那天算
    f = lambda t, c=cal, now=far: FR.fomc(c, pd.Timestamp(t), hist, tl, now=now)
    ok = []
    a = f("2026-10-27")                                       # 日历是 t 当天取的：用日历
    ok.append([(x["date"], x["bj"], x["bj_hm"], x.get("hold"), x.get("asof")) for x in a]
              == [("2026-10-28", "2026-10-29", "02:00", 97, None), ("2026-12-09", "2026-12-10", "03:00", 70, None)])
    ok.append(f("2026-10-26")[0].get("hold") == 97)           # 日历是 t 的下一个交易日取的：也用
    a = f("2026-10-23")                                       # 日历晚于下一个交易日：用存档 t 那天那行，没存下下次
    ok.append(a[0].get("hold") == 94 and a[0].get("hike") == 7 and a[0].get("asof") is None and a[1].get("why") == "nosave" and "since" not in a[1])
    a = f("2026-10-22")                                       # 存档还没开始
    ok.append([x.get("why") for x in a] == ["nosave", "nosave"])
    a = f("2026-10-28")                                       # 决议日当天：下一次是 12-09，用前一天的存档
    ok.append([x["date"] for x in a] == ["2026-12-09", "2027-01-27"] and a[0].get("hold") == 60 and a[0].get("asof") == "2026-10-27"
              and a[1].get("why") == "nosave")
    ok.append(f("2026-11-03")[0].get("hold") == 60 and f("2026-11-04")[0].get("why") == "nosave")    # 存档只往回找 7 天
    a = f("2026-10-27", dict(cal, fomc_pm={}))                # 日历那份里没有下下次：还没有盘口
    ok.append(a[1].get("why") == "nomkt")
    ok.append([x["date"] for x in f("2027-03-18")] == ["2027-04-28"])   # 时间轴取到的场次并进来
    a = f("2026-10-27", dict(cal, fomc_pm={}, events=[dict(kind="fomc", date="2026-10-28")], ok=dict(polymarket=False)))   # 整个没取到
    ok.append([x.get("why") for x in a] == ["fail", "fail"])
    # 线上盘中：t 还是 10-27 收盘，日历 10-28 美东 11:00 取的（决议前）；美东 15:00 跑 → 10-28 那场已经开完，下一次 12-09，再下一次日历没去取 → 没存
    c2 = dict(fetched="2026-10-28T15:00+00:00", **{"from": "2026-10-28"}, events=[dict(kind="fomc", date="2026-10-28", pm=dict(hold=0.97, cut=0.01, hike=0.02))],
              fomc_pm={"2026-12-09": dict(hold=0.7, cut=0.29, hike=0.01)})
    a = f("2026-10-27", c2, pd.Timestamp("2026-10-28 15:00", tz="America/New_York"))
    ok.append([(x["date"], x.get("hold"), x.get("why")) for x in a] == [("2026-12-09", 70, None), ("2027-01-27", None, "nosave")])
    a = f("2026-10-27", c2, pd.Timestamp("2026-10-28 13:00", tz="America/New_York"))   # 决议前：照旧
    ok.append([x["date"] for x in a] == ["2026-10-28", "2026-12-09"] and a[0].get("hold") == 97)
    ok.append(FR._pct("0.2745") == 27 and FR._pct(0.705) == 71 and FR._pct(0.245) == 25 and FR._pct(None) is None)   # 只取整一次（原来先留 3 位：0.275 → 28）；逢 5 进，和 k.js Math.round 一样
    ev = [dict(kind="fomc", date="2026-10-28", time="2:00 p.m. 美东", title="议息会（决议）"), dict(kind="presser", date="2026-10-28", time=" 美东", title="主席记者会"),
          dict(kind="fomc", date="2026-12-09", time=" 美东", title="议息会（决议）"), dict(kind="cpi", date="2026-10-28", time="8:30 a.m.", title="CPI")]
    ok.append(FR.fed_bj(ev) == {"fomc|2026-10-28": dict(bj="2026-10-29", hm="02:00"), "presser|2026-10-28": dict(bj="2026-10-29", hm="02:30"),
                                "fomc|2026-12-09": dict(bj="2026-12-10", hm="03:00")})
    now = pd.Timestamp("2026-10-27 17:00", tz="America/New_York")
    h = FR.h48(ev[:1], now=now)
    ok.append([(d["day"], [x["at"] for x in d["items"]]) for d in h] == [("10/29 周四", ["02:00"])])
    h = FR.h48(ev[1:2], now=now)                              # 记者会没写时刻：按 14:30 换成北京时间，和"接下来 7 天"同一天（原来按美东日子写"时间未定"）
    ok.append([(d["day"], [x["at"] for x in d["items"]]) for d in h] == [("10/29 周四", ["02:30"])])
    got = dict(fetched="2026-10-30T07:58+00:00")
    ok.append(FR.cal_late(got, pd.Timestamp("2026-10-29")) is None and FR.cal_late(got, pd.Timestamp("2026-10-28")) == "2026-10-30"
              and FR.cal_late({}, pd.Timestamp("2026-10-28")) is None)
    good = all(ok)
    log("  前台议息会（构造的日历和存档）：" + ("一致" if good else "不一致 第 " + "、".join(str(i + 1) for i, x in enumerate(ok) if not x) + " 条"))
    return good


def optmkt_check(log=print):
    """期权块"大盘"那一行（qx/front.py opt_market()）：只取整一次，数和 qx/options.py market() 那句一样。
    构造的收盘：VIX 19.450001（先留 4 位再取一位会变成 19.4）、9 天 ÷ 30 天 0.964951（先留 4 位再取整会变成 97%）。"""
    from qx import front as FR, options as OP
    idx = pd.bdate_range("2020-01-01", periods=300)
    ser = lambda last, lo, hi: pd.DataFrame(dict(c=np.r_[np.linspace(lo, hi, 299), last]), index=idx)
    D = {"^VIX": ser(19.450001, 12, 30), "^VIX9D": ser(19.450001 * 0.964951, 12, 30), "^SKEW": ser(152.4999, 120, 170), "^VVIX": ser(109.5001, 80, 140)}
    o, m = FR.opt_market(D), OP.market(D)
    ok = [o["vix"]["now"] == 19.5, o["r9"] == 96, o["skew"]["now"] == 152, o["vvix"]["now"] == 110, o["r9_ge1"] is False,
          f"VIX {o['vix']['now']}（" in m, f"30 天的 {o['r9']:g}%" in m, f"SKEW {o['skew']['now']:g}（" in m, f"VVIX {o['vvix']['now']:g}（" in m,
          o["vix"]["p"] == round((D["^VIX"]["c"] <= 19.450001).mean() * 100)]
    good = all(ok)
    log("  前台期权大盘（构造的收盘）：" + ("一致" if good else "不一致 第 " + "、".join(str(i + 1) for i, x in enumerate(ok) if not x) + " 条"))
    return good


def views_check(log=print):
    """状态页（qx/front.py，第四轮后台精简第 2 步）："大约哪天够"按交易日 / 半月一期推，断了的路和顶栏红字同一个数，
    "没更新"和页面顶部数据提醒同一个算法（AAII 落后 9 天以上、其余 4 天以上）。构造的数。"""
    from qx import front as FR
    st = {"AAII 散户调查": {"last": "2026-10-13"}, "AAII 散户调查 2": {"last": "2026-10-14"}, "VIX": {"last": "2026-10-19"}, "黄金": {"last": "2026-10-18"}, "空": {}}
    ok = [FR.ready_by("2026-10-23", 245, 250) == "2026-10-30", FR.ready_by("2026-10-23", 300, 250) == "2026-10-23",
          FR.ready_by("2026-10-23", 0, 24, "half") == "2027-10", FR.ready_by("2026-10-23", 249, 250) == "2026-10-26",
          [h["name"] for h in FR.broken_routes({"health": [{"name": "a", "ok": True}, {"name": "b", "ok": False}, {"name": "c"}]})] == ["b", "c"],
          FR.broken_routes(None) == [],
          len(FR._stale(st, "2026-10-23")) == 3 and all(any(k in x for x in FR._stale(st, "2026-10-23")) for k in ("AAII 散户调查最新", "黄金", "空没有"))]
    good = all(ok)
    log("  状态页（构造的数）：" + ("一致" if good else "不一致 第 " + "、".join(str(i + 1) for i, x in enumerate(ok) if not x) + " 条"))
    return good


def flash_check(rng, log=print, n=3):
    """快讯的"第一次"：按"能看到的时间"截到过去某一刻重算，那一刻以前的标记必须和全量一样（第四轮第 1 步）。"""
    from qx import flash
    rows = flash.load_rows()
    if len(rows) < 20:
        return True
    full = flash.firsts(rows)
    ts = sorted({flash.visible(r) for r in rows})
    ok = True
    for t in [ts[-1]] + list(rng.choice(ts[: max(1, len(ts) - 1)], size=min(n, len(ts) - 1), replace=False)):
        part = [r for r in rows if flash.visible(r) <= t]
        a = flash.firsts(part)
        keys = {(r["route"], r["id"]) for r in part}
        b = {k: v for k, v in full.items() if k in keys}
        same_ = a == b
        ok &= same_
        log(f"  快讯截到 {t[:16]}：" + ("一致" if same_ else f"不一致（{len(set(a.items()) ^ set(b.items()))} 处）"))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    a = ap.parse_args()
    from qx import store
    D, aaii = store.load_all()
    ok = run(D, aaii, n=a.n)
    print("自检通过" if ok else "自检没过")
    sys.exit(0 if ok else 1)
