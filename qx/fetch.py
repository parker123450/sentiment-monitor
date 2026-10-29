#!/usr/bin/env python3
"""下载（从旧终端 data/fetch.py 复制的 yahoo()、fred()、兜底和 keep_recent_gaps()，2026-10-23 改成两档）。

两档：
  quick()  每 15 分钟：要闻、预测市场、CNN 恐慌贪婪、盘中报价；美股盘中每 30 分钟存一行期权链摘要。
  daily()  市场收盘后：Yahoo 日线、FRED、认沽认购比、AAII（每周）；美股收盘后另存一份完整期权链（qx/cboe.py）。
每个序列单独下载、单独兜底：下载失败就沿用 data/raw/ 里存下的，状态记成 cached；从来没有过就是 missing（data/meta.json）。
"""
import csv, gzip, io, json, os, ssl, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qx import store, cboe                                     # noqa: E402
from qx.registry import SERIES, YAHOO, FRED, CHAIN_SYMBOLS, OPTIONS_FILE, LINKED  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0"}       # 完整的浏览器 UA（带 Chrome/...）没有 cookie 时会被 Yahoo 回 429，简短的反而正常
STATE = os.path.join(store.HERE, "state.json")


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


CTX = ssl_context()


def get(url, timeout=60, ua=UA):
    req = urllib.request.Request(url, headers=ua)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def yahoo(sym, since=None):
    p2 = int(time.time()) + 86400
    p1 = int(since) if since else 631152000   # 默认 1990-01-01
    q = urllib.parse.quote(sym)
    last = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?period1={p1}&period2={p2}&interval=1d&includePrePost=false"
        for attempt in range(3):
            try:
                j = json.loads(get(url))
                res = (j.get("chart") or {}).get("result")
                if res:
                    return res[0]
                last = "empty result"
                break
            except ssl.SSLError:
                raise
            except urllib.error.HTTPError as e:
                last = e
                time.sleep((5 if e.code == 429 else 1.5) * (attempt + 1))   # 429 = 限流，等久一点
            except Exception as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Yahoo 下载失败：{last}")


def yahoo_month(sym):
    """最近一个月的日线，补按 period 取的历史里漏掉的日子。
    2026-10-21 几十个品种的日线收盘价是空的（按 period、按 range 取都一样），但小时线有那一天：
    这种日子用当天的小时线拼一根日线（开 = 第一根开盘，高低 = 极值，收 = 最后一根小时线的收盘，量 = 相加），返回（行，补的日子）。"""
    q = urllib.parse.quote(sym)
    res = (json.loads(get(f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range=1mo&interval=1d")).get("chart") or {}).get("result")
    if not res:
        return [], []
    res = res[0]
    rows = rows_from(res)
    off = timedelta(seconds=(res.get("meta") or {}).get("gmtoffset", 0) or 0)
    have = {r[0] for r in rows}
    want = sorted({(datetime.fromtimestamp(t, tz=timezone.utc) + off).strftime("%Y-%m-%d") for t in res.get("timestamp") or []} - have)
    today = (datetime.now(timezone.utc) + off).strftime("%Y-%m-%d")
    want = [d for d in want if d < today and datetime.strptime(d, "%Y-%m-%d").weekday() < 5]   # 当天未收盘的、周末的不补
    if not want:
        return rows, []
    h = (json.loads(get(f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range=1mo&interval=1h")).get("chart") or {}).get("result")
    if not h:
        return rows, []
    h = h[0]
    hq = (h.get("indicators") or {}).get("quote", [{}])[0]
    hoff = timedelta(seconds=(h.get("meta") or {}).get("gmtoffset", 0) or 0)
    bars = {}
    for i, t in enumerate(h.get("timestamp") or []):
        d = (datetime.fromtimestamp(t, tz=timezone.utc) + hoff).strftime("%Y-%m-%d")
        c = (hq.get("close") or [None])[i] if i < len(hq.get("close") or []) else None
        if d in want and c is not None:
            g = lambda k: (hq.get(k) or [None] * (i + 1))[i]
            bars.setdefault(d, []).append((c, g("open"), g("high"), g("low"), g("volume") or 0))
    filled = []
    for d, b in bars.items():
        hi = [x[2] for x in b if x[2] is not None]
        lo = [x[3] for x in b if x[3] is not None]
        c = round(float(b[-1][0]), 6)
        rows.append([d, c, float(sum(x[4] for x in b)), b[0][1], max(hi) if hi else None, min(lo) if lo else None, c])
        filled.append(d)
    return sorted(rows, key=lambda x: x[0]), sorted(filled)


def live_day(res):
    """这根日线的交易日还没收盘（盘中抓的）：返回那天的日期（交易所当地），否则 None。
    按 meta.currentTradingPeriod.regular.end 判断，收盘后再留 15 分钟给数据源出收盘价。"""
    meta = res.get("meta") or {}
    end = (((meta.get("currentTradingPeriod") or {}).get("regular")) or {}).get("end")
    if not end or time.time() >= end + 15 * 60:
        return None
    off = timedelta(seconds=meta.get("gmtoffset", 0) or 0)
    return (datetime.fromtimestamp(end, tz=timezone.utc) + off).strftime("%Y-%m-%d")


def rows_from(res):
    """Yahoo 返回 → [[date, close, volume, open, high, low, adjclose]]，日期按交易所当地时间。
    还没收盘的那根日线不要（盘中价不能当收盘价写进 CSV：之后下载失败沿用旧数据时会被当成收盘）。"""
    live = live_day(res)
    ts = res.get("timestamp") or []
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    meta = res.get("meta") or {}
    off = timedelta(seconds=meta.get("gmtoffset", 0) or 0)
    mt = meta.get("regularMarketTime")
    mday = (datetime.fromtimestamp(mt, tz=timezone.utc) + off).strftime("%Y-%m-%d") if mt else None
    adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    out = {}
    for i, t in enumerate(ts):
        pick = lambda k: (q.get(k) or [None] * len(ts))[i] if i < len(q.get(k) or []) else None
        c = pick("close")
        d = (datetime.fromtimestamp(t, tz=timezone.utc) + off).strftime("%Y-%m-%d")
        if c is None and i == len(ts) - 1 and d == mday and meta.get("regularMarketPrice"):
            # Yahoo 偶尔把最新一根日线的收盘价留空（收盘后要过一阵才补），这时用同一天的最新成交价补上
            c = meta["regularMarketPrice"]
            q = dict(q)
            for k, mk in (("high", "regularMarketDayHigh"), ("low", "regularMarketDayLow"), ("volume", "regularMarketVolume")):
                if pick(k) is None and meta.get(mk) is not None:
                    q[k] = list(q.get(k) or [None] * len(ts)); q[k][i] = meta[mk]
        if c is None:
            continue
        if live and d >= live:
            continue
        a = adj[i] if i < len(adj) and adj[i] is not None else c
        out[d] = [d, round(float(c), 6), float(pick("volume") or 0), pick("open"), pick("high"), pick("low"), round(float(a), 6)]
    return [out[k] for k in sorted(out)]


def fred(series_id):
    """FRED 偶尔返回网页（限流或维护页），所以先校验表头和日期，不对就换个 User-Agent 重试。"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    last = None
    for attempt, ua in enumerate(("Mozilla/5.0", "Python-urllib/3", "trading-terminal/1.0 (personal research)")):
        try:
            lines = get(url, timeout=10 if attempt == 0 else 60, ua={"User-Agent": ua}).splitlines()   # 第一个请求头常常干等满超时（10-27 实测每个序列白等 60 秒），先试 10 秒
            if not lines or not lines[0].lower().startswith(("observation_date", "date")):
                raise ValueError("返回的不是数据表（可能是网页或限流）")
            rows = []
            for line in lines[1:]:
                p = line.strip().split(",")
                if len(p) >= 2 and len(p[0]) == 10 and p[0][4] == "-" and p[1] not in ("", "."):
                    try:
                        rows.append([p[0], float(p[1])])
                    except ValueError:
                        pass
            if len(rows) < 100:
                raise ValueError(f"只有 {len(rows)} 行，不像完整数据")
            return rows
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(last)


def keep_recent_gaps(new_rows, old_rows, days=45):
    """Yahoo 的全量历史偶尔漏掉最近的某一天（2026-10-22 全量下载时 30 多个品种都漏了 10-21）。
    全量替换历史时，缓存里有、这次没返回、又在最近 days 天以内的日子补回来（也包括比这次更新的那几天）。"""
    if not new_rows or not old_rows:
        return new_rows, 0
    got = {x[0] for x in new_rows}
    cut = (datetime.strptime(new_rows[-1][0], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    back = [x for x in old_rows if x[0] not in got and x[0] >= cut]
    return sorted(new_rows + back, key=lambda x: x[0]), len(back)


def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(st):
    store.write_atomic(STATE, json.dumps(st))


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fetch_yahoo(name, full, log):
    old = store.read_rows(name)
    since = None
    if not full and len(old) >= 250:
        since = datetime.strptime(old[-1][0], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() - 10 * 86400
    res = yahoo(name, since)
    live = live_day(res)
    rows = rows_from(res)
    official = {x[0] for x in rows}                           # 日线接口给了收盘价的日子
    if not rows:
        raise RuntimeError("没有返回数据")
    if live:
        old = [x for x in old if x[0] < live]                   # 以前盘中写进去的那根也不要
    nb = 0
    if since is not None or len(rows) < 0.9 * len(old):          # 增量，或者全量反而变短了：和存下的合并
        m = {x[0]: x for x in old}
        m.update((x[0], x) for x in rows)
        rows = [m[k] for k in sorted(m)]
    else:
        rows, nb = keep_recent_gaps(rows, old)
    filled = []
    try:
        got = {x[0] for x in rows}
        month, hourly = yahoo_month(name)
        official |= {x[0] for x in month if x[0] not in hourly}
        add = [x for x in month if x[0] not in got]
        if add:
            rows = sorted(rows + add, key=lambda x: x[0])
            nb += len(add)
            filled = [d for d in hourly if d not in got]
    except Exception:
        pass
    return rows, old, nb, filled, official




# ================================================================ 2026-10-23 新加：两档下载
BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
AAII_URL = "https://www.aaii.com/files/surveys/sentiment.xls"
PRIVATE = os.path.join(store.HERE, "private")          # 不公开的文件（AAII 历史、以后的判断）：云端加密后才进仓库（qx/crypt.py）
AAII_CSV = os.path.join(PRIVATE, "aaii.csv")
CNN_CSV = os.path.join(store.HERE, "cnn.csv")
INTRADAY = os.path.join(store.HERE, "intraday.json")
PC_HIST = os.path.join(store.HERE, "pc_history.csv")
# 盘中报价：美股主要指数、关注的个股、联动市场（第 2 步"今天要知道的"盘中版用；现在只存）
QUOTES = ["^SOX", "SMH", "^NDX", "^GSPC", "IWM", "^VIX", "^VXN", "NVDA", "MU", "TSM", "AVGO", "AMD"] + [s for s, _ in LINKED]


def get_bytes(url, timeout=60, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def _record(meta, name, status, rows=None, warn=None, err=None, source=None):
    m = meta.setdefault(name, {})
    m.update({"status": status, "source": source or (SERIES[name]["source"] if name in SERIES else "")})
    if status == "ok":
        m["fetched"] = now_iso()
    if rows:
        m["first"], m["last"], m["rows"] = rows[0][0], rows[-1][0], len(rows)
    m["warn"] = warn or []
    if err:
        m["error"] = str(err)[:200]
    else:
        m.pop("error", None)


def daily(log=print, only=None, full=None):
    """日线、FRED、认沽认购比、AAII。only：只下载这些序列（亚洲收盘后只更新联动市场）。"""
    meta = store.read_meta()
    st = read_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if full is None:
        full = only is None and st.get("full_day") != today      # 每天第一次全量（拆股、分红后 Yahoo 会改写历史），之后只补最近 10 天
    names = [k for k in YAHOO if only is None or k in only]
    log(f"Yahoo 日线（{'全量' if full else '只补最近 10 天'}）{len(names)} 个：")

    def one(name):
        try:
            return name, fetch_yahoo(name, full, log), None
        except ssl.SSLError:
            raise
        except Exception as e:
            return name, None, e

    ok_n = 0
    with ThreadPoolExecutor(4) as ex:
        for name, res, err in ex.map(one, names):
            try:
                if err:
                    raise err
                rows, old, nb, filled, official = res
                warn = store.validate(name, rows, old)
                m0 = meta.get(name, {})
                hourly = sorted((set(m0.get("hourly", [])) | set(filled)) - official)
                if hourly:
                    meta.setdefault(name, {})["hourly"] = hourly
                else:
                    meta.get(name, {}).pop("hourly", None)
                if any("短很多" in w or "日期" in w for w in warn):
                    raise RuntimeError("；".join(warn))
                store.write_rows(name, rows)
                _record(meta, name, "ok", rows, warn)
                ok_n += 1
            except Exception as e:
                old = store.read_rows(name)
                _record(meta, name, "cached" if old else "missing", old, err=e)
                log(f"  ! {name} {str(e)[:120]}；" + (f"沿用存下的（截至 {old[-1][0]}）" if old else "也没有存过的"))
    log(f"  取到 {ok_n}/{len(names)}")
    if full and ok_n >= len(names) - 3:
        st["full_day"] = today
        write_state(st)

    if only is None:
        log("FRED：")
        dead = False
        for name in FRED:
            try:
                if dead:
                    raise RuntimeError("FRED 连不上，这次跳过")
                rows = fred(name)
                old = store.read_rows(name)
                if old and rows and rows[0][0] > old[0][0]:
                    # FRED 的 ICE 利差 2026 年 4 月起只给最近 3 年：新的从更晚开始时和存下的合并（重叠的日子以新的为准），不丢更早的历史
                    m = {r[0]: r for r in old}
                    m.update({r[0]: r for r in rows})
                    rows = [m[k] for k in sorted(m)]
                warn = store.validate(name, rows, old)
                if any("短很多" in w or "日期" in w for w in warn):
                    raise RuntimeError("；".join(warn))
                store.write_rows(name, rows)
                _record(meta, name, "ok", rows, warn)
                log(f"  {name:<14} {len(rows):>6} 天  → {rows[-1][0]}")
            except Exception as e:
                dead = dead or any(w in str(e) for w in ("urlopen error", "timed out", "Name or service", "Connection refused", "Network is unreachable"))
                old = store.read_rows(name)
                _record(meta, name, "cached" if old else "missing", old, err=e)
                log(f"  ! {name} {str(e)[:80]}；" + (f"沿用存下的（截至 {old[-1][0]}）" if old else "也没有存过的"))

        log("CBOE 认沽认购比：")
        try:
            pc = cboe.put_call_history(PC_HIST, log=log)
            rows = [[d, r] for d, r, _, _ in pc["equity"]]
            old = store.read_rows("PC_EQ")
            warn = store.validate("PC_EQ", rows, old)
            if not rows or any("短很多" in w for w in warn):
                raise RuntimeError("；".join(warn) or "没有数据")
            store.write_rows("PC_EQ", rows)
            _record(meta, "PC_EQ", "ok", rows, warn)
            log(f"  PC_EQ  {len(rows)} 天 → {rows[-1][0]}")
        except Exception as e:
            old = store.read_rows("PC_EQ")
            _record(meta, "PC_EQ", "cached" if old else "missing", old, err=e)
            log(f"  ! PC_EQ {e}")

        try:
            aaii(log, meta)
        except Exception as e:
            meta["_aaii"] = {"status": "cached", "error": str(e)[:200], "tried": now_iso()}
            log(f"  ! AAII {str(e)[:120]}（沿用存下的）")
    store.write_meta(meta)
    return {"ok": ok_n, "n": len(names)}


def aaii(log, meta):
    """AAII 散户多空调查（每周四公布）。网站有反爬，取不到就沿用存下的历史，页面标"这周没取到"。"""
    rows = {}
    if os.path.exists(AAII_CSV):
        with open(AAII_CSV, encoding="utf-8") as f:
            rows = {r["date"]: r for r in csv.DictReader(f)}
    last = max(rows) if rows else None
    now = datetime.now(timezone.utc)
    if last and (now - datetime.fromisoformat(last).replace(tzinfo=timezone.utc)).days < 7:
        log(f"AAII：最新 {last}，不到一周，不用取")
        return
    b = get_bytes(AAII_URL, headers=BROWSER)
    if not b.startswith(b"\xd0\xcf\x11\xe0"):
        raise RuntimeError("网站拦了（返回的不是 xls）")
    import pandas as pd
    x = pd.read_excel(io.BytesIO(b), sheet_name="SENTIMENT", header=None)
    x = x[pd.to_datetime(x[0], errors="coerce").notna()].copy()
    x["date"] = pd.to_datetime(x[0])
    x = x.set_index("date")[[1, 2, 3]].apply(pd.to_numeric, errors="coerce").dropna()
    for d, r in x.iterrows():
        rows[d.strftime("%Y-%m-%d")] = {"date": d.strftime("%Y-%m-%d"), "bull": r[1], "neutral": r[2], "bear": r[3]}
    write_aaii(rows)
    meta["_aaii"] = {"status": "ok", "fetched": now_iso(), "last": max(rows)}
    log(f"AAII：{len(rows)} 周，最新 {max(rows)}")


def write_aaii(rows):
    os.makedirs(PRIVATE, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["date", "bull", "neutral", "bear"])
    w.writeheader()
    for k in sorted(rows):
        w.writerow({c: rows[k][c] for c in ["date", "bull", "neutral", "bear"]})
    store.write_atomic(AAII_CSV, buf.getvalue())


def cnn(log=print):
    """CNN 恐慌贪婪：最新读数写 data/cnn.csv（每天一行，盘中会被覆盖，收盘后定下来）；第一次用它给的一年历史打底。"""
    j = json.loads(get(CNN_URL, ua=dict(BROWSER, Referer="https://www.cnn.com/", Origin="https://www.cnn.com")))
    fg = j["fear_and_greed"]
    rows = {}
    if os.path.exists(CNN_CSV):
        with open(CNN_CSV, encoding="utf-8") as f:
            rows = {r["date"]: r for r in csv.DictReader(f)}
    for p in ((j.get("fear_and_greed_historical") or {}).get("data") or []):
        d = datetime.fromtimestamp(p["x"] / 1000, timezone.utc).strftime("%Y-%m-%d")
        rows.setdefault(d, {"date": d, "score": round(float(p["y"]), 1), "rating": p.get("rating", "")})
    d = fg["timestamp"][:10]
    rows[d] = {"date": d, "score": round(float(fg["score"]), 1), "rating": fg.get("rating", "")}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["date", "score", "rating"])
    w.writeheader()
    for k in sorted(rows):
        w.writerow(rows[k])
    store.write_atomic(CNN_CSV, buf.getvalue())
    log(f"CNN 恐慌贪婪：{fg['score']:.0f}（{fg.get('rating')}），{fg['timestamp'][:16]}")
    return fg


def intraday(log=print):
    """盘中报价（最新价、昨收、涨跌、是不是盘中）。只存最新一份。"""
    def one(sym):
        try:
            q = urllib.parse.quote(sym)
            r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range=1d&interval=15m"))["chart"]["result"][0]
            m = r.get("meta") or {}
            p, pc = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
            reg = ((m.get("currentTradingPeriod") or {}).get("regular")) or {}
            live = bool(reg.get("start") and reg.get("end") and reg["start"] <= time.time() <= reg["end"])
            return sym, {"p": p, "pc": pc, "chg": round((p / pc - 1) * 100, 2) if p and pc else None,
                         "t": datetime.fromtimestamp(m.get("regularMarketTime") or 0, timezone.utc).isoformat(timespec="minutes"),
                         "hi": m.get("regularMarketDayHigh"), "lo": m.get("regularMarketDayLow"), "live": live}
        except Exception as e:
            return sym, {"error": str(e)[:80]}
    with ThreadPoolExecutor(4) as ex:
        quotes = dict(ex.map(one, QUOTES))
    store.write_atomic(INTRADAY, json.dumps({"fetched": now_iso(), "quotes": quotes}, ensure_ascii=False))
    bad = [k for k, v in quotes.items() if "error" in v]
    log(f"盘中报价：{len(quotes) - len(bad)}/{len(quotes)}" + (f"（没取到 {' '.join(bad)}）" if bad else ""))


EARN_CHAIN_DAYS, EARN_CHAIN_KEEP = 5, 40


def earn_chain_symbols(today=None):
    """未来 5 个交易日发财报、市值 ≥ 2,000 亿美元（events.BIG_CAP）、不在常驻名单里的公司（口径十四.9）。"""
    import pandas as pd
    from qx import clock, events as EV
    d0 = pd.Timestamp(today or datetime.now(timezone.utc).astimezone(clock.NY).date())
    end = d0 + pd.tseries.offsets.BDay(EARN_CHAIN_DAYS)
    have = {s for s, _ in CHAIN_SYMBOLS}
    out = {}
    for e in EV.load().get("events", []):
        if e.get("kind") == "earnings" and e.get("sym") and (e.get("cap") or 0) >= EV.BIG_CAP and d0 < pd.Timestamp(e["date"]) <= end and e["sym"] not in have:
            out.setdefault(e["sym"], e.get("name") or e["sym"])
    return sorted(out.items())


def options(log=print, archive_dir=None):
    """期权链：每个标的一行摘要（同一天覆盖，收盘后定下来）；archive_dir 不为空时同时把完整期权链存成 gz（收盘后一天一次）。
    收盘后那一次另外取未来 5 个交易日发财报的大市值公司（摘要存 options_earn.csv，到期日曲线进 chains_latest.json 给日历、第 5 类卡用，完整链和常驻的一起存档；口径十四.9）。"""
    latest = os.path.join(store.HERE, "chains_latest.json")
    snaps = cboe.option_snapshots(CHAIN_SYMBOLS, os.path.join(store.HERE, OPTIONS_FILE), log=log, latest_path=latest, archive_dir=archive_dir)
    log("期权链：" + " ".join(f"{m['symbol']} iv30={m['iv30']:.1f}" for m in snaps if m.get("iv30")))
    if archive_dir:
        try:
            extra = earn_chain_symbols()
            if extra:
                more = cboe.option_snapshots(extra, os.path.join(store.HERE, "options_earn.csv"), log=log, latest_path=latest, archive_dir=archive_dir)
                log(f"期权链（财报前的大市值公司）：{len(more)}/{len(extra)} 个")
            _prune_chains(latest)
        except Exception as e:
            log(f"  ! 财报前的期权链出错：{type(e).__name__}")
    return snaps


def _prune_chains(p, keep=EARN_CHAIN_KEEP):
    """chains_latest.json 里不在常驻名单、最近一次已经是 40 天以前的去掉（财报前才取的那些，不让文件一直变大）。"""
    import pandas as pd
    try:
        j = json.load(open(p, encoding="utf-8"))
    except Exception:
        return
    have = {s for s, _ in CHAIN_SYMBOLS}
    cut = (pd.Timestamp.now() - pd.Timedelta(days=keep)).strftime("%Y-%m-%d")
    k = {s: v for s, v in j.items() if s in have or str(v.get("date") or v.get("asof") or "")[:10] >= cut}
    if len(k) < len(j):
        store.write_atomic(p, json.dumps(k, ensure_ascii=False))


def quick(log=print, opt=False, archive_dir=None, cal=False, fund=False):
    """每 15 分钟：要闻、预测市场、CNN、盘中报价；opt=True 时加期权链。每样单独兜底。"""
    meta = store.read_meta()
    jobs = [("_news", "要闻", lambda: __import__("qx.news", fromlist=["fetch"]).fetch(log=log)),
            ("_polymarket", "预测市场", lambda: __import__("qx.polymarket", fromlist=["snapshot"]).snapshot(log=log)),
            ("_cnn", "CNN", lambda: cnn(log)),
            ("_intraday", "盘中报价", lambda: intraday(log))]
    if opt:
        jobs.append(("_options", "期权链", lambda: options(log, archive_dir)))
    if cal:
        jobs.append(("_calendar", "日历", lambda: __import__("qx.events", fromlist=["fetch"]).fetch(log=log)))
    if fund:
        jobs.append(("_taiwan", "台湾月营收", lambda: __import__("qx.fundamentals", fromlist=["taiwan"]).taiwan(log=log)))
        jobs.append(("_earnings", "财报超预期", lambda: __import__("qx.fundamentals", fromlist=["earnings"]).earnings(log=log)))
    for key, name, fn in jobs:
        try:
            fn()
            meta[key] = {"status": "ok", "fetched": now_iso()}
        except Exception as e:
            meta[key] = {"status": "cached", "error": str(e)[:200], "tried": now_iso()}
            log(f"  ! {name}没取到（沿用上次的）：{str(e)[:120]}")
    store.write_meta(meta)
    return meta
