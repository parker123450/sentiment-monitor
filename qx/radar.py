"""机会和风险卡（第四轮第 4 步，2026-10-27）。规则在 口径.md 第十二节，先写条件再写代码；阈值用惯例整数。

6 类，都在整个扫描范围里跑，页面按少见程度排，不按行业排：
  1 小信号对仓位    第 3 步的"不对称"
  2 信用和股价背离  篮子 20 日折算涨跌 和 配对信用的 20 日"健康度"（= −压力，按自己全部历史的 20 日变化标准差折算）方向相反，且差 ≥ 1
  3 拥挤和出清      仓位读数到"偏高"（自己历史同方向 5% 以外）标"拥挤"；之后对应价格反着走 ≥ 1 个周度波动，标"开始出清"
  4 消息反应不对称  超预期但反应日跌 ≥ 1 个日度波动："好消息不涨"；反过来"坏消息不跌"。市值 ≥ 200 亿美元、本季发财报的美股
  5 事件定价偏差    期权给的财报幅度 ÷ 最近 4 次实际幅度中位数 ≥ 1.5 或 ≤ 0.67；Polymarket 一天变 15 个百分点以上而相关价格没动
  6 跨市场传导      登记的几组：前一个按日度波动折算动了 ≥ 2，后一个之后的交易时段同向折算涨跌不到一半，标"没跟上"；休市的不算
每张卡五栏：为什么现在、哪里算错、空间、用什么做、时间窗口。只列满足条件的，不写"还差多少"。卡上写"情景，不是买卖建议"。
回放：第 2 类列最近 2 年，第 4 类列最近 4 个季度；第 1、3、5、6 类写"数据从几号起攒，到几号才够回放"，卡上标"还没有回放"。
"""
import json, math, os

import numpy as np
import pandas as pd

from qx import coverage as C, narrative as NR, positioning as PS, smallsignal as SS
from qx.registry import SERIES
from qx.sentiment import longvol

NAMES = {1: "小信号对仓位", 2: "信用和股价背离", 3: "拥挤和出清", 4: "消息反应不对称", 5: "事件定价偏差", 6: "跨市场传导"}
NOTE = "情景，不是买卖建议"
DIV_GAP, CROWD, EARN_DAYS, IMPLIED_HI, IMPLIED_LO, PM_MOVE, LEAD_Z, FOLLOW = 1.0, 0.05, 10, 1.5, 0.67, 0.15, 2.0, 0.5
REPLAY_FROM = {1: "2026-10-27", 3: "2026-10-27", 5: "2026-10-19", 6: "2026-10-27"}   # 这几类从哪天起攒（仓位里 SOXL 份额、期权链、盘中报价）
# 第 3 类：仓位的市场 → (价格, 价格涨 = 多头赚)
CROWD_PRICE = {"美股": ("^GSPC", True), "美股波动": ("^VIX", True), "美债": ("TLT", True), "日元": ("JPY=X", False), "欧元": ("EURUSD=X", True),
               "美元": ("DX-Y.NYB", True), "原油": ("CL=F", True), "天然气": ("NG=F", True), "黄金": ("GC=F", True), "铜": ("HG=F", True),
               "农产品": ("ZS=F", True), "加密": ("BTC-USD", True), "半导体": ("SMH", True)}
# 第 6 类：传导关系（登记，2026-10-27 v1）
PAIRS = [("^SOX", ["^KS11", "^TWII"], "费城半导体 → KOSPI、台湾"), ("^NDX", ["^N225"], "纳指 → 日经"), ("CL=F", ["XLE", "JETS"], "原油 → 能源股、航空"),
         ("JPY=X", ["^N225"], "美元兑日元 → 日经"), ("^TNX", ["XLRE", "KRE", "IWM"], "美债收益率 → 房地产、银行、小盘"),
         ("BTC-USD", ["COIN", "MSTR"], "比特币 → 加密股"), ("^KS11", ["NQ=F"], "KOSPI → 纳指期货（亚洲大动而美股期货没动）"),
         ("^N225", ["NQ=F"], "日经 → 纳指期货")]
OPPOSITE = {("^TNX", "XLRE"), ("^TNX", "KRE"), ("^TNX", "IWM"), ("CL=F", "JETS")}


# ================================================================ 工具
def tail(z):
    """|z| 个标准差以外的双尾比例（正态近似，第 4、6 类排序用；第 1、2、3 类直接数历史）。"""
    return math.erfc(abs(z) / math.sqrt(2))


def _close(D, k, t):
    if k not in D:
        return None
    s = D[k]["c"].dropna()
    late = k in SERIES and SERIES[k]["source"] == "FRED"
    s = s[s.index < t] if late else s[s.index <= t]
    return s if len(s) > 260 else None


def _dvol(s):
    """长期日波动（全部历史，原则 2）。"""
    return float(longvol(s).iloc[-1] / np.sqrt(252))


def _ret(s, n=1, bp=False):
    return float((s.iloc[-1] - s.iloc[-1 - n]) * 100) if bp else float(np.log(s.iloc[-1] / s.iloc[-1 - n]))


def episodes(flag, gap=20):
    """条件从不满足变成满足的日子（相隔 gap 个交易日以内算同一段）。"""
    f = flag.fillna(False).astype(bool).values
    idx, out, last = flag.index, [], -10**9
    for i in range(len(f)):
        if f[i] and (i == 0 or not f[i - 1]) and i - last > gap:
            out.append(idx[i])
        if f[i]:
            last = i
    return out


def fwd(price, dates, n=20, up=True):
    """每段开始后 n 个交易日：涨跌（按看好的方向）和途中最深回撤。"""
    out = []
    for d in dates:
        i = price.index.searchsorted(d)
        if i + n >= len(price):
            continue
        w = price.iloc[i: i + n + 1].values
        r = np.log(w / w[0]) * (1 if up else -1)
        out.append((d, float(r[-1]), float(r.min())))
    return out


def space_text(st):
    if not st:
        return "历史上没有同类"
    worst = min(x[2] for x in st)
    if len(st) < 20:
        return f"历史上同类 {len(st)} 段，途中最深 {abs(np.exp(worst) - 1) * 100:.1f}%（不到 20 段，不写赔率）"
    up = sum(1 for x in st if x[1] > 0)
    return f"历史上同类 {len(st)} 段，20 天后 {up} 段朝看好的方向，途中最深 {abs(np.exp(worst) - 1) * 100:.1f}%"


def letf_decay(D, t, sym="SMH"):
    """3 倍 ETF 每月损耗约 3σ²/12，3 倍反向约 6σ²/12（σ：近 60 天年化波动）。"""
    s = _close(D, sym, t)
    if s is None:
        return ""
    sig = float(np.log(s).diff().iloc[-60:].std() * np.sqrt(252))
    return f"3 倍做多每月损耗约 {3 * sig ** 2 / 12 * 100:.1f}%、3 倍做空约 {6 * sig ** 2 / 12 * 100:.1f}%（σ = 近 60 天年化 {sig * 100:.0f}%）"


def _card(cls, key, title, why, wrong, space, use, window, rank, date, replay=True, **kw):
    return dict(cls=cls, cls_name=NAMES[cls], key=f"c{cls}:{key}", title=title, why=why, wrong=wrong, space=space, use=use, window=window,
                rank=rank, date=date, replayed=replay, note=NOTE, **kw)


# ================================================================ 第 1 类
def class1(D, t, sig):
    out = []
    for x in sig["signals"]:
        if not x.get("asym"):
            continue
        a = x["asym"]
        out.append(_card(1, x["k"], f"{x['name']}：{a['word']}", f"{x['text']}（历史上 {x['frac'] * 100:.1f}% 的日子更极端）；{a['market']}的仓位{a['crowd']}。",
                         f"{x['name']}的 5 日变化回到平常，或者{a['market']}的仓位不再挤在一边。",
                         "还没有回放（SOXL 份额从 2026-10-27 起攒；CFTC 有 2006 年起的周度历史，还没回放）。",
                         f"{a['market']}相关的期货或 ETF；看{C.NAME.get(CROWD_PRICE.get(a['market'], ('', ''))[0], CROWD_PRICE.get(a['market'], ('', ''))[0]) or '对应标的'}。", "5–20 个交易日",
                         x["frac"], x["asof"], replay=False))
    return out


# ================================================================ 第 2 类
def _basket_z_series(D, members, t):
    zs = []
    for m in members:
        s = _close(D, m, t)
        if s is None or (s <= 0).any():
            continue
        lv = longvol(s) / np.sqrt(252)
        zs.append(np.log(s / s.shift(20)) / (lv * np.sqrt(20)))
    return pd.concat(zs, axis=1).median(axis=1).dropna() if zs else None


def _basket_index(D, members, t):
    """篮子的等权指数（第 2 类"之后 20 天"用）：每天取当天有数的成员对数涨跌的平均，累加。
    成员上市晚的从它有数那天起才算进来；价高的成员不多占权重；不同市场休市的日子只算开着的成员。"""
    rs = []
    for m in members:
        s = _close(D, m, t)
        if s is None or (s <= 0).any():
            continue
        rs.append(np.log(s).diff().rename(m))
    if not rs:
        return None
    r = pd.concat(rs, axis=1).mean(axis=1).dropna()
    return np.exp(r.cumsum())


def _health_series(D, p, t):
    """配对信用读数的 20 日"健康度"：−（20 日变化 ÷ 自己全部历史里 20 日变化的标准差），up_is_stress=False 的不取负。"""
    s = NR._series(D, p["id"], t)
    if s is None:
        return None
    fred = p["id"] in SERIES and SERIES[p["id"]]["source"] == "FRED"
    ch = (s - s.shift(20)) * 100 if (fred or p["id"] in NR.BP_PRICE) else np.log(s / s.shift(20))
    sd = ch.expanding(252).std()
    z = (ch / sd).dropna()
    return -z if p.get("up_is_stress", True) else z


def class2(D, t, replay_years=2):
    out, rep = [], []
    for b in NR.registry_at(t)["basket"]:                           # t 那天在用的篮子版本
        if not b.get("pair"):
            continue
        p = b["pair"][0]
        bz = _basket_z_series(D, b["members"], t)
        hz = _health_series(D, p, t)
        if bz is None or hz is None:
            continue
        j = pd.concat([bz.rename("b"), hz.rename("h")], axis=1).dropna()
        if len(j) < 260:
            continue
        flag = (np.sign(j.b) != np.sign(j.h)) & ((j.b - j.h).abs() >= DIV_GAP)
        ep = episodes(flag)
        price = _basket_index(D, b["members"], t)
        if price is None:
            continue
        for d in ep:
            if d >= t - pd.Timedelta(days=365 * replay_years):
                r = fwd(price, [d], up=bool(j.h.get(d, 0) > 0))
                rep.append(dict(basket=b["name"], date=d.strftime("%Y-%m-%d"), b=round(float(j.b[d]), 2), h=round(float(j.h[d]), 2),
                                ret20=round(r[0][1] * 100, 1) if r else None, mdd=round(r[0][2] * 100, 1) if r else None))
        if not flag.iloc[-1] or j.index[-1] < t - pd.Timedelta(days=7):
            continue
        bnow, hnow = float(j.b.iloc[-1]), float(j.h.iloc[-1])
        up = hnow > 0                                                # 信用在变好、股价在跌 → 看股价跟上信用（偏多）；反过来偏空
        st = fwd(price, [d for d in ep if d < j.index[-1] and bool(j.h.get(d, 0) > 0) == up], up=up)   # 历史同类：只算同方向的
        why = (f"{b['name']} 20 日折算 {bnow:+.1f}，{p['name']}的 20 日健康度 {hnow:+.1f}："
               + ("信用在变好，股价却在跌" if up else "信用在变差，股价却在涨") + f"（差 {abs(bnow - hnow):.1f}）。")
        out.append(_card(2, b["id"], f"{b['name']}：{'信用变好、股价没跟' if up else '信用变差、股价没跟'}", why,
                         f"两样重新同向（{p['name']}的健康度和篮子 20 日涨跌同号），或者差缩到 1 以内。", space_text(st),
                         f"篮子成员：{'、'.join(C.NAME.get(m, m) for m in b['members'])}" + ("；" + letf_decay(D, t) if b.get("ai") else ""), "20 个交易日",
                         float(((np.sign(j.b) != np.sign(j.h)) & ((j.b - j.h).abs() >= abs(bnow - hnow))).iloc[:-1].mean()), j.index[-1].strftime("%Y-%m-%d")))
    return out, sorted(rep, key=lambda r: r["date"])


# ================================================================ 第 3 类
def class3(D, t, pos):
    out = []
    for r in pos["readings"]:
        if r.get("pos") is None or not (r["pos"] >= 1 - CROWD or r["pos"] <= CROWD):
            continue
        side = PS.side(dict(r, pos=r["pos"]))
        crowded_long = (r["pos"] >= 1 - CROWD) == r["long_is_crowded"]
        px = CROWD_PRICE.get(r["market"])
        state, why2 = "拥挤", ""
        if px:
            s = _close(D, px[0], t)
            if s is not None and len(s) > 300:
                r5 = np.log(s / s.shift(5)).dropna()
                wv = float(r5.iloc[:-1].std())
                move = float(r5.iloc[-1]) * (1 if px[1] else -1)          # 按"多头赚"的方向
                against = -move if crowded_long else move
                if against >= wv:
                    state = "开始出清"
                why2 = f"；{C.NAME.get(px[0], px[0])} 5 日{'对多头' if crowded_long else '对空头'}不利 {abs(against) / wv:.1f} 个周度波动" if against > 0 else ""
        out.append(_card(3, r["name"], f"{r['market']}：{state}（{'多头' if crowded_long else '空头'}挤）",
                         f"{r['name']} {r['value']}{r['unit']}，在自己历史里 {r['pos'] * 100:.0f}% 的位置（{r['src']}，截至 {r['asof']}）{why2}。",
                         "仓位读数回到 5%–95% 之间；或者价格重新朝挤的方向走、创新高（新低）。",
                         "还没有回放（CFTC 有 2006 年起的周度历史，还没回放）。",
                         f"{C.NAME.get(px[0], px[0]) if px else r['market']}相关的期货或 ETF", "5–20 个交易日",
                         min(r["pos"], 1 - r["pos"]), r["asof"], replay=False, state=state))
    return out


# ================================================================ 第 4 类
def class4(D, t, days=EARN_DAYS, quarters=4):
    from qx import earn
    rs = [r for r in earn.rows() if r.get("seen") and pd.Timestamp(r["seen"]) <= t and earn.in_sample(r)]   # 日度波动按全部历史算、公布前市值 ≥ 200 亿（口径十二 2026-10-28、10-29）
    out, rep = [], []
    for r in rs:
        try:
            sp, ret, dv = float(r["surprise"]), float(r["ret"]), float(r["dvol"])
        except (TypeError, ValueError):
            continue
        kind = "好消息不涨" if sp > 0 and ret <= -dv else "坏消息不跌" if sp < 0 and ret >= dv else None
        if not kind:
            continue
        x = dict(date=r["date"], react=r["react_day"], sym=r["sym"], name=r["name"], kind=kind, surprise=sp, ret=round(ret * 100, 1), z=round(ret / dv, 1),
                 ai=r["sym"] in C.AI_SYMS)
        rep.append(x)
        if pd.Timestamp(r["react_day"]) >= t - pd.tseries.offsets.BDay(days):
            out.append(_card(4, r["sym"] + r["date"], f"{r['sym']}：{kind}",
                             f"{r['name']} {r['date']} 财报超预期 {sp:+.1f}%，反应日（{r['react_day']}）{x['ret']:+.1f}%，是它日度波动的 {abs(x['z']):.1f} 倍。",
                             "股价收复（或跌破）财报前一天的收盘价。", "", f"{r['sym']} 正股或期权", "10 个交易日", tail(x["z"]), r["react_day"]))
    q0 = (t - pd.DateOffset(months=3 * quarters)).strftime("%Y-%m-%d")
    rep = [x for x in rep if x["date"] >= q0]
    tally = {}
    for x in rep:
        q = pd.Timestamp(x["date"]).to_period("Q").strftime("%Y Q%q")
        g = tally.setdefault(q, {"好消息不涨": 0, "坏消息不跌": 0, "AI 链": 0})
        g[x["kind"]] += 1
        g["AI 链"] += x["ai"]
    total = {}
    for r in rs:
        q = pd.Timestamp(r["date"]).to_period("Q").strftime("%Y Q%q")
        total[q] = total.get(q, 0) + 1
    for q in tally:
        tally[q]["家数"] = total.get(q, 0)
    for c in out:
        q = pd.Timestamp(c["date"]).to_period("Q").strftime("%Y Q%q")
        g = tally.get(q, {})
        c["space"] = f"本季（{q}）{g.get('家数', 0)} 家里：好消息不涨 {g.get('好消息不涨', 0)}、坏消息不跌 {g.get('坏消息不跌', 0)}（其中 AI 链 {g.get('AI 链', 0)}）"
    return out, rep, tally


# ================================================================ 第 5 类
def class5(D, t):
    from qx import earn, events as EV, store
    out = []
    try:
        chains = json.load(open(os.path.join(store.HERE, "chains_latest.json"), encoding="utf-8"))
    except Exception:
        chains = {}
    past = {}
    for r in earn.rows():
        if pd.Timestamp(r["seen"]) <= t:
            past.setdefault(r["sym"], []).append(abs(float(r["ret"])))
    for e in EV.load().get("events", []):
        if e.get("kind") != "earnings" or not e.get("sym"):
            continue
        d = pd.Timestamp(e["date"])
        if not (t < d <= t + pd.tseries.offsets.BDay(5)):
            continue
        c = chains.get(e["sym"])
        hist = past.get(e["sym"], [])[-4:]
        if not c or not c.get("curve") or len(hist) < 4:
            continue
        exp_iv = next(((exp, iv) for exp, dte, iv in c["curve"] if pd.Timestamp(exp) >= d), None)
        if not exp_iv:
            continue
        days = max(1, (pd.Timestamp(exp_iv[0]) - pd.Timestamp(c.get("date") or c["asof"])).days)
        implied = exp_iv[1] / 100 * np.sqrt(days / 365)
        ratio = implied / float(np.median(hist))
        if ratio >= IMPLIED_HI or ratio <= IMPLIED_LO:
            out.append(_card(5, e["sym"] + e["date"], f"{e['sym']}：期权给的财报幅度{'偏大' if ratio >= 1 else '偏小'}",
                             f"期权给 ±{implied * 100:.1f}%（到 {exp_iv[0]}），最近 4 次实际幅度中位数 {np.median(hist) * 100:.1f}%，比值 {ratio:.2f}。",
                             "财报后实际幅度落在两者之间。", "还没有回放（期权链从 2026-10-19 起攒）。", f"{e['sym']} 期权（跨式 / 宽跨式）", f"到 {e['date']} 财报",
                             tail(np.log(ratio) / np.log(IMPLIED_HI) * 2), t.strftime("%Y-%m-%d"), replay=False))
    return out


# ================================================================ 第 6 类
def class6(D, t):
    from qx import markets
    out = []
    sess = None
    for lead, fols, nm in PAIRS:
        sL = _close(D, lead, t)
        if sL is None:
            continue
        bpL = lead in C.BP
        zL = _ret(sL, bp=bpL) / (float((sL.diff() * 100 if bpL else np.log(sL).diff()).iloc[:-1].std()) or np.nan)     # 全部历史（原则 2）
        if not np.isfinite(zL) or abs(zL) < LEAD_Z:
            continue
        dL = sL.index[-1]
        for f in fols:
            sF = _close(D, f, t)
            if sF is None or sF.index[-1] <= dL:
                continue                                              # 后一个还没在前一个大动之后交易过（或休市）
            i = sF.index.searchsorted(dL, side="right")
            rF = float(np.log(sF.iloc[i] / sF.iloc[i - 1]))
            zF = rF / float(np.log(sF).diff().iloc[:i].std())
            want = -np.sign(zL) if (lead, f) in OPPOSITE else np.sign(zL)
            if np.sign(zF) == want and abs(zF) >= abs(zL) * FOLLOW:
                continue
            out.append(_card(6, f"{lead}>{f}", f"{nm}：{C.NAME.get(f, f)}没跟上",
                             f"{C.NAME.get(lead, lead)} {dL.strftime('%m-%d')} 动了 {zL:+.1f} 个日度波动；{C.NAME.get(f, f)} 之后的交易日（{sF.index[i].strftime('%m-%d')}）{zF:+.1f}，不到一半{'（方向还相反）' if np.sign(zF) != want else ''}。",
                             f"{C.NAME.get(f, f)}之后几天补上同方向的波动，或者{C.NAME.get(lead, lead)}自己回吐。", "还没有回放（传导关系 2026-10-27 登记）。",
                             f"{C.NAME.get(f, f)}", "1–5 个交易日", tail(zL), sF.index[i].strftime("%Y-%m-%d"), replay=False))
    return out


# ================================================================ 汇总
def compute(D, t, pos=None, sig=None, pm_items=None):
    t = pd.Timestamp(t)
    pos = pos if pos is not None else PS.compute(D, t)
    sig = sig if sig is not None else SS.compute(D, t, pos)
    cards = class1(D, t, sig)
    c2, rep2 = class2(D, t)
    cards += c2 + class3(D, t, pos)
    c4, rep4, tally4 = class4(D, t)
    cards += c4 + class5(D, t) + class6(D, t)
    for x in pm_items or []:                                         # 第 5 类后半：预测市场大变化而大盘没动（只在当天用，不进回放）
        s = _close(D, "SPY", t)
        if s is not None and abs(_ret(s) / _dvol(s)) < 0.5:
            cards.append(_card(5, x["key"], x["title"], "预测市场概率一天变了 15 个百分点以上，标普 ETF 当天动得不到半个日度波动。",
                               "概率回到原来的位置，或者相关价格补上波动。", "还没有回放（预测市场从 2026-10-23 起攒）。", "相关的期货或 ETF", "1–5 个交易日",
                               0.05, t.strftime("%Y-%m-%d"), replay=False))
    cards.sort(key=lambda c: c["rank"])
    return dict(asof=t.strftime("%Y-%m-%d"), cards=cards, replay={2: rep2, 4: rep4[-60:], "tally4": tally4},
                pending={k: f"数据从 {v} 起攒，攒满一年（{(pd.Timestamp(v) + pd.DateOffset(years=1)).strftime('%Y-%m-%d')}）才够回放" for k, v in REPLAY_FROM.items()})


def values(res):
    return {c["key"]: c["rank"] for c in res["cards"]} | {"n": len(res["cards"])}
