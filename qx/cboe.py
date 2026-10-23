"""CBOE 期权数据（从旧终端 data/cboe.py 复制，2026-10-23 加了完整期权链存档；最早从旧项目 cboe.py 复制，只留认沽/认购比历史和期权链快照；主动买卖、持仓变化留到期权模块）

  1. 认沽/认购比日度历史：2006-11 到 2019-10 用 CBOE 历史 CSV，之后按天读每日统计 JSON。
     抓过的日子存进 data/pc_history.csv（休市日也记一行空的，下次不再抓），之后每次只补新的。
  2. 期权链快照（延迟 15 分钟）：30 天平值隐含波动、期限结构、25 delta 偏度、认沽认购成交比和持仓比。
     没有历史可下载，每个标的每天存一行到 data/options_history.csv。
"""
import csv, json, os, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

UA = {"User-Agent": "Mozilla/5.0"}
PC_CSV = {"equity": "equitypc", "index": "indexpc", "total": "totalpc"}
PC_JSON_NAME = {"equity": "EQUITY PUT/CALL RATIO", "index": "INDEX PUT/CALL RATIO", "total": "TOTAL PUT/CALL RATIO"}


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


CTX = _ctx()


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8")


# ---------------------------------------------------------------- 认沽/认购比历史
def _pc_from_csv(kind):
    txt = _get(f"https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/{PC_CSV[kind]}.csv")
    out = {}
    for line in txt.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 5 or not p[0][:1].isdigit():
            continue
        try:
            d = datetime.strptime(p[0], "%m/%d/%Y").strftime("%Y-%m-%d")
            out[d] = (float(p[1]), float(p[2]), float(p[4]))  # call, put, ratio
        except ValueError:
            pass
    return out


def _pc_from_json(d):
    try:
        j = json.loads(_get(f"https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options", timeout=20))
    except Exception:
        return d, None  # 休市日或还没发布（CBOE 对没有的文件回 403）
    row = {}
    ratios = {r["name"]: r["value"] for r in j.get("ratios", [])}
    for kind, name in PC_JSON_NAME.items():
        sec = {"equity": "EQUITY OPTIONS", "index": "INDEX OPTIONS", "total": "SUM OF ALL PRODUCTS"}[kind]
        vol = next((x for x in j.get(sec, []) if x.get("name") == "VOLUME"), None)
        try:
            row[kind] = (float(vol["call"]), float(vol["put"]), float(ratios[name])) if vol else None
        except (KeyError, TypeError, ValueError):
            row[kind] = None
    return d, row


def put_call_history(cache_path, log=print, until=None):
    """返回 {kind: [(date, ratio, call, put), ...]}，并更新 cache_path。until：最晚补到哪天（默认今天）。"""
    rows, tried = {}, set()
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                tried.add(r["date"])
                if r["equity"]:
                    rows[r["date"]] = {k: (float(r[k + "_call"]), float(r[k + "_put"]), float(r[k])) if r[k] else None for k in PC_CSV}
    else:
        log("  第一次运行：下载 2006–2019 年的认沽/认购比历史 CSV")
        hist = {k: _pc_from_csv(k) for k in PC_CSV}
        for d in hist["equity"]:
            rows[d] = {k: hist[k].get(d) for k in PC_CSV}
            tried.add(d)
    start = date(2019, 10, 5)
    today = date.fromisoformat(until) if until else date.today()
    todo = []
    d = start
    while d <= today:
        s = d.isoformat()
        if d.weekday() < 5 and s not in tried:
            todo.append(s)
        d += timedelta(days=1)
    # 最近 7 天里试过但没取到的再试一次（当天的数据收盘后才发布）
    recent = [x for x in sorted(tried) if x >= (today - timedelta(days=7)).isoformat() and x not in rows and x <= today.isoformat()]
    todo = sorted(set(todo) | set(recent))
    if todo:
        log(f"  补抓认沽/认购比 {len(todo)} 天" + ("（第一次会多花一两分钟）" if len(todo) > 50 else ""))
        with ThreadPoolExecutor(8) as ex:
            for d, row in ex.map(_pc_from_json, todo):
                tried.add(d)
                if row and row.get("equity"):
                    rows[d] = row
    tmp = cache_path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date"] + [c for k in PC_CSV for c in (k, k + "_call", k + "_put")])
        for d in sorted(tried):
            r = rows.get(d)
            if not r:
                w.writerow([d] + [""] * 9)
                continue
            line = [d]
            for k in PC_CSV:
                v = r.get(k)
                line += [v[2], v[0], v[1]] if v else ["", "", ""]
            w.writerow(line)
    os.replace(tmp, cache_path)
    out = {k: [] for k in PC_CSV}
    for d in sorted(rows):
        for k in PC_CSV:
            v = rows[d].get(k)
            if v and v[2] > 0:
                out[k].append((d, v[2], v[0], v[1]))
    return out


# ---------------------------------------------------------------- 期权链快照
def _parse(sym):
    tail = sym[-15:]       # ROOT + YYMMDD + C/P + 行权价×1000（8 位）
    return datetime.strptime(tail[:6], "%y%m%d").date(), tail[6], int(tail[7:]) / 1000


def _interp(points, x):
    pts = sorted(points)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0


def fetch_chain(sym):
    return json.loads(_get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json", timeout=60))


# 期权给出的概率和期权异动（2026-10-23 夜加，第三轮第 2 步"预期差"）
PROB_DTE = (20, 45)          # 用 20–45 天里最接近 30 天的那个到期日
PROB_LV = (-0.2, -0.1, 0.1, 0.2)   # 到期时跌破 / 涨过现价 ±10%、±20% 的概率
UNUSUAL_MIN = 1000           # 期权异动只看当天成交 ≥ 1000 张的合约（滤掉零星成交，不是触发线）
UNUSUAL_DTE = 7              # 只看 7 天以后到期的（快到期的深度实值合约多是平仓、行权和换月，没有信息）
UNUSUAL_TOP = 3              # 每个标的列前 3：虚值、当天成交超过原有未平仓（多半是新开仓），按成交金额排


def _ncdf(x):
    from math import erf, sqrt
    return 0.5 * (1 + erf(x / sqrt(2)))


def probs(opts_by_exp, spot):
    """风险中性概率（市场定价里"到期时在某价位以下 / 以上"的概率）：每个目标价用那个行权价附近的虚值期权隐含波动，P(S_T < K) = N(−d2)。
    忽略利率和偏度的二阶项，只作描述。返回 {dte, dn20, dn10, up10, up20, sd}。"""
    from math import log, sqrt
    cands = [d for d in opts_by_exp if PROB_DTE[0] <= d <= PROB_DTE[1]]
    if not cands or not spot:
        return None
    dte = min(cands, key=lambda d: abs(d - 30))
    otm = [(k, iv) for cp, k, iv, dl in opts_by_exp[dte] if (cp == "P" and k <= spot) or (cp == "C" and k >= spot)]
    if len(otm) < 6:
        return None
    T = dte / 365
    out = {"dte": dte}
    for x in PROB_LV:
        K = spot * (1 + x)
        iv = _interp(otm, K)
        if not iv:
            return None
        d2 = (log(spot / K) - 0.5 * iv * iv * T) / (iv * sqrt(T))
        below = _ncdf(-d2)
        out[("dn" if x < 0 else "up") + str(int(abs(x) * 100))] = round(below if x < 0 else 1 - below, 4)
    atm = _interp(otm, spot)
    out["sd"] = round(atm * sqrt(T), 4) if atm else None          # 到期前 ±1 倍的幅度
    return out


def chain_metrics(sym, j=None):
    j = j or fetch_chain(sym)
    D = j["data"]
    ts = datetime.strptime(j["timestamp"][:10], "%Y-%m-%d").date()
    spot = D.get("current_price") or D.get("close")
    by_exp = {}
    cv = pv = coi = poi = 0.0
    unusual = []
    for o in D["options"]:
        try:
            exp, cp, k = _parse(o["option"])
        except Exception:
            continue
        dte = (exp - ts).days
        vol, oi = o.get("volume") or 0, o.get("open_interest") or 0
        otm = (cp == "P" and k < spot) or (cp == "C" and k > spot)
        if vol >= UNUSUAL_MIN and spot and dte >= UNUSUAL_DTE and otm and vol > oi:
            mid = ((o.get("bid") or 0) + (o.get("ask") or 0)) / 2 or (o.get("last_trade_price") or 0)
            unusual.append({"exp": exp.isoformat(), "dte": dte, "cp": cp, "k": k, "m": round(k / spot - 1, 4), "vol": int(vol), "oi": int(oi),
                            "x": round(vol / max(oi, 1), 2), "usd": round(vol * mid * 100), "iv": round((o.get("iv") or 0) * 100, 1)})
        if cp == "C":
            cv += vol; coi += oi
        else:
            pv += vol; poi += oi
        iv = o.get("iv") or 0
        if dte < 2 or iv <= 0.01 or iv > 5:
            continue
        by_exp.setdefault(dte, []).append((cp, k, iv, o.get("delta") or 0))
    atm, skew = [], []
    for dte, opts in sorted(by_exp.items()):
        near = sorted(opts, key=lambda x: abs(x[1] - spot))[:4]
        if len(near) >= 2 and abs(near[0][1] / spot - 1) < 0.05:
            atm.append((dte, sum(x[2] for x in near[:2]) / 2 * 100))
        puts = [x for x in opts if x[0] == "P" and -0.40 < x[3] < -0.10]
        calls = [x for x in opts if x[0] == "C" and 0.10 < x[3] < 0.40]
        if puts and calls:
            p = min(puts, key=lambda x: abs(x[3] + 0.25)); c = min(calls, key=lambda x: abs(x[3] - 0.25))
            if abs(p[3] + 0.25) < 0.08 and abs(c[3] - 0.25) < 0.08:
                skew.append((dte, (p[2] - c[2]) * 100))
    iv30 = D.get("iv30") or _interp(atm, 30)
    iv_near, iv_3m = _interp(atm, 30), _interp(atm, 91)
    traded = (D.get("last_trade_time") or "")[:10] or ts.isoformat()   # 盘前抓到的是上一个交易日收盘的数据
    curve = [[(ts + timedelta(days=d)).isoformat(), d, round(v, 2)] for d, v in atm]     # 每个到期日的平值隐含波动（日历算事件定价幅度用）
    return {"symbol": sym, "date": traded, "spot": spot, "iv30": iv30, "curve": curve, "asof": ts.isoformat(),
            "term": (iv_near / iv_3m) if iv_near and iv_3m else None,      # > 1 = 近月比 3 个月贵
            "skew25": _interp(skew, 30),                                     # 25 delta 认沽 IV − 认购 IV，波动率点
            "pc_vol": pv / cv if cv else None, "pc_oi": poi / coi if coi else None, "vol": cv + pv,
            "prob": probs(by_exp, spot), "unusual": sorted(unusual, key=lambda u: -u["usd"])[:UNUSUAL_TOP]}


HIST_COLS = ["date", "symbol", "spot", "iv30", "term", "skew25", "pc_vol", "pc_oi", "vol", "p_dn20", "p_dn10", "p_up10", "p_up20", "p_dte", "p_sd"]


def read_history(hist_path):
    keep = {}
    if os.path.exists(hist_path):
        with open(hist_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keep[(r["date"], r["symbol"])] = r
    return keep


def option_snapshots(symbols, hist_path, log=print, latest_path=None, archive_dir=None):
    """抓期权链，每个标的每天一行存进 hist_path（同一天重复运行时覆盖）。返回当天的读数列表。
    archive_dir：另外把完整期权链原样存成 <archive_dir>/<代码>.json.gz（2026-10-23 加：完整链没有历史可下载，每天收盘后存一份）。"""
    out = []
    def one(s):
        try:
            txt = _get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{s[0]}.json", timeout=90)
            if archive_dir:
                import gzip
                os.makedirs(archive_dir, exist_ok=True)
                with gzip.open(os.path.join(archive_dir, f"{s[0]}.json.gz"), "wt", encoding="utf-8") as f:
                    f.write(txt)
            return chain_metrics(s[0], json.loads(txt))
        except Exception as e:
            log(f"  ! {s[0]} 期权链下载失败：{e}")
            return None
    with ThreadPoolExecutor(4) as ex:
        for (sym, name), m in zip(symbols, ex.map(one, symbols)):
            if m:
                m["name"] = name
                out.append(m)
    keep = read_history(hist_path)
    for m in out:
        pr = m.get("prob") or {}
        m.update({"p_dn20": pr.get("dn20"), "p_dn10": pr.get("dn10"), "p_up10": pr.get("up10"), "p_up20": pr.get("up20"), "p_dte": pr.get("dte"), "p_sd": pr.get("sd")})
        keep[(m["date"], m["symbol"])] = {c: ("" if m.get(c) is None else round(m[c], 4) if isinstance(m[c], float) else m[c]) for c in HIST_COLS}
    tmp = hist_path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HIST_COLS)
        w.writeheader()
        for k in sorted(keep):
            w.writerow({c: keep[k].get(c, "") for c in HIST_COLS})
    os.replace(tmp, hist_path)
    if latest_path:                       # 每个标的最近一次的到期日曲线（日历算"期权给这件事定价多少"用）；没取到的沿用上次
        try:
            with open(latest_path, encoding="utf-8") as f:
                latest = json.load(f)
        except Exception:
            latest = {}
        for m in out:
            if m.get("curve"):
                latest[m["symbol"]] = {k: m.get(k) for k in ("date", "asof", "spot", "iv30", "curve", "prob", "unusual")}
        with open(latest_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False)
        os.replace(latest_path + ".tmp", latest_path)
    return out
