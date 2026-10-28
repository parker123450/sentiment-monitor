"""仓位和资金（第四轮第 3 步，2026-10-27）。规则在 口径.md 第十一节。

取数（每天一次，run.py 按时间判断；每个文件都带"能看到的时间" pub，按它截断；攒起来以后新取到的行，pub 不早于取到的那天）：
  CFTC 每周持仓（publicreporting.cftc.gov，Legacy 期货）：非商业（投机）多空，2006 年起。数据截至周二，周五美东 15:30 公布 → pub = 周二 + 3 天。
  杠杆 ETF：Direxion 每天的 SOXL / SOXS 份额（CSV 第一行 Shares Outstanding），从 10-27 起攒；pub = 取到的时间。
  空头仓位：纳斯达克的 short-interest（每月两次结算日；FINRA 约 8 个工作日后公布）→ pub = 结算日 + 11 天（保守）。
  日本国债：财务省 jgbcm_all.csv（全量）+ jgbcm.csv（当月）；pub = 那一天的下一天（收盘后才出）。
计算 compute(D, t)：每个读数在自己当天以前全部历史里的位置（原则 2）；"挤在哪边"：同一市场能取到的读数全部在同一侧 10% 以外才写，否则"方向不一致"。
趋势基金（估）：20、60、120 日涨跌的正负算多空，翻转价 = 让这个周期涨跌变号的价格（就是 N 天前的收盘）。简化模型，不是真实持仓。
"""
import csv, io, json, os, re, time, urllib.parse
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from qx import store

CFTC_CSV = os.path.join(store.HERE, "cftc.csv")
LETF_CSV = os.path.join(store.HERE, "letf.csv")
SI_CSV = os.path.join(store.HERE, "short_interest.csv")
JGB_CSV = os.path.join(store.HERE, "jgb.csv")
UA_NAMED = {"User-Agent": "qx-radar/1.0 (+https://github.com/parker123450/sentiment-monitor)"}
JSON_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}      # 纳斯达克：面板现有来源原来的请求头
EDGE, MIN_OBS = 0.10, 104                                                   # 挤在哪边：10% 以外；至少 104 个观测（周度 2 年）才和历史比

# CFTC 合约代码 → (名字, 市场)
CFTC = {"13874A": ("标普 500 期货", "美股"), "209742": ("纳指 100 期货", "美股"), "1170E1": ("VIX 期货", "美股波动"),
        "043602": ("10 年美债期货", "美债"), "042601": ("2 年美债期货", "美债"), "020601": ("长期美债期货", "美债"),
        "097741": ("日元期货", "日元"), "099741": ("欧元期货", "欧元"), "098662": ("美元指数期货", "美元"),
        "067651": ("WTI 原油期货", "原油"), "023651": ("天然气期货", "天然气"), "088691": ("黄金期货", "黄金"), "085692": ("铜期货", "铜"),
        "002602": ("玉米期货", "农产品"), "005602": ("大豆期货", "农产品"), "001602": ("小麦期货", "农产品"), "133741": ("比特币期货", "加密")}
SI_WATCH = ["NVDA", "AMD", "AVGO", "MU", "TSM", "ORCL", "CRWV", "NBIS", "IREN", "MSFT", "META", "SMCI", "COIN", "MSTR", "TSLA"]


def _rows(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(p, cols, rows):
    tmp = p + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in cols} for r in rows)
    os.replace(tmp, p)


# ================================================================ 取
def _seen_day(incremental):
    """攒起来以后新取到的行：能看到的时间不早于取到的那天（UTC）。第一次整份取的历史没有这个限制。"""
    return datetime.now(timezone.utc).date() if incremental else None


def _pub(guess, seen):
    """公布时间 = 推定的公布日（CFTC 周二 + 3 天、空头结算日 + 11 天、日本国债次日）和取到那天里晚的那个。
    CFTC 遇到假日、政府停摆会晚发，推定的日子会早于真正能看到的那天（2026-10-28 补，口径第十一节）。"""
    return (max(guess, seen) if seen else guess).isoformat()


# CFTC 停摆后补发的真实公布日（CFTC 2025-12-09 公告的加快补发表，cftc.gov COT Historical Special Announcements）。
# 原来按"周二 + 3 天"推，这 13 期提前了 1–7 周看到，回放和卡的回放用了未来数据（原则 3）。口径十一 2026-10-29 补。
CFTC_LATE = {"2025-09-30": "2025-11-19", "2025-10-07": "2025-11-21", "2025-10-14": "2025-11-25", "2025-10-21": "2025-12-02",
             "2025-10-28": "2025-12-05", "2025-11-04": "2025-12-09", "2025-11-10": "2025-12-10", "2025-11-18": "2025-12-12",
             "2025-11-25": "2025-12-15", "2025-12-02": "2025-12-17", "2025-12-09": "2025-12-19", "2025-12-16": "2025-12-23",
             "2025-12-23": "2025-12-29"}


def _us_holidays(y):
    """会让 CFTC 那周晚发的美国联邦假日（落在周三到周五的才有影响）：元旦、六月节（2021 起）、独立日、退伍军人节、感恩节、圣诞，周末的按观察日。"""
    def obs(d):
        return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d
    nov = date(y, 11, 1)
    out = {obs(date(y, 1, 1)), obs(date(y, 7, 4)), obs(date(y, 11, 11)), obs(date(y, 12, 25)), nov + timedelta(days=(3 - nov.weekday()) % 7 + 21)}
    if y >= 2021:
        out.add(obs(date(y, 6, 19)))
    return {d.isoformat() for d in out}


def cftc_pub(d):
    """截至周二 d 的那一期什么时候能看到：通常周五（d + 3）。停摆补发的用 CFTC 公布的补发日；
    那一周周三到周五碰到美国假日的，按下周一算（宁晚不早）。"""
    s = d.isoformat()
    if s in CFTC_LATE:
        return date.fromisoformat(CFTC_LATE[s])
    hol = _us_holidays(d.year) | _us_holidays(d.year + 1)
    if any((d + timedelta(days=k)).isoformat() in hol for k in (1, 2, 3)):
        return d + timedelta(days=6)
    return d + timedelta(days=3)


def fetch_cftc(log=print):
    from qx.fetch import get
    old = _rows(CFTC_CSV)
    since = max((r["date"] for r in old), default="2006-01-01")
    codes = ",".join(f"'{c}'" for c in CFTC)
    q = (f"$select=cftc_contract_market_code,report_date_as_yyyy_mm_dd,open_interest_all,noncomm_positions_long_all,noncomm_positions_short_all"
         f"&$where=cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd > '{since}'&$order=report_date_as_yyyy_mm_dd&$limit=50000")
    url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json?" + urllib.parse.quote(q, safe="=&$'(),")
    j = json.loads(get(url, timeout=120, ua=UA_NAMED))
    have = {(r["code"], r["date"]) for r in old}
    seen = _seen_day(bool(old))
    n = 0
    for x in j:
        d = x["report_date_as_yyyy_mm_dd"][:10]
        k = (x["cftc_contract_market_code"], d)
        if k in have:
            continue
        old.append({"code": k[0], "date": d, "pub": _pub(cftc_pub(date.fromisoformat(d)), seen), "oi": x.get("open_interest_all", ""),
                    "long": x.get("noncomm_positions_long_all", ""), "short": x.get("noncomm_positions_short_all", "")})
        have.add(k)
        n += 1
    _write(CFTC_CSV, ["code", "date", "pub", "oi", "long", "short"], sorted(old, key=lambda r: (r["date"], r["code"])))
    log(f"  CFTC 持仓：新 {n} 行（共 {len(old)}）")
    return n


def fetch_letf(log=print):
    from qx.fetch import get
    rows = _rows(LETF_CSV)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    got = {}
    for s in ("SOXL", "SOXS"):
        txt = get(f"https://www.direxion.com/holdings/{s}.csv", timeout=30, ua=UA_NAMED)
        m = re.search(r"Shares Outstanding:\s*([\d,]+)", txt)
        d = re.search(r'^"?(\d{1,2}/\d{1,2}/\d{4})', txt.splitlines()[2] if len(txt.splitlines()) > 2 else "", re.M)
        if m:
            got[s] = int(m.group(1).replace(",", ""))
            got["trade"] = datetime.strptime(d.group(1), "%m/%d/%Y").date().isoformat() if d else ""
    if "SOXL" in got and "SOXS" in got:
        key = got.get("trade") or now[:10]
        rows = [r for r in rows if r["date"] != key] + [{"date": key, "pub": now, "soxl": got["SOXL"], "soxs": got["SOXS"]}]
        _write(LETF_CSV, ["date", "pub", "soxl", "soxs"], sorted(rows, key=lambda r: r["date"]))
    log(f"  杠杆 ETF 份额：{'取到' if 'SOXL' in got else '没取到'}（共 {len(rows)} 天）")


def fetch_si(log=print):
    from qx.fetch import get
    rows = _rows(SI_CSV)
    have = {(r["sym"], r["settle"]) for r in rows}
    seen = _seen_day(bool(rows))
    n = 0
    for s in SI_WATCH:
        try:
            j = json.loads(get(f"https://api.nasdaq.com/api/quote/{s}/short-interest?assetClass=stocks", timeout=30, ua=JSON_UA))
            for x in ((j.get("data") or {}).get("shortInterestTable") or {}).get("rows") or []:
                d = datetime.strptime(x["settlementDate"], "%m/%d/%Y").date()
                if (s, d.isoformat()) in have:
                    continue
                num = lambda v: float(str(v).replace(",", "")) if v not in (None, "", "N/A") else ""
                rows.append({"sym": s, "settle": d.isoformat(), "pub": _pub(d + timedelta(days=11), seen), "si": num(x.get("interest")),
                             "adv": num(x.get("avgDailyShareVolume")), "dtc": num(x.get("daysToCover"))})
                have.add((s, d.isoformat()))
                n += 1
        except Exception:
            continue
        time.sleep(1)
    _write(SI_CSV, ["sym", "settle", "pub", "si", "adv", "dtc"], sorted(rows, key=lambda r: (r["settle"], r["sym"])))
    log(f"  空头仓位：新 {n} 行（共 {len(rows)}）")


ERA = {"S": 1925, "H": 1988, "R": 2018}


def _jgb_date(s):
    m = re.match(r"^([SHR])(\d+)\.(\d+)\.(\d+)$", s.strip())
    if m:
        return date(ERA[m.group(1)] + int(m.group(2)), int(m.group(3)), int(m.group(4)))
    m = re.match(r"^(\d{4})/(\d+)/(\d+)$", s.strip())
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def fetch_jgb(log=print, full=None):
    """财务省国债收益率：列是 1、2、3、4、5、6、7、8、9、10、15、20、25、30、40 年。只留 2、10、30、40 年。"""
    from qx.fetch import get_bytes
    rows = {r["date"]: r for r in _rows(JGB_CSV)}
    seen = _seen_day(bool(rows))
    full = full if full is not None else not rows
    urls = (["https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"] if full else []) + ["https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"]
    for u in urls:
        txt = get_bytes(u, timeout=60, headers=UA_NAMED).decode("shift_jis", "replace")
        for ln in txt.splitlines():
            p = ln.split(",")
            d = _jgb_date(p[0]) if p else None
            if not d or len(p) < 15:
                continue
            f = lambda i: p[i].strip() if i < len(p) and re.match(r"^-?\d+(\.\d+)?$", p[i].strip()) else ""
            old = rows.get(d.isoformat())                             # 当月的文件每次都会再给一遍：已经有的行保留原来的公布时间
            rows[d.isoformat()] = {"date": d.isoformat(), "pub": old["pub"] if old else _pub(d + timedelta(days=1), seen), "y2": f(2), "y10": f(10), "y30": f(14), "y40": f(15)}
    _write(JGB_CSV, ["date", "pub", "y2", "y10", "y30", "y40"], [rows[k] for k in sorted(rows)])
    log(f"  日本国债：{len(rows)} 天，到 {max(rows) if rows else '—'}")


def fetch_all(log=print):
    for f in (fetch_cftc, fetch_letf, fetch_si, fetch_jgb):
        try:
            f(log=log)
        except Exception as e:
            log(f"  ! {f.__name__} 没取到：{type(e).__name__}")


# ================================================================ 读（按 pub 截到 t）
def _df(p, t, date_col="date"):
    r = _rows(p)
    if not r:
        return pd.DataFrame()
    d = pd.DataFrame(r)
    if p == CFTC_CSV:                                   # 已经存下的行也按真实公布日截（取两者里晚的那个）
        fix = d["date"].map(lambda s: cftc_pub(date.fromisoformat(s[:10])).isoformat())
        d["pub"] = np.where(fix > d["pub"].str[:10], fix, d["pub"])
    d = d[pd.to_datetime(d["pub"].str[:10]) <= pd.Timestamp(t)]
    return d


def jgb_series(t, col="y30"):
    d = _df(JGB_CSV, t)
    if d.empty:
        return None
    s = pd.to_numeric(d[col], errors="coerce")
    s.index = pd.to_datetime(d["date"])
    return s.dropna()


def _pos(hist, x):
    """x 在历史里的位置（0–1，当天以前全部历史）。"""
    h = hist.dropna()
    if len(h) < MIN_OBS:
        return None
    return float((h < x).mean() + 0.5 * (h == x).mean())


def cftc_readings(t):
    d = _df(CFTC_CSV, t)
    out = []
    if d.empty:
        return out
    for code, g in d.groupby("code"):
        if code not in CFTC:
            continue
        g = g.sort_values("date")
        oi, lg, sh = (pd.to_numeric(g[c], errors="coerce") for c in ("oi", "long", "short"))
        net = ((lg - sh) / oi).dropna()
        if len(net) < 2:
            continue
        p = _pos(net.iloc[:-1], float(net.iloc[-1]))
        nm, mk = CFTC[code]
        out.append(dict(src="CFTC", name=nm + " 投机净多 ÷ 总持仓", market=mk, value=round(float(net.iloc[-1]) * 100, 1), unit="%", pos=p,
                        asof=g["date"].iloc[-1], pub=g["pub"].iloc[-1], n=len(net), long_is_crowded=True))
    return out


def letf_readings(t):
    d = _df(LETF_CSV, t)
    if d.empty:
        return []
    d = d.sort_values("date")
    bull, bear = pd.to_numeric(d["soxl"]), pd.to_numeric(d["soxs"])
    ratio = (bull / (bull + bear)).dropna()
    p = _pos(ratio.iloc[:-1], float(ratio.iloc[-1]))
    return [dict(src="Direxion", name="SOXL 份额 ÷（SOXL + SOXS）", market="半导体", value=round(float(ratio.iloc[-1]) * 100, 1), unit="%", pos=p,
                 asof=d["date"].iloc[-1], pub=d["pub"].iloc[-1][:10], n=len(ratio), long_is_crowded=True,
                 note=None if p is not None else f"从 {d['date'].iloc[0]} 起攒，{len(ratio)} 天，满 {MIN_OBS} 天才和历史比")]


def si_readings(t):
    d = _df(SI_CSV, t)
    out = []
    if d.empty:
        return out
    for s, g in d.groupby("sym"):
        g = g.sort_values("settle")
        dtc = pd.to_numeric(g["dtc"], errors="coerce").dropna()
        if dtc.empty:
            continue
        p = _pos(dtc.iloc[:-1], float(dtc.iloc[-1])) if len(dtc) > 24 else None
        out.append(dict(src="纳斯达克", name=f"{s} 空头回补天数", market="美股个股", value=round(float(dtc.iloc[-1]), 1), unit="天", pos=p,
                        asof=g["settle"].iloc[-1], pub=g["pub"].iloc[-1], n=len(dtc), long_is_crowded=False,
                        note=None if p is not None else f"纳斯达克只给最近一年（{len(dtc)} 期），从现在起攒"))
    return out


def panel_readings(D, t):
    """面板已有的：认沽认购（低 = 没人买保护 = 挤在多头）、AAII 看多减看空、CNN 恐慌贪婪。"""
    out = []
    if "PC_EQ" in D:
        s = D["PC_EQ"]["c"]
        s = s[s.index <= t].rolling(10).mean().dropna()
        if len(s) > MIN_OBS:
            out.append(dict(src="CBOE", name="股票认沽 ÷ 认购（10 日均）", market="美股", value=round(float(s.iloc[-1]), 3), unit="", pos=_pos(s.iloc[:-1], float(s.iloc[-1])),
                            asof=s.index[-1].strftime("%Y-%m-%d"), pub=s.index[-1].strftime("%Y-%m-%d"), n=len(s), long_is_crowded=False))
    try:
        a = store.load_aaii()
        if a is not None and len(a):
            a = a[a.index < t]
            spread = (a["bull"] - a["bear"]).dropna() * 100
            out.append(dict(src="AAII", name="散户看多减看空", market="美股", value=round(float(spread.iloc[-1]), 1), unit="%", pos=_pos(spread.iloc[:-1], float(spread.iloc[-1])),
                            asof=spread.index[-1].strftime("%Y-%m-%d"), pub=spread.index[-1].strftime("%Y-%m-%d"), n=len(spread), long_is_crowded=True))
    except Exception:
        pass
    return out


def trend_est(D, t, syms=("^GSPC", "^NDX", "^SOX", "NQ=F", "^N225", "^KS11", "CL=F", "GC=F", "^TNX", "JPY=X", "BTC-USD")):
    """趋势基金（估）：20、60、120 日涨跌的正负，三个加起来 −3 到 +3；翻转价 = N 天前的收盘。"""
    from qx import coverage as C
    out = []
    for s in syms:
        if s not in D:
            continue
        c = D[s]["c"].dropna()
        c = c[c.index <= t]
        if len(c) < 130:
            continue
        sig = {n: int(np.sign(c.iloc[-1] - c.iloc[-1 - n])) for n in (20, 60, 120)}
        out.append(dict(sym=s, name=C.NAME.get(s, s), score=sum(sig.values()), sig=sig, last=round(float(c.iloc[-1]), 4),
                        flip={n: round(float(c.iloc[-1 - n]), 4) for n in (20, 60, 120)}, asof=c.index[-1].strftime("%Y-%m-%d")))
    return out


def side(r):
    """一个读数挤在哪边：位置在 10% 以外。long_is_crowded=True 表示读数高 = 多头拥挤。"""
    if r.get("pos") is None:
        return None
    hi, lo = r["pos"] >= 1 - EDGE, r["pos"] <= EDGE
    if not (hi or lo):
        return "中间"
    return ("多头" if hi else "空头") if r["long_is_crowded"] else ("空头" if hi else "多头")


def compute(D, t):
    t = pd.Timestamp(t)
    R = cftc_readings(t) + letf_readings(t) + si_readings(t) + panel_readings(D, t)
    for r in R:
        r["side"] = side(r)
    by = {}
    for r in R:
        by.setdefault(r["market"], []).append(r)
    crowd = []
    for mk, rs in by.items():
        ss = [r["side"] for r in rs if r["side"] is not None]
        if not ss:
            word = "数据不够"
        elif all(x == "中间" for x in ss):
            word = "不挤"
        elif all(x == "多头" for x in ss):
            word = "挤在多头"
        elif all(x == "空头" for x in ss):
            word = "挤在空头"
        else:
            word = "方向不一致"
        crowd.append(dict(market=mk, word=word, n=len(ss), of=len(rs)))
    return dict(asof=t.strftime("%Y-%m-%d"), readings=R, crowd=crowd, trend=trend_est(D, t))


def values(res):
    v = {}
    for r in res["readings"]:
        v[r["name"]] = r["pos"] if r["pos"] is not None else np.nan
    for c in res["crowd"]:
        v["挤:" + c["market"]] = c["word"]
    for x in res["trend"]:
        v["趋势:" + x["sym"]] = x["score"]
    return v
