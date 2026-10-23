"""序列登记表：所有要下载的序列只在这里登记（从旧终端 data/registry.py 复制改的，2026-10-23）。

每个序列：名字、来源、起点、公布滞后、单位、组。
  lag   公布滞后（美股交易日）。FRED 的滞后在计算里处理（qx/sentiment.py 按"次一个观测日才可用"对齐，和研究一致）。
  kind  ohlcv = 开高低收和成交量（Yahoo）；value = 只有一个数（FRED、CBOE）。
原始数据在 data/raw/<文件名>.csv（云端放在 Actions 缓存里，不进仓库）。
"""

YAHOO_HOW = "Yahoo v8 chart 日线；每天第一次全量，之后补最近 10 天"
FRED_HOW = "FRED fredgraph.csv"

SERIES = {}


def _add(name, source, start, lag, unit, kind="ohlcv", adj=False, zero=False, note="", group=""):
    SERIES[name] = dict(name=name, file=name.replace("^", "") + ".csv", source=source, how=YAHOO_HOW if source == "Yahoo" else FRED_HOW,
                        start=start, lag=lag, unit=unit, kind=kind, adj=adj, zero=zero, note=note, group=group)


# ---------------------------------------------------------------- 期权隐含波动（指数）
for _s, _n in [("^VIX", "标普 500 期权 30 天隐含波动"), ("^VIX3M", "标普 500 期权 3 个月隐含波动"), ("^VXN", "纳指 100 期权 30 天隐含波动"),
               ("^VIX9D", "标普 500 期权 9 天隐含波动"), ("^SKEW", "CBOE SKEW"), ("^VVIX", "VIX 的隐含波动"), ("^MOVE", "美债期权隐含波动"),
               ("^OVX", "原油期权隐含波动"), ("^GVZ", "黄金期权隐含波动")]:
    _add(_s, "Yahoo", "Yahoo 最早起", 0, "点", group="期权", note=_n)

# ---------------------------------------------------------------- 美股：指数、ETF
for _s, _n, _adj in [("^SOX", "费城半导体指数", False), ("SMH", "VanEck 半导体 ETF", False), ("SOXX", "iShares 半导体 ETF", False),
                     ("SOXL", "3 倍做多半导体", False), ("SOXS", "3 倍做空半导体", False), ("^GSPC", "标普 500", False), ("^NDX", "纳指 100", False),
                     ("SPY", "标普 500 ETF", True), ("QQQ", "纳指 100 ETF", False), ("IWM", "罗素 2000 ETF", False), ("RSP", "等权标普 500 ETF", True)]:
    _add(_s, "Yahoo", "Yahoo 最早起", 0, "", adj=_adj, group="美股", note=_n)

# ---------------------------------------------------------------- 信用 ETF 和国债 ETF（算"信用 ETF 跑输国债的比例"，都用含分红价）
CREDIT_ETF = {"HYG": "SHY", "JNK": "SHY", "BKLN": "SHY", "SJNK": "SHY", "ANGL": "IEF", "LQD": "IEF", "EMB": "IEF"}   # 信用 ETF → 对比的国债 ETF
for _s in list(CREDIT_ETF) + ["SHY", "IEF", "TLT", "KRE"]:          # KRE：区域银行，"几条信用读数同时亮"检验时用过，留着保持口径
    _add(_s, "Yahoo", "Yahoo 最早起", 0, "美元", adj=True, group="信用", note="信用 / 国债 ETF")

# ---------------------------------------------------------------- 半导体成分股：28 只（阶段规则用的股票池，和研究一致，不改）
SEMIS = ["ADI", "AMAT", "AMD", "ASML", "ASX", "AVGO", "COHR", "ENTG", "GFS", "INTC", "KLAC", "LRCX", "LSCC", "MCHP",
         "MPWR", "MRVL", "MTSI", "MU", "NVDA", "NXPI", "ON", "QCOM", "STM", "SWKS", "TER", "TSM", "TXN", "UMC"]
# 小盘和次新半导体 35 只（产业链分组、"小盘先崩"提醒用；不进阶段规则）
SMALL = ["AMKR", "FORM", "ONTO", "COHU", "KLIC", "POWI", "SITM", "SLAB", "SYNA", "CRUS", "RMBS", "AMBA", "MXL", "DIOD", "VSH", "MKSI",
         "UCTT", "ICHR", "PLAB", "AEHR", "NVMI", "CAMT", "ALGM", "ACLS", "SMTC", "CEVA", "AOSL", "PI", "TSEM", "WOLF", "QRVO", "ALAB", "CRDO", "MBLY", "NVTS"]
# AI 产业链分组（只描述"这次谁跌得最深"）
AI = {"光通信": ["AAOI", "LITE", "CIEN", "COHR", "FN"], "网络": ["ANET"], "服务器和电源": ["VRT", "SMCI", "DELL", "HPE", "CLS"],
      "算力云": ["CRWV", "NBIS", "ORCL", "APLD", "IREN"], "存储": ["WDC", "STX", "SNDK", "MU"]}
BIGTECH = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"]
for _s in dict.fromkeys(SEMIS + SMALL + [t for v in AI.values() for t in v] + BIGTECH):
    _add(_s, "Yahoo", "上市日起", 0, "美元", group="个股", note="成分股 / 产业链")

# ---------------------------------------------------------------- 联动市场（平时不出现，少见的变化才出现）
LINKED = [("^N225", "日经 225"), ("^KS11", "KOSPI"), ("000660.KS", "SK 海力士"), ("005930.KS", "三星电子"), ("^TWII", "台湾加权"),
          ("^HSI", "恒生指数"), ("000300.SS", "沪深 300"), ("GC=F", "黄金"), ("CL=F", "原油 WTI"), ("JPY=X", "美元兑日元"),
          ("KRW=X", "美元兑韩元"), ("DX-Y.NYB", "美元指数"), ("^TNX", "10 年美债收益率"), ("BTC-USD", "比特币"), ("EWY", "韩国 ETF")]
for _s, _n in LINKED:
    _add(_s, "Yahoo", "Yahoo 最早起", 0, "", group="联动", note=_n)

# ---------------------------------------------------------------- FRED（日度；滞后 1 = 次一交易日才知道）
for _s, _n in [("BAA10Y", "穆迪 Baa 公司债收益率 − 10 年国债"), ("AAA10Y", "穆迪 Aaa 公司债收益率 − 10 年国债"),
               ("DGS10", "10 年国债收益率"), ("DGS2", "2 年国债收益率"), ("DCPF3M", "3 个月金融商业票据利率"), ("DTB3", "3 个月国库券利率"),
               ("BAMLC0A0CM", "ICE 投资级利差"), ("BAMLC0A4CBBB", "ICE BBB 利差"), ("BAMLH0A1HYBB", "ICE BB 利差"),
               ("BAMLH0A2HYB", "ICE B 利差"), ("BAMLH0A3HYC", "ICE CCC 及以下利差"), ("BAMLH0A0HYM2", "ICE 高收益整体利差")]:
    _add(_s, "FRED", "FRED 最早起", 1, "%", kind="value", group="信用", note=_n)

# ---------------------------------------------------------------- CBOE 认沽认购比
_add("PC_EQ", "CBOE", "2006-11-01", 0, "比值", kind="value", group="仓位", note="股票期权认沽成交量 ÷ 认购成交量，收盘后当天公布")

# 期权链：盘中每 30 分钟存一行摘要；收盘后存一份完整的（加密后放 GitHub Releases）
CHAIN_SYMBOLS = [("SPY", "标普 500 ETF"), ("QQQ", "纳指 100 ETF"), ("SMH", "半导体 ETF"), ("SOXX", "半导体 ETF（iShares）"), ("NVDA", "英伟达"),
                 ("AVGO", "博通"), ("AMD", "AMD"), ("TSM", "台积电"), ("MU", "美光"), ("EWY", "韩国 ETF")]
OPTIONS_FILE = "options_history.csv"

YAHOO = [k for k, v in SERIES.items() if v["source"] == "Yahoo"]
FRED = [k for k, v in SERIES.items() if v["source"] == "FRED"]
assert len({v["file"] for v in SERIES.values()}) == len(SERIES), "文件名重复"
