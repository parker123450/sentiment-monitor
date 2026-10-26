// 规则：和 Python（qx/flash.py、qx/notify.py）一模一样的打标签、"第一次"、推送上限。规则本身不写在这里：
// Actions 每 15 分钟把 rules.json（登记/entities.toml 导出）经 /state 推过来，Worker 用最新的一份。
// 改这里要同时改 Python，并跑 test/parity.test.js（两边读同一组样例对拍）。

const NONASCII = /[^\x00-\x7f]/;
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// 公司和机构的别名：区分大小写，英文按整词
export function aliasRe(words) {
  return new RegExp(words.map(w => NONASCII.test(w) ? esc(w) : `(?<![A-Za-z0-9])${esc(w)}(?![A-Za-z0-9])`).join("|"), "u");
}

// 六条线的关键词：不分大小写；英文按整词，允许 s/es/d/ed/ing 词尾；以 * 结尾的按词头
export function kwRe(words) {
  return new RegExp(words.map(w => {
    if (NONASCII.test(w)) return esc(w);
    if (w.endsWith("*")) return `(?<![A-Za-z0-9])${esc(w.slice(0, -1))}`;
    return `(?<![A-Za-z0-9])${esc(w)}(?:s|es|d|ed|ing)?(?![A-Za-z0-9])`;
  }).join("|"), "iu");
}

export function compile(rules) {
  return {
    ents: rules.entities.map(e => ({ id: e.id, name: e.name, watch: !!e.watch, re: aliasRe(e.alias) })),
    lines: rules.lines.map(l => ({ id: l.id, name: l.name, re: kwRe(l.kw) })),
    white: new Set(rules.white), firstDays: rules.first_days, pushLines: new Set(rules.push_lines),
  };
}

export function tag(C, title) {
  return { ents: C.ents.filter(e => e.re.test(title)).map(e => e.id), lines: C.lines.filter(l => l.re.test(title)).map(l => l.id) };
}

// "第一次"：last 是 {"主体:线": 上次看到的毫秒}；返回这条新标的 key，并更新 last
export function firsts(C, last, row) {
  if (!C.white.has(row.src)) return [];
  const out = [], at = Date.parse(row.seen || row.pub), span = C.firstDays * 86400e3;
  for (const e of row.ents) for (const l of row.lines) {
    const k = `${e}:${l}`, prev = last[k];
    if (prev == null || at - prev > span) out.push(k);
    last[k] = at;
  }
  return out;
}

// 推送的"一天"：北京时间 08:00 切
export function pushDay(ms, startH = 8) {
  return new Date(ms + (8 - startH) * 3600e3).toISOString().slice(0, 10);
}

// 推送候选：观察名单 × 推送的线 的"第一次"
export function candidates(C, row, newFirsts) {
  const watch = new Set(C.ents.filter(e => e.watch).map(e => e.id)), name = id => (C.ents.find(e => e.id === id) || {}).name || id;
  const lineName = id => (C.lines.find(l => l.id === id) || {}).name || id;
  return newFirsts.filter(k => { const [e, l] = k.split(":"); return watch.has(e) && C.pushLines.has(l); })
    .map(k => { const [e, l] = k.split(":"); return { kind: "first", key: `first:${k}`, title: `第一次：${name(e)} × ${lineName(l)}`, body: `${row.t}\n（${row.src}）`, pri: 4 }; });
}

// 推送总规则：去重（repeat_h 小时内同 key 只推一次）、每天上限（rare 和 cap=false 的不占名额）、超了的攒起来
// st = {sent: {key: ms}, used: {day: n}, held: {day: [title]}}；返回这次要发的
export function gate(R, st, msgs, now) {
  const day = pushDay(now, R.day_start_bj), out = [], cut = now - R.repeat_h * 3600e3;
  st.sent = st.sent || {}; st.used = st.used || {}; st.held = st.held || {};
  for (const m of msgs) {
    if ((st.sent[m.key] || 0) >= cut) continue;
    st.sent[m.key] = now;
    if (m.cap !== false && !m.rare) {
      if ((st.used[day] || 0) >= R.day_cap) { (st.held[day] = st.held[day] || []).push(m.title); continue; }
      st.used[day] = (st.used[day] || 0) + 1;
    }
    out.push(m);
  }
  return out;
}

// 上一个推送日攒下的，合成一条
export function digest(st, now, startH = 8) {
  const day = pushDay(now, startH), out = [];
  for (const d of Object.keys(st.held || {}).sort()) {
    if (d >= day) continue;
    const xs = st.held[d]; delete st.held[d];
    if (xs.length) out.push({ key: `digest:${d}`, title: `没推的 ${xs.length} 件（${d.slice(5)}）`, body: xs.slice(0, 12).map(x => "· " + x).join("\n") + (xs.length > 12 ? "\n……" : ""), cap: false });
  }
  return out;
}

// 少见查表：Actions 给的每个标的"1 日对数涨跌 → 过去 10 年同方向几次"的分段表 [[阈值, 次数], ...]（阈值从小到大）
export function rarity(table, r) {
  if (!table || r == null) return null;
  const side = r >= 0 ? table.up : table.down, a = Math.abs(r);
  let n = null;
  for (const [th, cnt] of side || []) if (a >= th) n = cnt;
  return n;
}
