"""时间：美股收盘后算、北京早上看。只用已经收盘的交易日（盘中跑时，当天那根未完成的日线不进计算）。

美股休市日用 NYSE 公布的日期列表（不按规则推算；2026-10-23 从 nyse.com/markets/hours-calendars 核对）。列表到 2028 年底，过了就在页头提示补表。
提前收盘（13:00）的日子按全天处理：16:15 以后才算收盘，只是晚一点。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SH = ZoneInfo("Asia/Shanghai")
CLOSE_HM = (16, 15)          # 收盘 16:00，留 15 分钟给数据源出收盘价

# NYSE 休市日（全天）。来源：NYSE 公布的交易日历（2025 年含 1-09 卡特国葬日）；2029 年起要补。
NYSE_HOLIDAYS = {
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
    "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04", "2028-11-23",
    "2028-12-25",
}
HOLIDAYS_UNTIL = "2028-12-31"


def is_trading_day(d):
    d = d if isinstance(d, date) else date.fromisoformat(d)
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def ny_now():
    return datetime.now(NY)


def last_closed(now=None, hm=CLOSE_HM):
    """最近一个已经收盘的美股交易日（美东日期，YYYY-MM-DD）。跳过周末和 NYSE 休市日。"""
    now = now or ny_now()
    d = now.date()
    if not is_trading_day(d) or (now.hour, now.minute) < hm:
        d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d.isoformat()


def holidays_stale(today=None):
    """休市日列表过期了没有（过期后看门狗会在休市日误报，页头提示补表）。"""
    return (today or date.today()).isoformat() > HOLIDAYS_UNTIL


def stamp():
    return datetime.now(SH).isoformat(timespec="seconds")
