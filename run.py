#!/usr/bin/env python3
"""入口：云端每 15 分钟跑一次 `python run.py auto`，自己决定这次做什么。

  每次：要闻、预测市场、CNN、盘中报价；美股盘中每 30 分钟加期权链摘要；美股收盘后（美东 16:45 以后）存一份完整期权链。
  美股收盘后（美东 16:15）：日线、FRED、认沽认购、AAII → 算情绪 → 自检 → 记日志；美东 20:30 以后再补一次（FRED、CBOE 晚到的）。
  亚洲收盘后（北京 16:30）：只补联动市场的日线。
  每次最后：生成页面。有 PAGE_PASSWORD 才生成要发布的加密页（site/index.html），否则只在本机生成明文预览。

用法：
  python run.py auto            # 云端用
  python run.py page            # 不下载，只用存下的数据重算、生成页面
  python run.py daily           # 马上下载一次日线（不管时间）
  python run.py selftest        # 只跑自检
  python run.py pack <文件> / unpack <文件>   # data/ 下的小文件加密打包 / 解开（data 分支只放这一个加密文件）
"""
import csv, json, os, shutil, sys, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from qx import clock, crypt, export, fetch, page, selftest, sentiment, store   # noqa: E402
from qx.registry import LINKED                                                  # noqa: E402

SITE = os.path.join(ROOT, "site")
PREVIEW = os.path.join(ROOT, "本机预览", "情绪阶段.html")
LOG = os.path.join(store.HERE, "log.csv")
CHAINS = os.path.join(store.RAW, "chains")
ASIA = [s for s, _ in LINKED if s.endswith((".KS", ".SS")) or s in ("^N225", "^KS11", "^TWII", "^HSI")]
LOG_COLS = ["date", "stage", "sell", "price", "pos", "credit", "credit_n", "regime", "vixmax", "m_sell", "m_price", "m_pos", "m_credit", "dd", "cnn", "written"]


def log(*a):
    print(*a, flush=True)


def decide(st, now=None):
    """这次要做哪些事（只看时间和上次做到哪）。"""
    now = now or datetime.now(timezone.utc)
    ny = now.astimezone(clock.NY)
    today_ny = ny.date().isoformat()
    trading = clock.is_trading_day(ny.date())
    hm = (ny.hour, ny.minute)
    last_us = clock.last_closed(ny)
    do = {"opt": False, "archive": None, "daily": None, "cal": time.time() - st.get("cal_ts", 0) >= 6 * 3600}
    if trading and (9, 30) <= hm < (16, 15):
        do["opt"] = time.time() - st.get("opt_ts", 0) >= 28 * 60
    if trading and hm >= (16, 45) and st.get("chain_day") != today_ny:
        do["opt"], do["archive"] = True, today_ny
    if st.get("us_done") != last_us or not os.path.exists(store.path("^SOX")):     # 行情缓存丢了也重新下载
        do["daily"] = "us"
    elif st.get("us_late") != last_us and (hm >= (20, 30) or ny.date().isoformat() > last_us):
        do["daily"] = "us_late"
    elif now.weekday() < 5 and now.hour * 60 + now.minute >= 8 * 60 + 30 and st.get("asia_done") != now.date().isoformat():
        do["daily"] = "asia"
    return do, last_us, today_ny


def write_log(R, cnn):
    """样本外日志：每个美股收盘一行（同一天重跑就覆盖）。信用 ETF 那条也记（第 11 轮：不算进投降，但每天记，攒样本外）。"""
    t = R["P"].index[-1]
    g = lambda k: R[k].iloc[-1]
    num = lambda x, d=0: "" if x is None or not (x == x) else (round(float(x), d) if d else int(round(float(x))))
    row = {"date": t.strftime("%Y-%m-%d"), "stage": num(g("stage")), "sell": num(g("sell")), "price": num(g("price")), "pos": num(g("pos")),
           "credit": num(g("credit")), "credit_n": num(g("credit_n")), "regime": num(g("regime")), "vixmax": num(g("vixmax"), 2),
           "m_sell": num(g("m_sell")), "m_price": num(g("m_price")), "m_pos": num(g("m_pos")), "m_credit": num(g("m_credit")),
           "dd": num(g("dd") * 100, 2), "cnn": cnn["now"] if cnn and cnn.get("date") == t.strftime("%Y-%m-%d") else "",
           "written": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    rows = {}
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            rows = {r["date"]: r for r in csv.DictReader(f)}
    rows[row["date"]] = row
    tmp = LOG + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k].get(c, "") for c in LOG_COLS})
    os.replace(tmp, LOG)


def build(check=False, write=False):
    """算情绪、（可选）自检、（可选）记日志、生成页面。返回自检是否通过。"""
    D, aaii = store.load_all()
    if "^SOX" not in D:
        log("还没有费城半导体的日线，这次不算、不生成页面")
        return False
    R = sentiment.compute_all(D, aaii)
    ok = True
    if check:
        log("自检（截断重算必须和全量一致）：")
        ok = selftest.run(D, aaii, R=R, n=3, log=log)
    data = export.build(D, aaii, R)
    if write and ok:
        write_log(R, data.get("cnn"))
    pw = os.environ.get("PAGE_PASSWORD", "").strip()
    if ok:
        if page.write(data, SITE, password=pw or None, preview=None if os.environ.get("CI") else PREVIEW):
            log(f"页面：site/index.html（加密，{os.path.getsize(os.path.join(SITE, 'index.html')) / 1e6:.2f} MB）")
        else:
            log("页面：没有 PAGE_PASSWORD，不生成要发布的页面" + ("" if os.environ.get("CI") else f"；本机预览 {os.path.relpath(PREVIEW, ROOT)}"))
    st = R["stage"].iloc[-1]
    log(f"现在：{sentiment.NAMES[int(st)]}（{R['P'].index[-1].date()}）")
    return ok


def archive_chains(st):
    """把还没上传的完整期权链目录打包加密 → data/out/chains-<日期>.enc（工作流上传到 GitHub Releases），返回文件列表。"""
    key = crypt.data_key()
    out = []
    if not key or not os.path.isdir(CHAINS):
        return out
    os.makedirs(os.path.join(ROOT, "data", "out"), exist_ok=True)
    for d in sorted(os.listdir(CHAINS)):
        src = os.path.join(CHAINS, d)
        if not os.path.isdir(src) or d in st.get("chains_up", []):
            continue
        dst = os.path.join(ROOT, "data", "out", f"chains-{d}.enc")
        crypt.pack_dir(src, dst, key)
        out.append(dst)
    return out


def auto():
    st = fetch.read_state()
    do, last_us, today_ny = decide(st)
    log(f"这次：{json.dumps(do, ensure_ascii=False)}；最近收盘的美股交易日 {last_us}")
    archive_dir = os.path.join(CHAINS, do["archive"]) if do["archive"] else None
    fetch.quick(log=log, opt=do["opt"], archive_dir=archive_dir, cal=do["cal"])
    st = fetch.read_state()
    if do["cal"]:
        st["cal_ts"] = time.time()
    if do["opt"]:
        st["opt_ts"] = time.time()
    if do["archive"]:
        st["chain_day"] = do["archive"]
    fetch.write_state(st)
    check = write = False
    if do["daily"] in ("us", "us_late"):
        got = fetch.daily(log=log)
        st = fetch.read_state()
        if got["ok"] >= 0.8 * got["n"]:                  # 大部分没取到就不算做完，下次再来
            st["us_late" if do["daily"] == "us_late" else "us_done"] = last_us
        fetch.write_state(st)
        check = write = True
    elif do["daily"] == "asia":
        got = fetch.daily(log=log, only=ASIA)
        st = fetch.read_state()
        if got["ok"] >= 0.8 * got["n"]:
            st["asia_done"] = datetime.now(timezone.utc).date().isoformat()
        fetch.write_state(st)
    if do["daily"]:
        os.makedirs(os.path.join(ROOT, "data", "out"), exist_ok=True)
        open(os.path.join(ROOT, "data", "out", "raw_changed"), "w").close()     # 工作流看到它才存行情缓存
    ok = build(check=check, write=write)
    files = archive_chains(fetch.read_state())
    with open(os.path.join(ROOT, "data", "out", "upload.txt") if files else os.devnull, "w") as f:
        f.write("\n".join(files))
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd == "auto":
        ok = auto()
    elif cmd == "page":
        ok = build()
    elif cmd == "daily":
        fetch.daily(log=log)
        ok = build(check=True, write=True)
    elif cmd == "uploaded":                          # 工作流上传完期权链存档后调用：记下来、删掉本地目录
        st = fetch.read_state()
        for f in sys.argv[2:]:
            d = os.path.basename(f)[len("chains-"):-len(".enc")]
            st["chains_up"] = (st.get("chains_up", []) + [d])[-60:]
            shutil.rmtree(os.path.join(CHAINS, d), ignore_errors=True)
            os.remove(f)
        fetch.write_state(st)
        ok = True
    elif cmd == "pack":                              # data/ 下攒的小文件（不含行情缓存和待上传的存档）→ 加密的 data.enc
        crypt.pack_dir(store.HERE, sys.argv[2], crypt.data_key(), skip=("raw", "out"))
        ok = True
    elif cmd == "unpack":
        crypt.unpack_dir(sys.argv[2], store.HERE, crypt.data_key())
        ok = True
    elif cmd == "selftest":
        D, aaii = store.load_all()
        ok = selftest.run(D, aaii, n=5, log=log)
    else:
        print(__doc__)
        ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
