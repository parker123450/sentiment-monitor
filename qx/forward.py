"""前瞻（第四轮第 5 步，2026-10-27）。规则在 口径.md 第十三节。

lines(D, t, ctx)      六条线，每条三栏：先变的小信号（第 3 步自动填）、现在怎么样（几个读数）、接下来的检验（时间轴里 30 天内的）。
scenarios(D, t)       三种走向：事先登记的假设（加密在 cards/scenarios/*.enc，原文在仓库旁边的 ../判断/scenarios/），每种 2–4 个"先看到什么"的信号。
                      写成规则的每天自动查（第一次亮的日子记进 data/private/scenario_log.json，推送）；写不成规则的标"要人看"。
                      三种走向只查哪条先出现、结果记进样本外记录；它们不改雷达的任何规则。
"""
import glob, json, os

import numpy as np
import pandas as pd

from qx import crypt, store, smallsignal as SS, narrative as NR, timeline as TL, ledger as LG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCEN_DIR = os.path.join(ROOT, "cards", "scenarios")
SCEN_SRC = os.path.join(os.path.dirname(ROOT), "判断", "scenarios")
SCEN_LOG = os.path.join(store.HERE, "private", "scenario_log.json")
LINES = [("rates", "利率和流动性"), ("industry", "产业进度"), ("geo", "地缘和政策"), ("credit", "融资和信用"), ("positioning", "仓位和资金"), ("narrative", "情绪和叙事")]
SIG_LINE = {"rates": {"^IRX", "^FVX", "^TNX", "^TYX", "TLT", "^MOVE", "JGB10", "JGB30", "JPY=X", "DX-Y.NYB", "EURUSD=X", "AUDUSD=X", "TWD=X", "KRW=X", "CNH=X"},
            "credit": {"BAMLH0A2HYB", "BAMLH0A1HYBB", "BAMLH0A3HYC", "BAMLC0A4CBBB", "BAMLC0A0CM", "HYG/IEF", "HYG", "LQD"},
            "geo": {"CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F", "^OVX", "^GVZ", "ZC=F", "ZS=F", "ZW=F"}}
NEXT_KIND = {"rates": {"fomc", "boj", "pce", "macro"}, "industry": {"earnings"}, "geo": {"manual"}, "credit": {"earnings"},
             "positioning": {"opex"}, "narrative": {"earnings", "gdp"}}


# ================================================================ 六条线
def lines(D, t, ctx):
    t = pd.Timestamp(t)
    sig, pos, narr, cards = ctx.get("sig") or {}, ctx.get("pos") or {}, ctx.get("narr") or {}, ctx.get("cards") or {}
    tl = TL.load().get("events", [])
    soon = [e for e in tl if t.strftime("%Y-%m-%d") <= e["date"] <= (t + pd.Timedelta(days=30)).strftime("%Y-%m-%d")]
    out = []
    for lid, nm in LINES:
        s_ = [x["text"] + f"（{x['level']}）" for x in sig.get("signals", []) if x["k"] in SIG_LINE.get(lid, set())]
        now = []
        if lid == "rates":
            for k, n_ in (("^TNX", "10 年美债"), ("^TYX", "30 年美债"), ("^MOVE", "美债波动"), ("JPY=X", "美元兑日元")):
                s, bp = SS.series(D, k, t)
                if s is not None and len(s) > 21:
                    now.append(f"{n_} {s.iloc[-1]:.2f}，20 日" + (f"{(s.iloc[-1] - s.iloc[-21]) * 100:+.0f} 个基点" if k in ("^TNX", "^TYX") else f"{(s.iloc[-1] / s.iloc[-21] - 1) * 100:+.1f}%"))
            j, _ = SS.series(D, "JGB30", t)
            if j is not None and len(j):
                now.append(f"日本 30 年国债 {j.iloc[-1]:.2f}%（{j.index[-1].strftime('%m-%d')}）")
            for a in LG.auctions(t)[:2]:
                now.append(f"{a['term']} 拍卖投标倍数 {a['btc']:.2f}，同期限历史里 {a['pos'] * 100:.0f}% 的位置（{a['date']}）")
        elif lid == "industry":
            for r in LG.rows(D, t):
                if r["chain"] in ("芯片", "资本开支预期", "AI 需求") and not r["value"].startswith("缺"):
                    now.append(f"{r['name']}：{r['value']}（{r['asof']}，{r['src']}）")
            s_ += [f"推演链 {c['name']} 走到第 {c['step']}/{c['of']} 环" + (f"，下一环 {c['next']['name']}" if c["next"] else "") for c in sig.get("chains", []) if c["id"] == "ai_fin"]
            s_ += [f"{m['name']} 营收和股价对不上（只作描述）" for m in sig.get("mismatch", [])]
        elif lid == "geo":
            for k, n_ in (("CL=F", "原油"), ("GC=F", "黄金"), ("^OVX", "原油波动")):
                s, _ = SS.series(D, k, t)
                if s is not None and len(s) > 21:
                    now.append(f"{n_} {s.iloc[-1]:,.2f}，20 日 {(s.iloc[-1] / s.iloc[-21] - 1) * 100:+.1f}%")
            s_ += [f"{c['name']} 推演链走到第 {c['step']}/{c['of']} 环" for c in sig.get("chains", []) if c["id"] == "oil" and c["step"]]
        elif lid == "credit":
            for b in narr.get("baskets", []):
                for p in b.get("pairs", []):
                    if p["id"].startswith("BAML") and p["level"] != "平常":
                        now.append(f"{p['name']} 20 日{p['chg']:+.0f} 个基点（{p['level']}）")
            for r in LG.rows(D, t):
                if r["chain"] in ("neocloud 信用", "云大厂融资"):
                    now.append(f"{r['name']} {r['value']}（{r['asof']}）")
            now = list(dict.fromkeys(now))
            s_ += [c["title"] for c in cards.get("cards", []) if c["cls"] == 2]
        elif lid == "positioning":
            now = [f"{c['market']}{c['word']}" for c in pos.get("crowd", []) if c["word"] in ("挤在多头", "挤在空头")] or ["没有挤在一边的市场"]
            s_ += [c["title"] for c in cards.get("cards", []) if c["cls"] in (1, 3)]
        elif lid == "narrative":
            if narr.get("main"):
                now.append(f"主线：{narr['main']['name']}")
            else:
                L = next((b for b in narr.get("baskets", []) if b["id"] == narr.get("lead")), None)
                now.append("没有认出主线" + (f"（领跌：{L['name']}）" if L else ""))
            for r in ((narr.get("heat") or {}).get("rows") or [])[:2]:
                now.append(f"热度：{r['topic']} {r['ratio']} 倍（只作描述）")
            g = ((cards.get("replay") or {}).get("tally4") or {})
            if g:
                q = sorted(g)[-1]
                now.append(f"{q}：好消息不涨 {g[q]['好消息不涨']} 家、坏消息不跌 {g[q]['坏消息不跌']} 家（{g[q]['家数']} 家发财报）")
        nxt = [f"{e['bj']} {e['title']}" for e in soon if e["kind"] in NEXT_KIND.get(lid, set())]
        if lid == "industry":
            nxt = [f"{e['bj']} {e['title']}" for e in soon if e["kind"] == "earnings" and e.get("sym") in {"MSFT", "GOOGL", "AMZN", "META", "NVDA", "ORCL", "CRWV", "AVGO", "TSM", "MU", "AMD"}]
        out.append(dict(id=lid, name=nm, signals=s_[:6], now=now[:6], next=nxt[:6]))
    return out


# ================================================================ 三种走向
def _load_scen():
    key = crypt.data_key()
    if not key:
        return []
    return [json.loads(crypt.unseal(open(p, "rb").read(), key)) for p in sorted(glob.glob(os.path.join(SCEN_DIR, "*.enc")))]


def seal():
    """仓库旁边 ../判断/scenarios/*.json（原文，不进仓库）→ cards/scenarios/*.enc（加密，进仓库）。"""
    key = crypt.data_key()
    os.makedirs(SCEN_DIR, exist_ok=True)
    out = []
    for p in sorted(glob.glob(os.path.join(SCEN_SRC, "*.json"))):
        j = json.load(open(p, encoding="utf-8"))
        dst = os.path.join(SCEN_DIR, j["id"] + ".enc")
        open(dst, "wb").write(crypt.seal(json.dumps(j, ensure_ascii=False).encode("utf-8"), key))
        out.append(dst)
    return out


def _check(D, t, c, narr_res):
    """一个信号今天亮没亮：→ (True / False / None 写不成规则, 说明)"""
    k = c["type"]
    if k == "manual":
        return None, "要人看：" + c["text"]
    if k == "no_new_high":
        s, _ = SS.series(D, c["series"], t)
        if s is None or len(s) < c["lookback"] + 1:
            return False, "数据不够"
        w = s.iloc[-c["lookback"]:]
        ago = len(w) - 1 - int(np.argmax(w.values))
        return ago >= c["quiet"], f"{c['name']}最近 {c['lookback']} 天的高点在 {ago} 天前"
    if k in ("chg", "chg_not"):
        s, bp = SS.series(D, c["series"], t)
        if s is None or len(s) < SS.MIN_DAYS + c["n"]:
            return False, "数据不够"
        ch = SS.change(s, bp, c["n"])
        f = SS.rarity(ch)
        hit = f is not None and f <= 0.05 and ((ch.iloc[-1] > 0) == (c["dir"] == "up"))
        return (hit if k == "chg" else not hit), f"{c['name']} {c['n']} 日变化在历史里 {f * 100:.1f}% 的位置" if f is not None else "数据不够"
    if k == "basket_z":
        b = next((x for x in narr_res["baskets"] if x["id"] == c["basket"]), None)
        if not b:
            return False, "篮子没数"
        hit = b["z"] <= c["thr"] if c["op"] == "<=" else b["z"] >= c["thr"]
        return hit, f"{b['name']} 20 日折算 {b['z']:+.2f}"
    if k == "flash_first":
        from qx import flash
        start = (pd.Timestamp(t, tz="UTC") - pd.Timedelta(days=c["days"])).isoformat()
        end = (pd.Timestamp(t, tz="UTC") + pd.Timedelta(days=1)).isoformat()
        hits = [r for r in flash.load_rows() if start <= flash.visible(r) < end and any(f"{e}:{c['line']}" in r["first"].split("|") for e in c["ents"])]
        return bool(hits), (hits[0]["t"][:60] if hits else "最近没有")
    return False, "不认识的规则"


def scenarios(D, t, narr_res=None, write=False):
    t = pd.Timestamp(t)
    narr_res = narr_res or NR.compute(D, t)
    try:
        log = json.load(open(SCEN_LOG, encoding="utf-8"))
    except Exception:
        log = {}
    first, state, pre = log.setdefault("first", {}), log.setdefault("state", {}), log.setdefault("pre", {})
    out, new = [], []
    for S in _load_scen():
        if t.strftime("%Y-%m-%d") < S.get("since", "2026-10-27"):
            continue
        ways = []
        for w in S["ways"]:
            sigs = []
            for i, c in enumerate(w["signals"]):
                hit, why = _check(D, t, c, narr_res)
                key = f"{S['id']}:{w['id']}:{i}"
                prev = state.get(key)
                if prev is None and hit:                      # 第一次查就已经成立：记成"登记时已亮"，不算先出现
                    pre[key] = t.strftime("%Y-%m-%d")
                elif hit and prev is False and key not in first:   # 登记以后从不成立变成成立，才算这条走向的信号先出现
                    first[key] = t.strftime("%Y-%m-%d")
                    new.append(dict(key="scen:" + key, title=f"三种走向 · {S['name']}：{w['name']}的信号先出现", body=f"{c.get('name', '')}：{why}"))
                if hit is not None:
                    state[key] = bool(hit)
                sigs.append(dict(text=c.get("text") or c.get("name", ""), hit=hit, why=why, first=first.get(key), pre=pre.get(key)))
            firsts = [s_["first"] for s_ in sigs if s_["first"]]
            ways.append(dict(id=w["id"], name=w["name"], how=w["how"], signals=sigs, lit=sum(1 for s_ in sigs if s_["hit"]), first=min(firsts) if firsts else None))
        lead = min((w for w in ways if w["first"]), key=lambda w: w["first"], default=None)
        out.append(dict(id=S["id"], name=S["name"], since=S["since"], ways=ways, lead=lead and lead["name"], note=S.get("note", "")))
    if write:
        os.makedirs(os.path.dirname(SCEN_LOG), exist_ok=True)
        store.write_atomic(SCEN_LOG, json.dumps(log, ensure_ascii=False))
    return out, new


def block(D, t, ctx, write=False):
    sc, new = scenarios(D, t, ctx.get("narr"), write=write)
    tl = TL.load()
    return dict(asof=pd.Timestamp(t).strftime("%Y-%m-%d"), lines=lines(D, t, ctx), scenarios=sc, new=new, written=bool(write),
                timeline=dict(events=tl.get("events", []), missing=tl.get("missing", []), built=tl.get("built")), ledger=LG.rows(D, t))
