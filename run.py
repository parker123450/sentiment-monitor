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
  python run.py backfill        # 快讯回补过去 30 天（谷歌新闻按日期搜，每分钟 1 次，约 3 小时；跑完才开始推"第一次"）
  python run.py pushtest        # 测试推送：正文写发送时间，看手机上的到达时间
  python run.py rules           # 导出给 Worker 的规则（data/out/rules.json）
  python run.py seal-scenarios  # 本机 ../判断/scenarios/*.json（三种走向原文，不进仓库）加密成 cards/scenarios/*.enc
  python run.py replay [起] [止] # 小信号和仓位回放（每天只用截到那天能看到的数据重算），写 data/private/replay.csv（加密存，日志只打条数）
  python run.py earn-refresh    # 财报反应：2026-10-28 以前按"前 504 天"算日度波动的行，按全部历史重算（别和正在写这个文件的进程同时跑）
"""
import csv, json, os, shutil, sys, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from qx import clock, crypt, export, fetch, flash, happen, notify, page, selftest, sentiment, store   # noqa: E402
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
    do = {"opt": False, "archive": None, "daily": None, "cal": time.time() - st.get("cal_ts", 0) >= 6 * 3600,
          "fund": time.time() - st.get("fund_ts", 0) >= 20 * 3600}
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
        return False, None
    R = sentiment.compute_all(D, aaii)
    ok = True
    if check:
        log("自检（截断重算必须和全量一致）：")
        ok = selftest.run(D, aaii, R=R, n=3, log=log)
    data = export.build(D, aaii, R, write=write and ok)
    if write and ok:
        write_log(R, data.get("cnn"))
    pw = os.environ.get("PAGE_PASSWORD", "").strip()
    try:                                                # 扫描范围里其余标的的 K 线，点了才加载（发布的加密，本机预览明文）
        data["kmore"] = export.write_k(D, SITE if pw and ok else None, pw or None, None if os.environ.get("CI") else os.path.dirname(PREVIEW))
    except Exception as e:
        log(f"  ! K 线文件没写出来：{type(e).__name__}")
        data["kmore"] = []
    if ok:
        if page.write(data, SITE, password=pw or None, preview=None if os.environ.get("CI") else PREVIEW):
            log(f"页面：site/index.html（加密，{os.path.getsize(os.path.join(SITE, 'index.html')) / 1e6:.2f} MB）")
        else:
            log("页面：没有 PAGE_PASSWORD，不生成要发布的页面" + ("" if os.environ.get("CI") else f"；本机预览 {os.path.relpath(PREVIEW, ROOT)}"))
    st = R["stage"].iloc[-1]
    log(f"现在：{sentiment.NAMES[int(st)]}（{R['P'].index[-1].date()}）；今天要知道的 {len(data['today']['items'])} 条；判断卡 {len(data.get('judge') or [])} 张")
    return ok, data


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
    fetch.quick(log=log, opt=do["opt"], archive_dir=archive_dir, cal=do["cal"], fund=do["fund"])
    st = fetch.read_state()
    if do["cal"]:
        st["cal_ts"] = time.time()
    if do["fund"]:
        st["fund_ts"] = time.time()
        try:                                            # 仓位和日本国债（第四轮第 3 步）：和基本面一样每天一次
            from qx import positioning
            positioning.fetch_all(log=log)
        except Exception as e:
            log(f"  ! 仓位数据出错：{type(e).__name__}")
        try:                                            # AI 账本的慢数据（第四轮第 5 步）：FactSet、美债拍卖
            from qx import ledger
            ledger.fetch_all(log=log)
        except Exception as e:
            log(f"  ! 账本数据出错：{type(e).__name__}")
        try:                                            # 时间轴（第四轮第 5 步）：每周一次
            from qx import timeline
            if time.time() - st.get("tl_ts", 0) >= 6 * 86400:
                timeline.build(log=log)
                st["tl_ts"] = time.time()
        except Exception as e:
            log(f"  ! 时间轴出错：{type(e).__name__}")
        try:                                            # 财报反应（第四轮第 4 步第 4 类卡）：补最近 5 天
            from qx import earn
            earn.fetch(datetime.now(timezone.utc).date() - timedelta(days=5), log=log)
        except Exception as e:
            log(f"  ! 财报反应出错：{type(e).__name__}")
    if do["opt"]:
        st["opt_ts"] = time.time()
    if do["archive"]:
        st["chain_day"] = do["archive"]
    fetch.write_state(st)
    try:
        happen.archive()                                # 新闻标题、议息会概率存档
    except Exception as e:
        log(f"  ! 存档出错：{e}")
    cands = []
    try:
        cands = flash.run(log=log)                      # 快讯：取、去重、打标签、"第一次"；回补跑完以后才给推送候选
    except Exception as e:
        log(f"  ! 快讯出错：{type(e).__name__}")
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
    try:
        notify.pull_feedback(log=log)                   # 页面发来的试用记录
    except Exception as e:
        log(f"  ! 试用记录没取到：{e}")
    ok, data = build(check=check, write=write)
    if os.environ.get("WORKER_URL"):                    # 有 Worker 时：推规则、各市场时刻和少见表，取回它每 5 分钟攒的快讯
        try:
            from qx import markets
            flash.sync(log=log, extra_state={"markets": markets.state(store.load_all()[0])})
        except Exception as e:
            log(f"  ! Worker 同步出错：{type(e).__name__}")
    try:
        notify.push(data, ok, log=log, flash=cands)
    except Exception as e:
        log(f"  ! 推送出错：{e}")
    files = archive_chains(fetch.read_state())
    with open(os.path.join(ROOT, "data", "out", "upload.txt") if files else os.devnull, "w") as f:
        f.write("\n".join(files))
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if cmd == "auto":
        ok = auto()
    elif cmd == "page":
        ok, _ = build()
    elif cmd == "daily":
        fetch.daily(log=log)
        ok, _ = build(check=True, write=True)
    elif cmd == "seal":                              # 本机 ../判断/*.json → 加密的 cards/*.enc（进仓库）
        from qx import judge
        for p in judge.seal():
            log("加密：" + os.path.relpath(p, ROOT))
        ok = True
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
    elif cmd == "backfill":
        n = flash.backfill(log=log)
        log(f"回补：{n} 次查询，跑完了，开始推\"第一次\"")
        ok = True
    elif cmd == "pushtest":
        ok = notify.pushtest(log=log) > 0
    elif cmd == "rules":
        os.makedirs(os.path.join(ROOT, "data", "out"), exist_ok=True)
        store.write_atomic(os.path.join(ROOT, "data", "out", "rules.json"), json.dumps({"flash": flash.rules(), "push": notify.rules()}, ensure_ascii=False))
        log("规则：data/out/rules.json")
        ok = True
    elif cmd == "seal-scenarios":
        from qx import forward
        for p in forward.seal():
            log("加密：" + os.path.relpath(p, ROOT))
        ok = True
    elif cmd == "replay":
        from qx import smallsignal, positioning
        D, aaii = store.load_all()
        a, b = (sys.argv[2:4] + ["2026-09-01", "2026-10-23"][len(sys.argv[2:4]):])[:2]
        rows = []
        for t in [d for d in D["^SOX"].index if a <= d.strftime("%Y-%m-%d") <= b]:
            Dt, _ = selftest.cut(D, aaii, t)                  # 截到那天：FRED 只要那天以前的观测
            pos = positioning.compute(Dt, t)
            ss = smallsignal.compute(Dt, t, pos)
            rows.append({"date": t.strftime("%Y-%m-%d"),
                         "signals": "；".join(f"{x['level']} {x['text']}" for x in ss["signals"]),
                         "crowd": "；".join(f"{c['market']}{c['word']}" for c in pos["crowd"] if c["word"] not in ("不挤", "数据不够")),
                         "asym": "；".join(f"{x['name']}：{x['asym']['word']}" for x in ss["signals"] if x["asym"]),
                         "chains": "；".join(f"{c['name']} {c['step']}/{c['of']}" + (f"，下一环 {c['next']['name']}" if c["next"] else "") for c in ss["chains"])})
        os.makedirs(os.path.join(store.HERE, "private"), exist_ok=True)
        p = os.path.join(store.HERE, "private", "replay.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "signals", "crowd", "asym", "chains"])
            w.writeheader()
            w.writerows(rows)
        log(f"回放：{len(rows)} 天，有小信号的 {sum(1 for r in rows if r['signals'])} 天（明细在 data/private/replay.csv，随 data.enc 加密）")
        ok = True
    elif cmd == "earn-refresh":
        from qx import earn
        earn.refresh(log=log)
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
