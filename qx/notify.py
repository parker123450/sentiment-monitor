"""推送和试用记录（第 6 步，2026-10-23）。规则在 口径.md 第七节。

推送（ntfy，手机装 ntfy App 订阅频道；频道名就是密码，在 GitHub Secret NTFY_TOPIC，本机 ~/.config/qx/ntfy_topic）：
  1. "今天要知道的"里新出现的条目：每条（同一天同一件事）只推一次；几条一起出现就合成一条推送。和判断有关、阶段变了的用高优先级。
  2. 数据断了：美东 18:30 以后，美股的日线还不是最近一个交易日（每个交易日最多一次）。
  3. 自检没过：页面不发布，推一条（每天最多一次）。
  第一次运行只记下现有的条目、不推，免得一上来推一堆。
试用记录：页面底部点一下（看了哪几块、帮上没有、一句话），页面把这一条发到另一个 ntfy 频道（FEEDBACK_TOPIC）；
  云端每次运行把新的取回来，加密存进 data/private/trial_log.csv。
"""
import csv, json, os, urllib.request
from datetime import datetime, timezone

from qx import store, clock

PUSHED = os.path.join(store.HERE, "private", "pushed.json")
TRIAL = os.path.join(store.HERE, "private", "trial_log.csv")
TRIAL_COLS = ["at", "day", "seen", "useful", "note"]
SITE = "https://parker123450.github.io/sentiment-monitor/"
NTFY = "https://ntfy.sh"


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


def _state():
    try:
        return json.load(open(PUSHED, encoding="utf-8"))
    except Exception:
        return None


def _save(st):
    os.makedirs(os.path.dirname(PUSHED), exist_ok=True)
    keep = sorted(st.get("sent", {}).items(), key=lambda kv: kv[1])[-500:]
    st["sent"] = dict(keep)
    store.write_atomic(PUSHED, json.dumps(st, ensure_ascii=False))


def send(title, msg, priority=3, log=print):
    t = topic()
    if not t:
        log("推送：没有 NTFY_TOPIC，不推")
        return False
    body = json.dumps({"topic": t, "title": title, "message": msg, "priority": priority, "click": SITE}).encode("utf-8")
    req = urllib.request.Request(NTFY, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status == 200


def push(data, ok, log=print):
    """data：export.build 的结果；ok：自检有没有过。"""
    st = _state()
    first = st is None
    st = st or {"sent": {}}
    now = datetime.now(timezone.utc)
    ny = now.astimezone(clock.NY)
    today = ny.date().isoformat()
    msgs = []
    items = ((data or {}).get("today") or {}).get("items") or []
    new = []
    for x in items:
        k = f"{x['key']}|{x['date']}"
        if k not in st["sent"]:
            st["sent"][k] = now.isoformat(timespec="minutes")
            new.append(x)
    if new and not first:
        hi = any(x["kind"] in ("judge", "stage") for x in new)
        if len(new) == 1:
            msgs.append((new[0]["title"].split("：")[0] if "：" in new[0]["title"] else "今天要知道的", new[0]["title"], 4 if hi else 3))
        else:
            msgs.append((f"今天要知道的 {len(new)} 件", "\n".join("· " + x["title"] for x in new[:8]) + ("\n……" if len(new) > 8 else ""), 4 if hi else 3))
    if not ok and st.get("selftest_fail") != today:
        st["selftest_fail"] = today
        msgs.append(("情绪面板 · 自检没过", "截断重算和全量不一致，网页这次没有发布。看 GitHub Actions 的日志。", 4))
    if data and clock.is_trading_day(ny.date()) and (ny.hour, ny.minute) >= (18, 30) and data.get("asof") != clock.last_closed(ny) and st.get("stale") != today:
        st["stale"] = today
        msgs.append(("情绪面板 · 数据没更新", f"美股日线还停在 {data.get('asof')}，最近一个交易日是 {clock.last_closed(ny)}。页面沿用旧数据。", 3))
    for title, msg, pr in msgs:
        try:
            send(title, msg, pr, log)
            log(f"推送：{title}")
        except Exception as e:
            log(f"  ! 推送没发出去：{e}")
    if first:
        log(f"推送：第一次运行，记下现有 {len(items)} 条，不推")
    _save(st)


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
