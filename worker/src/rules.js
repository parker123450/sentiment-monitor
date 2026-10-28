// 规则：和 Python（qx/flash.py、qx/notify.py）一模一样的打标签、"第一次"、推送上限。规则本身不写在这里：
// Actions 每 15 分钟把 rules.json（登记/entities.toml 导出）经 /state 推过来，Worker 用最新的一份。
// 改这里要同时改 Python，并跑 npm test（test/rules.test.js；fixtures/parity.json、push_cases.json 两边读同一组样例对拍）。

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

// 推送总规则：去重（repeat_h 小时内同 key 只推一次，合并进这条的 also 也记成推过）、每天上限（rare 和 cap=false 的不占名额）、超了的攒起来
// st = {sent: {key: ms}, used: {day: n}, held: {day: [{title, n10}]}}；返回这次要发的。和 qx/notify.py 的 gate() 一样（fixtures/push_cases.json 对拍）
export function gate(R, st, msgs, now) {
  const day = pushDay(now, R.day_start_bj), out = [], cut = now - R.repeat_h * 3600e3;
  st.sent = st.sent || {}; st.used = st.used || {}; st.held = st.held || {};
  for (const m of msgs) {
    if ((st.sent[m.key] || 0) >= cut) continue;
    for (const k of [m.key, ...(m.also || [])]) st.sent[k] = now;
    if (m.cap !== false && !m.rare) {
      if ((st.used[day] || 0) >= R.day_cap) { (st.held[day] = st.held[day] || []).push({ title: m.title, n10: m.n10 ?? null }); continue; }
      st.used[day] = (st.used[day] || 0) + 1;
    }
    out.push(m);
  }
  const old = pushDay(now - 7 * 86400e3, R.day_start_bj);
  for (const d of Object.keys(st.used)) if (d < old) delete st.used[d];
  return out;
}

// 上一个推送日攒下的，合成一条（按十年几次从少到多，只列标题）
export function digest(st, now, startH = 8) {
  const day = pushDay(now, startH), out = [];
  for (const d of Object.keys(st.held || {}).sort()) {
    if (d >= day) continue;
    const xs = st.held[d].map(x => typeof x === "string" ? { title: x, n10: null } : x)
      .sort((a, b) => (a.n10 == null) - (b.n10 == null) || (a.n10 || 0) - (b.n10 || 0));
    delete st.held[d];
    if (xs.length) out.push({ key: `digest:${d}`, title: `没推的 ${xs.length} 件（${d.slice(5)}）`, body: xs.slice(0, 12).map(x => "· " + x.title).join("\n") + (xs.length > 12 ? "\n……" : ""), pri: 3, cap: false });
  }
  return out;
}

// 盘中少见的涨跌 → 推送消息。S 是 Actions 推来的 markets（qx/markets.py 的 state()），quotes = {代码: {p, pc, at}}。
// 收益率（rare[s].bp）按基点查表；只看涨的（up_only：VIX、VXN）跌了不算；key 和 qx/watch.py 的盘中版一样（move:{组}:live|{UTC 日期}），
// 经同一个 /push 去重，Actions 15 分钟一次推的同一件事不会再推一遍。
export function moveMsgs(S, quotes, now, maxN10 = 2) {
  const out = [], up = new Set(S.up_only || []);
  for (const [s, q] of Object.entries(quotes || {})) {
    if (!q || !q.p || !q.pc) continue;
    const tb = (S.rare || {})[s], bp = !!(tb && tb.bp), r = bp ? (q.p - q.pc) * 100 : Math.log(q.p / q.pc);
    if (up.has(s) && r < 0) continue;
    const n10 = rarity(tb, r);
    if (n10 == null || n10 > maxN10) continue;
    const at = (q.at || now / 1000) * 1000, day = new Date(at).toISOString().slice(0, 10), nm = (S.names || {})[s] || s;
    const move = bp ? `${r >= 0 ? "升" : "降"} ${Math.abs(r).toFixed(0)} 个基点` : `${r >= 0 ? "涨" : "跌"} ${(Math.abs(Math.exp(r) - 1) * 100).toFixed(1)}%`;
    out.push({ key: `move:${(S.groups || {})[s] || s}:live|${day}`, title: `${nm} ${move}`, pri: 4, rare: true, n10,
      body: `过去 10 年同方向这么大的只有 ${Math.round(n10 * 10) / 10} 次（盘中，截至 ${new Date(at + 8 * 3600e3).toISOString().slice(11, 16)} 北京）。` });
  }
  return out;
}

// 少见查表：Actions 给的每个标的两个方向最极端的 40 个历史涨跌 [[值, 名次], ...]（值从小到大）和窗口长度 n。
// 返回"过去 10 年同方向至少这么极端的天数"（按 2520 天折算，和 qx/watch.py 的 n10 一样）；不到第 40 名那么极端的返回 null。
export function rarity(table, r) {
  if (!table || r == null || r === 0) return null;
  const side = (r > 0 ? table.up : table.down) || [], a = Math.abs(r);
  if (!side.length || a < side[0][0]) return null;
  const cnt = side.filter(([v]) => v >= a).length;
  return cnt * 2520 / (table.n || 2520);
}
