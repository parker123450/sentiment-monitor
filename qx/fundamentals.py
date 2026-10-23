"""基本面的两样免费数据（第 5 步判断卡"盈利预期"那一环用，2026-10-23；从旧终端 data/taiwan.py、data/earnings.py 改来）。

  台湾上市公司月营收：证交所开放数据 https://openapi.twse.com.tw/v1/opendata/t187ap05_L（只给最新一个月；每月 10 号前后公布上个月的）。
      关注的几家（台积电、联电、联发科、日月光、台达电、鸿海、广达、纬创）每月一行，攒进 data/tw_revenue.csv。
  财报超预期：纳斯达克 https://api.nasdaq.com/api/company/<代码>/earnings-surprise（每家最近 4 个季度的实际 / 预期每股盈利）。
      关注的半导体公司，写进 data/earnings.json。
每天取一次（run.py 按时间判断）。取不到就沿用上次的。
"""
import csv, json, os, time
from datetime import datetime, timezone

from qx import store

TW_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TW_CSV = os.path.join(store.HERE, "tw_revenue.csv")
TW = {"2330": "台积电", "2303": "联电", "2454": "联发科", "3711": "日月光", "2308": "台达电", "2317": "鸿海", "2382": "广达", "3231": "纬创"}
TW_COLS = ["ym", "pub", "code", "name", "rev", "mom", "yoy", "ytd_yoy"]
ER_URL = "https://api.nasdaq.com/api/company/{}/earnings-surprise"
ER_JSON = os.path.join(store.HERE, "earnings.json")
ER_WATCH = ["NVDA", "AVGO", "AMD", "MU", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "TXN", "QCOM", "ADI", "MRVL", "INTC", "NXPI", "ON", "MCHP", "TER"]
JSON_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _n(x):
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def taiwan(log=print):
    from qx.fetch import get
    j = json.loads(get(TW_URL, timeout=60))
    rows = {}
    if os.path.exists(TW_CSV):
        with open(TW_CSV, encoding="utf-8") as f:
            rows = {(r["ym"], r["code"]): r for r in csv.DictReader(f)}
    n = 0
    for r in j:
        code = str(r.get("公司代號", "")).strip()
        if code not in TW:
            continue
        ym = str(r["資料年月"]).strip()
        ym = f"{int(ym[:-2]) + 1911}-{ym[-2:]}"
        pub = str(r.get("出表日期", "")).strip()
        pub = f"{int(pub[:-4]) + 1911}-{pub[-4:-2]}-{pub[-2:]}" if len(pub) >= 6 else ""
        rows[(ym, code)] = {"ym": ym, "pub": pub, "code": code, "name": TW[code], "rev": _n(r.get("營業收入-當月營收")),
                            "mom": _n(r.get("營業收入-上月比較增減(%)")), "yoy": _n(r.get("營業收入-去年同月增減(%)")), "ytd_yoy": _n(r.get("累計營業收入-前期比較增減(%)"))}
        n += 1
    tmp = TW_CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TW_COLS)
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    os.replace(tmp, TW_CSV)
    log(f"台湾月营收：{n} 家")


def earnings(log=print):
    from qx.fetch import get
    try:
        old = json.load(open(ER_JSON, encoding="utf-8")).get("rows", {})
    except Exception:
        old = {}
    rows, ok = {}, 0
    for s in ER_WATCH:
        try:
            j = json.loads(get(ER_URL.format(s), timeout=30, ua=JSON_UA))
            t = (((j.get("data") or {}).get("earningsSurpriseTable") or {}).get("rows")) or []
            rows[s] = [{"d": datetime.strptime(r["dateReported"], "%m/%d/%Y").strftime("%Y-%m-%d"), "eps": _n(r.get("eps")),
                        "cons": _n(r.get("consensusForecast")), "surp": _n(r.get("percentageSurprise"))} for r in t if r.get("dateReported")]
            ok += 1
        except Exception as e:
            if s in old:
                rows[s] = old[s]
            log(f"  ! {s} 财报没取到（沿用上次）：{str(e)[:60]}")
        time.sleep(0.3)
    store.write_atomic(ER_JSON, json.dumps({"fetched": datetime.now(timezone.utc).isoformat(timespec="minutes"), "rows": rows}, ensure_ascii=False))
    log(f"财报超预期：{ok}/{len(ER_WATCH)} 家")


def load_tw():
    if not os.path.exists(TW_CSV):
        return []
    with open(TW_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_er():
    try:
        return json.load(open(ER_JSON, encoding="utf-8")).get("rows", {})
    except Exception:
        return {}
