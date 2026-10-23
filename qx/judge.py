"""判断卡（第 5 步，2026-10-23）。规则在 口径.md 第六节。

卡片原文在本机 ~/Desktop/情绪交易监控_v3/判断/*.json（不进仓库）；`python run.py seal` 加密成 cards/*.enc 进仓库，云端用 DATA_KEY 解开。
evaluate()：每一环今天是支持 / 中性 / 反对、错的条件出现没有、提出以来怎么走；每天记一行到 data/private/judge_log.csv。
items()：某一环的状态变了、错的条件第一次出现、要人看的事件两个交易日内 → 进"今天要知道的"，排在最前。
"""
import csv, glob, json, os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from qx import crypt, store, clock, fundamentals as FD, events as EV

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS = os.path.join(ROOT, "cards")
LOCAL = os.path.join(os.path.dirname(ROOT), "判断")
LOG = os.path.join(store.HERE, "private", "judge_log.csv")
LOG_COLS = ["date", "card", "link", "status", "fact"]


# ---------------------------------------------------------------- 卡片：本机明文 → 加密进仓库 → 云端解开
def seal():
    key = crypt.data_key()
    os.makedirs(CARDS, exist_ok=True)
    out = []
    for p in sorted(glob.glob(os.path.join(LOCAL, "*.json"))):
        j = json.load(open(p, encoding="utf-8"))
        dst = os.path.join(CARDS, j["id"] + ".enc")
        with open(dst, "wb") as f:
            f.write(crypt.seal(json.dumps(j, ensure_ascii=False).encode("utf-8"), key))
        out.append(dst)
    return out


def load():
    if os.path.isdir(LOCAL) and glob.glob(os.path.join(LOCAL, "*.json")):
        return [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(LOCAL, "*.json")))]
    key = crypt.data_key()
    if not key:
        return []
    return [json.loads(crypt.unseal(open(p, "rb").read(), key)) for p in sorted(glob.glob(os.path.join(CARDS, "*.enc")))]


# ---------------------------------------------------------------- 每一环怎么查（口径.md 六）
def _s(D, k, t):
    return D[k]["c"].dropna()[lambda s: s.index <= t] if k in D else pd.Series(dtype=float)


def chk_rates(D, R, t):
    real = _s(D, "DFII10", t)
    use_real = len(real) > 25 and (pd.Timestamp(t) - real.index[-1]).days <= 10
    s = real if use_real else _s(D, "^TNX", t)
    if len(s) < 25:
        return "中性", "没有数据"
    ch = (s.iloc[-1] - s.iloc[-21]) * 100
    nm = "10 年期实际利率" if use_real else "10 年美债收益率"
    st = "支持" if ch >= 10 else "反对" if ch <= -10 else "中性"
    return st, f"{nm} {s.iloc[-1]:.2f}%，20 天{'升' if ch >= 0 else '降'}了 {abs(ch):.0f} 个基点"


def chk_weak(D, R, t):
    sox, ndx = _s(D, "^SOX", t), _s(D, "^NDX", t)
    if len(sox) < 60 or len(ndx) < 60:
        return "中性", "没有数据"
    r = (sox / ndx).dropna()
    rel = (r.iloc[-1] / r.iloc[-21] - 1) * 100
    ma = sox.rolling(50).mean().iloc[-1]
    below = sox.iloc[-1] < ma
    st = "支持" if rel <= -3 and below else "反对" if rel >= 3 and not below else "中性"
    return st, f"费城半导体 20 天{'跑输' if rel < 0 else '跑赢'}纳指 {abs(rel):.1f}%，在 50 日线{'下方' if below else '上方'}"


def chk_eps(D, R, t):
    t = pd.Timestamp(t)
    tw = [r for r in FD.load_tw() if r["code"] == "2330" and r["pub"] and pd.Timestamp(r["pub"]) <= t + timedelta(days=1)]
    parts, sts = [], []
    if tw:
        r = max(tw, key=lambda r: r["ym"])
        y = float(r["yoy"])
        sts.append("反对" if y >= 20 else "支持" if y <= 0 else "中性")
        parts.append(f"台积电 {int(r['ym'][5:])} 月营收同比 {y:+.0f}%")
    er = FD.load_er()
    rec = [(s, x) for s, xs in er.items() for x in xs if x.get("surp") is not None and t - timedelta(days=45) <= pd.Timestamp(x["d"]) <= t]
    if rec:
        beat = sum(1 for _, x in rec if x["surp"] > 0) / len(rec)
        sts.append("反对" if beat >= 0.7 else "支持" if beat <= 0.3 else "中性")
        parts.append(f"最近 45 天 {len(rec)} 家半导体公司报财报，{sum(1 for _, x in rec if x['surp'] > 0)} 家超预期")
    if not sts:
        return "中性", "没有数据"
    st = "反对" if "反对" in sts else "支持" if all(x == "支持" for x in sts) else "中性"
    return st, "；".join(parts) + "（指引要人看）"


def chk_mood(D, R, t):
    st = R["stage"][R["stage"].index <= t]
    s = int(st.iloc[-1])
    from qx.sentiment import NAMES
    return {1: "支持", 2: "支持", 3: "中性"}.get(s, "反对"), f"情绪阶段：{NAMES[s]}"


CHECKS = {"rates": chk_rates, "weak": chk_weak, "eps": chk_eps, "mood": chk_mood}


def _wrong(w, card, D, t, ref_close):
    sym = card["ref"]["sym"]
    s = _s(D, sym, t)
    after = s[s.index > pd.Timestamp(card["made"])]
    if w["check"] in ("close_ge", "close_ge_ref"):
        lv = w.get("level") if w["check"] == "close_ge" else ref_close
        if w["check"] == "close_ge_ref":             # 先跌到参照价下方 drop% 以后，再收回参照价才算"回调全部收回"
            low = after[after <= ref_close * (1 - w.get("drop", 5) / 100)]
            after = after[after.index > low.index[0]] if len(low) else after.iloc[0:0]
        hit = after[after >= lv]
        if len(hit):
            return dict(state="出现了", date=hit.index[0].strftime("%Y-%m-%d"), detail=f"{hit.index[0].month} 月 {hit.index[0].day} 日收在 {hit.iloc[0]:,.0f}")
        return dict(state="没出现", detail=f"现在 {s.iloc[-1]:,.0f}，离 {lv:,.0f} 还差 {(lv / s.iloc[-1] - 1) * 100:.1f}%")
    if w["check"] == "event":
        ev = [e for e in EV.load().get("events", []) if e.get("kind") == w.get("kind") and e.get("sym") == w.get("sym") and e["date"] >= pd.Timestamp(t).strftime("%Y-%m-%d")]
        if ev:
            d = ev[0]["date"]
            near = _trading_days_between(pd.Timestamp(t).date(), date.fromisoformat(d)) <= 2
            return dict(state="要人看 · 快到了" if near else "要人看", date=d, detail=f"{int(d[5:7])} 月 {int(d[8:])} 日{ev[0].get('time', '')}", near=near)
        return dict(state="要人看", detail="日历里还没有日期（日历看 14 天）")
    return dict(state="—", detail="")


def _trading_days_between(a, b):
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += clock.is_trading_day(d)
    return n


def evaluate(card, D, R, t=None):
    t = pd.Timestamp(t if t is not None else R["P"].index[-1])
    sym = card["ref"]["sym"]
    s = _s(D, sym, t)
    made = pd.Timestamp(card["made"])
    ref_close = float(s[s.index <= made].iloc[-1])
    since = s[s.index >= made]
    out = dict(id=card["id"], title=card["title"], made=card["made"], end=card["end"], why=card.get("why", ""), ref_name=card["ref"]["name"],
               ref_close=round(ref_close, 2), now=round(float(s.iloc[-1]), 2), chg=round((s.iloc[-1] / ref_close - 1) * 100, 1),
               mdd=round((since.min() / ref_close - 1) * 100, 1), days=int((t - made).days), left=int((pd.Timestamp(card["end"]) - t).days),
               expired=t > pd.Timestamp(card["end"]), review=card.get("review", ""), trades=card.get("trades", []))
    links = []
    for L in card["links"]:
        st, fact = CHECKS[L["check"]](D, R, t) if L.get("check") in CHECKS else ("中性", "")
        links.append(dict(id=L["id"], name=L["name"], status=st, fact=fact, pro=L.get("for", []), con=L.get("against", []), note=L.get("note", "")))
    out["links"] = links
    out["weakest"] = [x["name"] for x in links if x["status"] == "反对"]
    out["wrong"] = [dict(w, **_wrong(w, card, D, t, ref_close)) for w in card.get("wrong", [])]
    return out


# ---------------------------------------------------------------- 日志和"今天要知道的"
def _log_rows():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_log(evs, t):
    d = pd.Timestamp(t).strftime("%Y-%m-%d")
    rows = [r for r in _log_rows() if r["date"] != d]
    for e in evs:
        for L in e["links"]:
            rows.append(dict(date=d, card=e["id"], link=L["id"], status=L["status"], fact=L["fact"]))
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    tmp = LOG + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["card"], r["link"])))
    os.replace(tmp, LOG)


def items(evs, t):
    d = pd.Timestamp(t).strftime("%Y-%m-%d")
    prev = {}
    for r in _log_rows():
        if r["date"] < d:
            prev[(r["card"], r["link"])] = r["status"]          # 按日期排过，最后一个就是上一个交易日的
    out = []
    for e in evs:
        for L in e["links"]:
            p = prev.get((e["id"], L["id"]))
            if p and p != L["status"]:
                out.append(dict(kind="judge", key=f"judge:{e['id']}:{L['id']}", group=e["title"], title=f"你的判断「{e['title']}」：「{L['name']}」这一环从{p}变成{L['status']}",
                                facts=[L["fact"]], mean=L.get("note", ""), n10=None, hist="你的判断", date=d, live=False, us=True))
        for w in e["wrong"]:
            if w.get("state") == "出现了" and w.get("date") == d:
                out.append(dict(kind="judge", key=f"judge:{e['id']}:w:{w['id']}", group=e["title"], title=f"你的判断「{e['title']}」：错的条件出现了——{w['text']}",
                                facts=[w.get("detail", "")], mean="这是你事先写下的'什么情况算我错了'。", n10=None, hist="你的判断", date=d, live=False, us=True))
            if w.get("near"):
                out.append(dict(kind="judge", key=f"judge:{e['id']}:e:{w['id']}", group=e["title"], title=f"你的判断「{e['title']}」：要验证的事件快到了——{w['text'].replace('（要人看）', '')}",
                                facts=[w.get("detail", "")], mean="这一条程序看不了，事件过后在对话里让 AI 查。", n10=None, hist="你的判断", date=d, live=False, us=True))
    return out


def block(D, R, write=False):
    cards = load()
    t = R["P"].index[-1]
    evs = [evaluate(c, D, R, t) for c in cards]
    its = items(evs, t)
    if write:
        write_log(evs, t)
    marks = {}
    for c in cards:
        for k in ("SOX", "SMH"):
            marks.setdefault(k, []).append([c["made"], "判断：" + c.get("short", c["title"][:6])])
            for tr in c.get("trades", []):
                marks[k].append([tr["date"], tr.get("label", "进出场")])
    return dict(cards=evs, items=its, marks=marks)
