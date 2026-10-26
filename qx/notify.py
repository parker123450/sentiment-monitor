"""推送和试用记录（第 6 步，2026-10-23；第四轮第 1 步改成多渠道和推送总规则，2026-10-27）。规则在 口径.md 第七节、第九节。

渠道（有哪个 Secret 用哪个，可以同时开）：
  ntfy：NTFY_TOPIC（频道名就是密码；本机 ~/.config/qx/ntfy_topic）
  企业微信群机器人：WECOM_KEY（本机 ~/.config/qx/wecom_key）
  Bark（iOS）：BARK_KEY（本机 ~/.config/qx/bark_key）
推什么：
  1. "今天要知道的"里新出现的条目（同一天同一件事只推一次；几条一起出现合成一条）。
  2. 快讯：观察名单 ×（融资和信用 或 地缘和政策）的"第一次"；同一件事 1 小时内 3 家以上白名单来源报道（qx/flash.py）。
  3. 数据断了、自检没过（每天最多一次，不占上限）。
总规则（rules()，Worker 读同一份）：
  每天最多 DAY_CAP 条，"每天"从北京时间 08:00 算起；十年少见的（n10 ≤ 2）和数据断了、自检没过不占名额。
  超了的不丢：下一个北京 08:00 合成一条"没推的 N 件"（按少见程度排，只列标题）。
  同一件事（key）24 小时内只推一次。不设免打扰。
  每条带"发给 Claude"：claude.ai 新对话的链接，预填当时的数字和要推演的问题。
  第一次运行只记下现有的条目、不推。
日志只打条数，不打标题和正文（公开仓库的 Actions 日志谁都能看）。
试用记录：页面底部点一下，页面把这一条发到另一个 ntfy 频道（FEEDBACK_TOPIC）；云端取回来加密存进 data/private/trial_log.csv。
"""
import csv, json, os, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from qx import store, clock

PUSHED = os.path.join(store.HERE, "private", "pushed.json")
TRIAL = os.path.join(store.HERE, "private", "trial_log.csv")
TRIAL_COLS = ["at", "day", "seen", "useful", "note"]
SITE = "https://parker123450.github.io/sentiment-monitor/"
NTFY = "https://ntfy.sh"
WECOM = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={}"
BARK = "https://api.day.app/{}"
BJ = timezone(timedelta(hours=8))
DAY_CAP, DAY_START_H, REPEAT_H, RARE_N10 = 6, 8, 24, 2
CLAUDE_MAX = 2000


def _topic(env, fname):
    t = os.environ.get(env, "").strip()
    p = os.path.expanduser(f"~/.config/qx/{fname}")
    if not t and os.path.exists(p):
        t = open(p).read().strip()
    return t


def topic():
    return _topic("NTFY_TOPIC", "ntfy_topic")


def feedback_topic():
    return _topic("FEEDBACK_TOPIC", "feedback_topic")


def channels():
    return {k: v for k, v in (("ntfy", topic()), ("wecom", _topic("WECOM_KEY", "wecom_key")), ("bark", _topic("BARK_KEY", "bark_key"))) if v}


def rules():
    """推送总规则（Worker 和 Actions 读同一份）。"""
    return {"day_cap": DAY_CAP, "day_start_bj": DAY_START_H, "repeat_h": REPEAT_H, "rare_n10": RARE_N10, "quiet": None}


def _state():
    try:
        return json.load(open(PUSHED, encoding="utf-8"))
    except Exception:
        return None


def _save(st):
    os.makedirs(os.path.dirname(PUSHED), exist_ok=True)
    st["sent"] = dict(sorted(st.get("sent", {}).items(), key=lambda kv: kv[1])[-800:])
    store.write_atomic(PUSHED, json.dumps(st, ensure_ascii=False))


def push_day(now):
    """推送的"一天"：北京时间 08:00 切。"""
    b = now.astimezone(BJ) - timedelta(hours=DAY_START_H)
    return b.date().isoformat()


def claude_link(title, body):
    q = f"雷达推送（{datetime.now(BJ):%m-%d %H:%M} 北京）：{title}\n{body}\n\n请按现在的数字推演：这件事可能怎么传导，接下来看什么能证实或证伪。"
    return "https://claude.ai/new?q=" + urllib.parse.quote(q[:CLAUDE_MAX])


def send(title, msg, priority=3, log=print):
    """发到所有开着的渠道；返回发出去的渠道数。"""
    ch = channels()
    if not ch:
        return 0
    link = claude_link(title, msg)
    n = 0
    for k, v in ch.items():
        try:
            if k == "ntfy":
                body = {"topic": v, "title": title, "message": msg, "priority": priority, "click": SITE,
                        "actions": [{"action": "view", "label": "发给 Claude", "url": link}]}
                req = urllib.request.Request(NTFY, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
            elif k == "wecom":
                body = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{msg}\n[打开雷达]({SITE}) · [发给 Claude]({link})"}}
                req = urllib.request.Request(WECOM.format(v), data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
            else:
                body = {"title": title, "body": msg, "url": link, "group": "雷达", "level": "timeSensitive" if priority >= 4 else "active"}
                req = urllib.request.Request(BARK.format(v), data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                n += r.status == 200
        except Exception as e:
            log(f"  ! 推送渠道 {k} 没发出去：{type(e).__name__}")
    return n


def deliver(msgs, st, now=None, log=print):
    """按总规则发：去重、上限、超了的攒到下一个 08:00 合成一条。msgs：[{key, title, body, pri, rare, cap}]，cap=False 的不占名额。"""
    now = now or datetime.now(timezone.utc)
    day = push_day(now)
    sent = st.setdefault("sent", {})
    used = st.setdefault("used", {})
    held = st.setdefault("held", {})
    # 上一个推送日攒下的：到了新的一天先合成一条发
    for d in sorted(k for k in held if k < day):
        xs = sorted(held.pop(d), key=lambda x: (x.get("n10") is None, x.get("n10") or 0))
        if xs:
            title = f"没推的 {len(xs)} 件（{d[5:]}）"
            body = "\n".join("· " + x["title"] for x in xs[:12]) + ("\n……" if len(xs) > 12 else "")
            send(title, body, 3, log)
    cut = (now - timedelta(hours=REPEAT_H)).isoformat(timespec="minutes")
    out, n_held = [], 0
    for m in msgs:
        if sent.get(m["key"], "") >= cut:
            continue
        sent[m["key"]] = now.isoformat(timespec="minutes")
        if m.get("cap", True) and not m.get("rare"):
            if used.get(day, 0) >= DAY_CAP:
                held.setdefault(day, []).append({"title": m["title"], "n10": m.get("n10")})
                n_held += 1
                continue
            used[day] = used.get(day, 0) + 1
        out.append(m)
    st["used"] = {k: v for k, v in used.items() if k >= (now - timedelta(days=7)).date().isoformat()}
    n = 0
    for m in out:
        n += send(m["title"], m["body"], m.get("pri", 3), log) > 0
    if out or n_held:
        log(f"推送：{n} 条发出" + (f"，{n_held} 条超了上限攒到明早 08:00" if n_held else ""))
    return n


def push(data, ok, log=print, flash=None):
    """data：export.build 的结果；ok：自检有没有过；flash：qx.flash.run() 给的快讯候选。"""
    st = _state()
    first = st is None
    st = st or {"sent": {}}
    now = datetime.now(timezone.utc)
    ny = now.astimezone(clock.NY)
    today = ny.date().isoformat()
    msgs = []
    items = ((data or {}).get("today") or {}).get("items") or []
    new = [x for x in items if f"{x['key']}|{x['date']}" not in st["sent"]]
    if first:
        for x in items:
            st["sent"][f"{x['key']}|{x['date']}"] = now.isoformat(timespec="minutes")
        for x in flash or []:
            st["sent"][x["key"]] = now.isoformat(timespec="minutes")
        log(f"推送：第一次运行，记下现有 {len(items) + len(flash or [])} 条，不推")
        _save(st)
        return 0
    if new:
        hi = any(x["kind"] in ("judge", "stage") for x in new)
        rare = all((x.get("n10") is not None and x["n10"] <= RARE_N10) for x in new)
        if len(new) == 1:
            title, body = (new[0]["title"].split("：")[0] if "：" in new[0]["title"] else "今天要知道的"), new[0]["title"]
        else:
            title, body = f"今天要知道的 {len(new)} 件", "\n".join("· " + x["title"] for x in new[:8]) + ("\n……" if len(new) > 8 else "")
        for x in new[1:]:
            st["sent"][f"{x['key']}|{x['date']}"] = now.isoformat(timespec="minutes")
        msgs.append(dict(key=f"{new[0]['key']}|{new[0]['date']}", title=title, body=body, pri=4 if hi else 3, rare=rare,
                         n10=min((x["n10"] for x in new if x.get("n10") is not None), default=None)))
    for x in flash or []:
        msgs.append(dict(key=x["key"], title=x["title"], body=f"{x['body']}\n（{x['src']}）", pri=4 if x["kind"] == "first" else 3))
    for c in (((data or {}).get("radar") or {}).get("cards") or {}).get("cards") or []:      # 新满足的机会和风险卡（第四轮第 4 步）
        msgs.append(dict(key=c["key"], title=f"{c['cls_name']}：{c['title']}", body=f"{c['why']}\n哪里算错：{c['wrong']}", pri=3,
                         rare=c["rank"] is not None and c["rank"] <= 2 / 2520))
    if not ok and st.get("selftest_fail") != today:
        st["selftest_fail"] = today
        msgs.append(dict(key=f"selftest|{today}", title="雷达 · 自检没过", body="截断重算和全量不一致，网页这次没有发布。看 GitHub Actions 的日志。", pri=4, cap=False))
    if data and clock.is_trading_day(ny.date()) and (ny.hour, ny.minute) >= (18, 30) and data.get("asof") != clock.last_closed(ny) and st.get("stale") != today:
        st["stale"] = today
        msgs.append(dict(key=f"stale|{today}", title="雷达 · 数据没更新", body=f"美股日线还停在 {data.get('asof')}，最近一个交易日是 {clock.last_closed(ny)}。页面沿用旧数据。", pri=3, cap=False))
    if msgs and not channels():
        log("推送：没有推送渠道（NTFY_TOPIC / WECOM_KEY / BARK_KEY），不推")
    n = deliver(msgs, st, now, log) if channels() else 0
    _save(st)
    return n


def pushtest(log=print):
    """测试推送：正文写发送时间，用户看手机上的到达时间，报出差值。"""
    t = datetime.now(BJ)
    n = send("雷达 · 测试推送", f"发送时间 {t:%H:%M:%S}（北京）。请看手机通知上的时间，回复差了几秒。", 3, log)
    log(f"测试推送：发到 {n} 个渠道")
    return n


def pull_feedback(log=print):
    """把页面发来的试用记录取回来，存进加密的 trial_log.csv。"""
    t = feedback_topic()
    if not t:
        return 0
    rows = []
    if os.path.exists(TRIAL):
        with open(TRIAL, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    have = {r["at"] for r in rows}
    req = urllib.request.Request(f"{NTFY}/{t}/json?poll=1&since=12h", headers={"User-Agent": "qx-panel"})
    n = 0
    with urllib.request.urlopen(req, timeout=20) as r:
        for line in r.read().decode("utf-8").splitlines():
            try:
                m = json.loads(line)
                if m.get("event") != "message":
                    continue
                at = datetime.fromtimestamp(m["time"], timezone.utc).isoformat(timespec="seconds")
                if at in have:
                    continue
                j = json.loads(m.get("message") or "{}")
                rows.append({"at": at, "day": j.get("day", ""), "seen": " ".join(j.get("seen", [])), "useful": j.get("useful", ""), "note": (j.get("note") or "")[:300]})
                have.add(at)
                n += 1
            except Exception:
                continue
    if n:
        os.makedirs(os.path.dirname(TRIAL), exist_ok=True)
        tmp = TRIAL + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TRIAL_COLS)
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: r["at"]))
        os.replace(tmp, TRIAL)
        log(f"试用记录：取回 {n} 条")
    return n
