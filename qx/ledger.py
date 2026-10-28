"""AI 账本和前瞻用的慢数据（第四轮第 5 步，2026-10-27）。规则在 口径.md 第十三节。

只做能免费自动化、不用从新闻里抽数字的（原则 4）。每个数带来源、时点、下次公布日：
  台积电月营收        证交所开放数据（面板原有，qx/fundamentals.py；每月 10 号前后公布上个月）
  FactSet 每周盈利    insight.factset.com 每周五前后的"S&P 500 Earnings Season Update"：混合盈利增速、超预期比例、预期市盈率（按固定句式取，取不到写"没取到"）
  Ramp AI 指数        FRED RAMPAIALL（月度）
  信用利差            FRED 单 B、BB、投资级
  美债拍卖            财政部 Fiscal Data（TreasuryDirect 的 robots.txt 全挡，用这个）：投标倍数和自己历史比
  财政部账户、准备金、逆回购  FRED WTREGEN、WRESBAL（周度）、RRPONTSYD（日度）
  云厂商资本开支和现金流  SEC XBRL companyfacts，要联系邮箱（SEC_CONTACT），没有就标"缺"
存 data/factset.csv、data/auctions.csv（带 pub）。
"""
import csv, html, json, os, re, time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from qx import store

FACTSET_CSV = os.path.join(store.HERE, "factset.csv")
AUCTION_CSV = os.path.join(store.HERE, "auctions.csv")
UA_NAMED = {"User-Agent": "qx-radar/1.0 (+https://github.com/parker123450/sentiment-monitor)"}
FS_RSS = "https://insight.factset.com/rss.xml"
FISCAL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"


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


def _num(rx, t):
    m = re.search(rx, t, re.I)
    return float(m.group(1)) if m else ""


def fetch_factset(log=print):
    from qx.fetch import get
    xml = get(FS_RSS, timeout=60, ua=UA_NAMED)
    rows = _rows(FACTSET_CSV)
    have = {r["url"] for r in rows}
    n = 0
    for it in re.findall(r"<item\b.*?>(.*?)</item>", xml, re.S)[:10]:
        t = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1])).strip()
        u = (re.search(r"<link>(.*?)</link>", it, re.S) or [None, ""])[1].strip()
        if not re.search(r"Earnings Season Update|Earnings Insight", t) or u in have:
            continue
        page = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", get(u, timeout=60, ua=UA_NAMED))))
        rows.append({"title": t[:120], "url": u, "pub": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                     "growth": _num(r"blended (?:\(year-over-year\) )?earnings growth rate for the S&P 500 is (-?\d+(?:\.\d+)?)%", page),
                     "beat": _num(r"(\d+(?:\.\d+)?)% of S&P 500 companies have reported a positive EPS surprise", page),
                     "rev": _num(r"blended (?:\(year-over-year\) )?revenue growth rate for the S&P 500 is (-?\d+(?:\.\d+)?)%", page),
                     "pe": _num(r"forward 12-month P/E ratio (?:for the S&P 500 )?is (\d+(?:\.\d+)?)", page),
                     "it": _num(r"Information Technology[^.]{0,80}?(-?\d+(?:\.\d+)?)%", page)})
        have.add(u)
        n += 1
        time.sleep(2)
    _write(FACTSET_CSV, ["title", "url", "pub", "growth", "beat", "rev", "pe", "it"], rows)
    log(f"  FactSet：新 {n} 篇（共 {len(rows)}）")


def fetch_auctions(log=print):
    from qx.fetch import get
    rows = _rows(AUCTION_CSV)
    since = max((r["date"] for r in rows), default="2008-01-01")
    have = {(r["date"], r["cusip"]) for r in rows}
    page, n = 1, 0
    while True:
        u = (f"{FISCAL}?fields=auction_date,security_type,security_term,cusip,bid_to_cover_ratio,high_yield,indirect_bidder_accepted,offering_amt"
             f"&filter=auction_date:gt:{since}&sort=auction_date&page%5Bsize%5D=1000&page%5Bnumber%5D={page}")
        j = json.loads(get(u, timeout=90, ua=UA_NAMED))
        for x in j.get("data") or []:
            k = (x["auction_date"], x["cusip"])
            if k in have or x.get("security_type") not in ("Note", "Bond"):
                continue
            rows.append({"date": x["auction_date"], "pub": x["auction_date"], "type": x["security_type"], "term": x["security_term"], "cusip": x["cusip"],
                         "btc": x.get("bid_to_cover_ratio") or "", "yield": x.get("high_yield") or "", "indirect": x.get("indirect_bidder_accepted") or "",
                         "amt": x.get("offering_amt") or ""})
            have.add(k)
            n += 1
        if page >= int((j.get("meta") or {}).get("total-pages") or 1):
            break
        page += 1
        time.sleep(1)
    _write(AUCTION_CSV, ["date", "pub", "type", "term", "cusip", "btc", "yield", "indirect", "amt"], sorted(rows, key=lambda r: (r["date"], r["cusip"])))
    log(f"  美债拍卖：新 {n} 场（共 {len(rows)}）")


def fetch_all(log=print):
    for f in (fetch_factset, fetch_auctions):
        try:
            f(log=log)
        except Exception as e:
            log(f"  ! {f.__name__} 没取到：{type(e).__name__}")


# ================================================================ 读
def auctions(t, terms=("10-Year", "30-Year", "2-Year")):
    """长端拍卖：最近一场的投标倍数，在同期限自己全部历史里的位置（低 = 需求弱）。"""
    rs = [r for r in _rows(AUCTION_CSV) if r["pub"] <= pd.Timestamp(t).strftime("%Y-%m-%d") and r.get("btc")]
    out = []
    for term in terms:
        g = [r for r in rs if r["term"] == term]
        if len(g) < 20:
            continue
        b = np.array([float(r["btc"]) for r in g])
        out.append(dict(term=term, date=g[-1]["date"], btc=b[-1], pos=float((b[:-1] < b[-1]).mean()), n=len(b), yld=g[-1]["yield"]))
    return out


def _fred_last(D, k, t):
    if k not in D:
        return None
    s = D[k]["c"].dropna()
    s = s[s.index < pd.Timestamp(t)]
    return (s.index[-1].strftime("%Y-%m-%d"), float(s.iloc[-1]), s) if len(s) else None


def rows(D, t):
    """账本：每条链 4–6 个数，每个带来源、时点、下次公布日。"""
    import csv as _csv
    from qx import fundamentals as F
    t = pd.Timestamp(t)
    out = []
    # 台积电月营收
    if os.path.exists(F.TW_CSV):
        tw = [r for r in _csv.DictReader(open(F.TW_CSV, encoding="utf-8")) if r["code"] == "2330" and r.get("pub") and pd.Timestamp(r["pub"][:10]) <= t]
        if tw:
            r = sorted(tw, key=lambda r: r["ym"])[-1]
            nxt = (pd.Timestamp(r["ym"] + "-01") + pd.DateOffset(months=2)).strftime("%Y-%m-10")
            out.append(dict(chain="芯片", name="台积电月营收同比", value=f"{float(r['yoy']):+.1f}%", asof=r["ym"], src="台湾证交所", next=f"约 {nxt}"))
    # FactSet
    fs = [r for r in _rows(FACTSET_CSV) if pd.Timestamp(r["pub"][:10]) <= t]
    if fs:
        r = fs[-1]
        v = "；".join(x for x in [f"混合盈利增速 {r['growth']}%" if r["growth"] else "", f"超预期 {r['beat']}%" if r["beat"] else "",
                                  f"预期市盈率 {r['pe']}" if r["pe"] else ""] if x) or "这篇没取到数（句式变了）"
        out.append(dict(chain="资本开支预期", name="标普 500 盈利季（FactSet）", value=v, asof=r["pub"][:10], src="FactSet Insight", next="下周五前后", url=r["url"]))
    # FRED
    for k, chain, nm, unit, nxt in (("RAMPAIALL", "AI 需求", "Ramp AI 采用率", "%", "每月中旬"), ("BAMLH0A2HYB", "neocloud 信用", "单 B 利差", "%", "每个交易日（晚一天）"),
                                    ("BAMLC0A0CM", "云大厂融资", "投资级利差", "%", "每个交易日（晚一天）"), ("WTREGEN", "流动性", "财政部账户", "十亿美元", "每周四"),
                                    ("WRESBAL", "流动性", "银行准备金", "十亿美元", "每周四"), ("RRPONTSYD", "流动性", "隔夜逆回购", "十亿美元", "每个交易日")):
        x = _fred_last(D, k, t)
        out.append(dict(chain=chain, name=nm, value=f"{x[1]:,.2f}{unit}" if x else "缺（FRED 还没取到）", asof=x[0] if x else "", src="FRED " + k, next=nxt))
    for a in auctions(t):
        out.append(dict(chain="流动性", name=f"{a['term']} 美债拍卖投标倍数", value=f"{a['btc']:.2f}（同期限历史里 {a['pos'] * 100:.0f}% 的位置）", asof=a["date"], src="财政部 Fiscal Data", next="看时间轴"))
    out.append(dict(chain="资本开支预期", name="云厂商资本开支和自由现金流", value="缺：SEC 接口要联系邮箱（用户给了 SEC_CONTACT 才接）", asof="", src="SEC XBRL", next="财报后"))
    out.append(dict(chain="存储", name="存储价格、GPU 租金、token 价格、韩国出口", value="没有免费可自动化的数，只放新闻链接", asof="", src="—", next="—"))
    return out
