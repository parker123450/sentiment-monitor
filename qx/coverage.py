"""扫描范围（第四轮第 2 步，2026-10-27 登记；口径.md 第十节）。两层：

ALL     全部扫描：小信号、少见涨跌、机会卡都在这一层跑，同一套规则，涨跌按各自长期波动折算、按少见程度排，不按行业排。
AI      AI 链细看：现在的主线，篮子、主线、账本用这一层（registry 里已有的半导体、小盘、产业链、大型科技加这里新增的）。
代码以 Yahoo 实测为准（10-27）：^HSTECH 取不到；HSTECH.HK、000300.SS、399006.SZ 只回最近 1 天、没有历史，
扫描里改用 ETF：恒生科技 → 3033.HK，沪深 300 → 510300.SS，创业板 → 159915.SZ。CNH=X 全历史取不到（只有近几天），标"缺"。
每个代码记：名字、市场（交易所日历，算开没开盘）、大类（页面"各市场一行"按它分行）。
"""
from qx.registry import SEMIS, SMALL, AI as AI_GROUPS, BIGTECH, LINKED, CREDIT_ETF

# (代码, 名字, 市场, 大类)；市场用 exchange_calendars 的代码，24 小时的（汇率、加密、期货）写 "24h"
ALL = [
    # 美股：指数、等权、11 个行业、细分
    ("^GSPC", "标普 500", "XNYS", "美股"), ("^NDX", "纳指 100", "XNYS", "美股"), ("^RUT", "罗素 2000", "XNYS", "美股"),
    ("RSP", "等权标普", "XNYS", "美股"), ("^SOX", "费城半导体", "XNYS", "美股"),
    ("XLK", "科技", "XNYS", "美股行业"), ("XLF", "金融", "XNYS", "美股行业"), ("XLE", "能源", "XNYS", "美股行业"), ("XLV", "医疗", "XNYS", "美股行业"),
    ("XLI", "工业", "XNYS", "美股行业"), ("XLY", "可选消费", "XNYS", "美股行业"), ("XLP", "必需消费", "XNYS", "美股行业"), ("XLU", "公用事业", "XNYS", "美股行业"),
    ("XLB", "材料", "XNYS", "美股行业"), ("XLRE", "房地产", "XNYS", "美股行业"), ("XLC", "通信", "XNYS", "美股行业"),
    ("SMH", "半导体 ETF", "XNYS", "美股细分"), ("IGV", "软件", "XNYS", "美股细分"), ("KRE", "区域银行", "XNYS", "美股细分"), ("XBI", "生物科技", "XNYS", "美股细分"),
    ("ITB", "住宅建筑", "XNYS", "美股细分"), ("XME", "金属采矿", "XNYS", "美股细分"), ("XOP", "油气开采", "XNYS", "美股细分"), ("GDX", "金矿股", "XNYS", "美股细分"),
    ("URA", "铀", "XNYS", "美股细分"), ("ITA", "国防航空", "XNYS", "美股细分"), ("JETS", "航空", "XNYS", "美股细分"),
    # 其他股市
    ("^N225", "日经 225", "XTKS", "日本"), ("^KS11", "KOSPI", "XKRX", "韩国"), ("^TWII", "台湾加权", "XTAI", "台湾"), ("^HSI", "恒生指数", "XHKG", "香港"),
    ("3033.HK", "恒生科技 ETF", "XHKG", "香港"), ("510300.SS", "沪深 300 ETF", "XSHG", "A 股"), ("159915.SZ", "创业板 ETF", "XSHG", "A 股"),
    ("^STOXX50E", "欧洲 STOXX 50", "XAMS", "欧洲"), ("^GDAXI", "德国 DAX", "XETR", "欧洲"),
    ("INDA", "印度 ETF", "XNYS", "新兴市场"), ("EWZ", "巴西 ETF", "XNYS", "新兴市场"), ("EEM", "新兴市场 ETF", "XNYS", "新兴市场"), ("KWEB", "中概互联 ETF", "XNYS", "新兴市场"),
    ("EWY", "韩国 ETF", "XNYS", "新兴市场"),
    # 商品
    ("CL=F", "原油 WTI", "24h", "商品"), ("BZ=F", "布伦特", "24h", "商品"), ("NG=F", "天然气", "24h", "商品"), ("GC=F", "黄金", "24h", "商品"),
    ("SI=F", "白银", "24h", "商品"), ("HG=F", "铜", "24h", "商品"), ("ZC=F", "玉米", "24h", "商品"), ("ZS=F", "大豆", "24h", "商品"), ("ZW=F", "小麦", "24h", "商品"),
    # 利率（收益率指数；10 年期实际利率、2 年在 FRED）
    ("^IRX", "3 个月美债", "XNYS", "利率"), ("^FVX", "5 年美债", "XNYS", "利率"), ("^TNX", "10 年美债", "XNYS", "利率"), ("^TYX", "30 年美债", "XNYS", "利率"),
    ("TLT", "长债 ETF", "XNYS", "利率"),
    # 汇率
    ("DX-Y.NYB", "美元指数", "24h", "汇率"), ("JPY=X", "美元兑日元", "24h", "汇率"), ("CNH=X", "美元兑离岸人民币", "24h", "汇率"), ("KRW=X", "美元兑韩元", "24h", "汇率"),
    ("TWD=X", "美元兑台币", "24h", "汇率"), ("EURUSD=X", "欧元兑美元", "24h", "汇率"), ("AUDUSD=X", "澳元兑美元", "24h", "汇率"),
    # 加密
    ("BTC-USD", "比特币", "24h", "加密"), ("ETH-USD", "以太坊", "24h", "加密"), ("SOL-USD", "SOL", "24h", "加密"), ("COIN", "Coinbase", "XNYS", "加密"),
    ("MSTR", "Strategy", "XNYS", "加密"),
    # 信用和波动
    ("HYG", "高收益债 ETF", "XNYS", "信用"), ("LQD", "投资级债 ETF", "XNYS", "信用"), ("^VIX", "VIX", "XNYS", "波动"), ("^VXN", "VXN", "XNYS", "波动"),
    ("^MOVE", "MOVE", "XNYS", "波动"), ("^OVX", "原油波动", "XNYS", "波动"), ("^GVZ", "黄金波动", "XNYS", "波动"),
    # 期货（第 6 类卡：亚洲大动而纳指期货没动）
    ("NQ=F", "纳指期货", "24h", "美股"),
]

# AI 链细看新增（第 2 步 1.加）
AI_NEW = [
    ("9984.T", "软银", "XTKS", "日本"), ("6857.T", "爱德万", "XTKS", "日本"), ("8035.T", "东京电子", "XTKS", "日本"), ("6920.T", "Lasertec", "XTKS", "日本"),
    ("6146.T", "Disco", "XTKS", "日本"), ("285A.T", "铠侠", "XTKS", "日本"),
    ("2330.TW", "台积电（台股）", "XTAI", "台湾"), ("2454.TW", "联发科", "XTAI", "台湾"), ("2317.TW", "鸿海", "XTAI", "台湾"), ("2382.TW", "广达", "XTAI", "台湾"),
    ("3231.TW", "纬创", "XTAI", "台湾"), ("2308.TW", "台达电", "XTAI", "台湾"), ("3711.TW", "日月光", "XTAI", "台湾"),
    ("688256.SS", "寒武纪", "XSHG", "A 股"), ("300308.SZ", "中际旭创", "XSHG", "A 股"), ("601138.SS", "工业富联", "XSHG", "A 股"), ("688981.SS", "中芯国际（A）", "XSHG", "A 股"),
    ("0981.HK", "中芯国际（港）", "XHKG", "香港"), ("0700.HK", "腾讯", "XHKG", "香港"), ("9988.HK", "阿里巴巴", "XHKG", "香港"),
    ("ASML.AS", "阿斯麦（欧）", "XAMS", "欧洲"), ("ASM.AS", "ASM International", "XAMS", "欧洲"), ("BESI.AS", "BESI", "XAMS", "欧洲"), ("IFX.DE", "英飞凌", "XETR", "欧洲"),
    ("VST", "Vistra", "XNYS", "美股电力"), ("CEG", "Constellation", "XNYS", "美股电力"), ("GEV", "GE Vernova", "XNYS", "美股电力"), ("ETN", "伊顿", "XNYS", "美股电力"),
    ("TLN", "Talen", "XNYS", "美股电力"), ("CORZ", "Core Scientific", "XNYS", "美股电力"),
    ("000660.KS", "SK 海力士", "XKRX", "韩国"), ("005930.KS", "三星电子", "XKRX", "韩国"),
]
AI_US = list(dict.fromkeys(SEMIS + SMALL + [t for v in AI_GROUPS.values() for t in v] + BIGTECH))

NAME = {s: n for s, n, _, _ in ALL + AI_NEW}
MARKET = {s: m for s, _, m, _ in ALL + AI_NEW}
CLASS = {s: c for s, _, _, c in ALL + AI_NEW}
for _s in AI_US:
    MARKET.setdefault(_s, "XNYS")
    CLASS.setdefault(_s, "AI 链美股")
ALL_SYMS = [s for s, *_ in ALL]
AI_SYMS = list(dict.fromkeys([s for s, *_ in AI_NEW] + AI_US))
SCAN = list(dict.fromkeys(ALL_SYMS + AI_SYMS))          # 全部扫描 = 两层合起来（AI 链也跑同一套规则）
CORE = ALL_SYMS + [s for s, *_ in AI_NEW] + ["NVDA", "AMD", "AVGO", "MU", "TSM", "ORCL", "CRWV", "NBIS", "MSFT", "GOOGL", "AMZN", "META", "AAPL", "TSLA"]
# Worker 盘中只取核心（约 150 个，每批 20 个，最多 8 批）
CLASSES = ["美股", "美股行业", "美股细分", "美股电力", "AI 链美股", "A 股", "香港", "日本", "韩国", "台湾", "欧洲", "新兴市场", "商品", "利率", "汇率", "加密", "信用", "波动"]
BP = {"^IRX", "^FVX", "^TNX", "^TYX"}                   # 收益率：涨跌按基点
