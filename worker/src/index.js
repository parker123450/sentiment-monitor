// 雷达 Worker（第四轮第 1 步，2026-10-27）：轻活。重活在 GitHub Actions（Python）。规划第四节"架构"。
//
// 定时（wrangler.toml）：
//   */5 * * * *       第 0、5、10…分：快讯（TradingView 路透频道、谷歌新闻路透一个栏目、华尔街见闻）→ 去重、打标签、"第一次" → 推送
//   2-59/5 * * * *    第 2、7、12…分：开盘中的市场取价 → 查 Actions 给的少见表 → 十年少见的推送
//   0 0 * * *         每天：清 30 天前的快讯、7 天前的推送记录；合成"没推的 N 件"
// 接口（四把令牌按路径限权，比较用常数时间）：
//   GET  /live      READ_TOKEN    页面现取：价格、状态时点、快讯、各条路健康、最新的定时文字
//   POST /state     WRITE_TOKEN   Actions 推来规则、少见表、各市场时刻
//   POST /firsts    WRITE_TOKEN   Actions 推来白名单（彭博、WSJ 等）的（主体:线, 看到时间）
//   GET  /news      WRITE_TOKEN   Actions 取回快讯存档（?since=毫秒）
//   POST /push      WRITE_TOKEN   所有推送都走这里，统一上限、去重、合并
//   POST /brief     BRIEF_TOKEN   定时文字（第 6 步）
//   POST /ingest    INGEST_TOKEN  可选：Mac 上的 LSEG 官方桥送来的标题
//   GET  /ack?id=   不要令牌      推送测试回执（一次性编号）
// 只放公开的新闻标题、行情和读数；判断卡、三种走向不放。

import { compile, tag, firsts, candidates, gate, digest, moveMsgs, pushDay } from "./rules.js";
import { newsJobs, parse, sparkUrl, parseSpark } from "./sources.js";

const ORIGIN = "https://parker123450.github.io";
const SITE = "https://parker123450.github.io/sentiment-monitor/";
const KEEP_DAYS = 30, SHOW_H = 2, FAIL_STOP = 5, STOP_H = 1, RARE_PUSH = 2;
const PUSH_RULES = { day_cap: 6, day_start_bj: 8, repeat_h: 24, rare_n10: 2 };   // 默认；Actions 推来的 rules.push 覆盖

const json = (x, status = 200, h = {}) => new Response(JSON.stringify(x), { status, headers: { "content-type": "application/json; charset=utf-8", ...h } });

// 常数时间比较
function same(a, b) {
  const x = new TextEncoder().encode(a || ""), y = new TextEncoder().encode(b || "");
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x[i] || 0) ^ (y[i] || 0);
  return d === 0;
}
const authed = (req, env, k) => !!env[k] && same((req.headers.get("authorization") || "").replace(/^Bearer\s+/i, ""), env[k]);

// /live 限速：同一个实例里每个 IP 每分钟 10 次（实例之间不共享，做不到严格限速，靠令牌）
const hits = new Map();
function limited(req) {
  const ip = req.headers.get("cf-connecting-ip") || "?", m = Math.floor(Date.now() / 60e3), k = ip + ":" + m, n = (hits.get(k) || 0) + 1;
  hits.set(k, n);
  if (hits.size > 2000) hits.clear();
  return n > 10;
}

async function getState(env, k) {
  const r = await env.DB.prepare("SELECT v, at FROM state WHERE k = ?").bind(k).first();
  return r ? { v: JSON.parse(r.v), at: r.at } : null;
}
const putState = (env, k, v, at) => env.DB.prepare("INSERT INTO state (k, v, at) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, at = excluded.at").bind(k, JSON.stringify(v), at);

// ---------------------------------------------------------------- 推送
function claudeLink(title, body) {
  const t = new Date(Date.now() + 8 * 3600e3).toISOString().slice(5, 16).replace("T", " ");
  const q = `雷达推送（${t} 北京）：${title}\n${body}\n\n请按现在的数字推演：这件事可能怎么传导，接下来看什么能证实或证伪。`;
  return "https://claude.ai/new?q=" + encodeURIComponent(q.slice(0, 2000));
}

async function send(env, m) {
  const link = claudeLink(m.title, m.body), jobs = [];
  const post = (u, b) => fetch(u, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
  if (env.NTFY_TOPIC) jobs.push(post("https://ntfy.sh", { topic: env.NTFY_TOPIC, title: m.title, message: m.body, priority: m.pri || 3, click: SITE, actions: [{ action: "view", label: "发给 Claude", url: link }] }));
  if (env.WECOM_KEY) jobs.push(post(`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=${env.WECOM_KEY}`, { msgtype: "markdown", markdown: { content: `**${m.title}**\n${m.body}\n[打开雷达](${SITE}) · [发给 Claude](${link})` } }));
  if (env.BARK_KEY) jobs.push(post(`https://api.day.app/${env.BARK_KEY}`, { title: m.title, body: m.body, url: link, group: "雷达", level: (m.pri || 3) >= 4 ? "timeSensitive" : "active" }));
  const rs = await Promise.allSettled(jobs);
  return rs.filter(r => r.status === "fulfilled" && r.value.ok).length;
}

// 所有推送都过这里（Worker 自己的定时，和 Actions 经 /push 送来的）：读推送状态 → 去重和上限 → 写回 → 发。
// 状态是整包读、整包写，不是规划说的一条 INSERT … SELECT：两个请求恰好同时到时可能多推一条（两个定时错开 2 分钟、Actions 15 分钟一次，很少碰上）。
async function pushAll(env, msgs, now) {
  const R = { ...PUSH_RULES, ...(((await getState(env, "rules")) || {}).v || {}).push };
  const st = ((await getState(env, "push")) || {}).v || {};
  const out = digest(st, now, R.day_start_bj).concat(gate(R, st, msgs, now));
  for (const k in st.sent) if (st.sent[k] < now - 2 * 86400e3) delete st.sent[k];
  await putState(env, "push", st, now).run();
  let n = 0;
  for (const m of out) n += (await send(env, m)) > 0;
  if (out.length) await env.DB.batch(out.map(m => env.DB.prepare("INSERT OR REPLACE INTO pushlog (key, at, day, sent) VALUES (?, ?, ?, ?)").bind(m.key, now, pushDay(now, R.day_start_bj), 1)));
  return n;
}

// ---------------------------------------------------------------- 快讯
async function ingest(env, got, now) {
  const rules = await getState(env, "rules");
  const C = rules && rules.v.flash ? compile(rules.v.flash) : null;
  const all = Object.entries(got).flatMap(([route, xs]) => xs.map(x => ({ ...x, route })));
  if (!all.length) return { n: 0, msgs: [] };
  const have = new Set((await env.DB.prepare("SELECT route || ' ' || id AS k FROM news WHERE seen > ?").bind(now - 3 * 86400e3).all()).results.map(r => r.k));
  const fresh = all.filter(x => !have.has(x.route + " " + x.id));
  const rows = fresh.map(x => ({ ...x, seen: now, ...(C ? tag(C, x.t) : { ents: [], lines: [] }) }));
  const keys = [...new Set(rows.flatMap(r => r.ents.flatMap(e => r.lines.map(l => `${e}:${l}`))))];
  const last = {};
  if (C && keys.length) {
    const q = await env.DB.prepare(`SELECT k, at FROM firsts WHERE k IN (${keys.map(() => "?").join(",")})`).bind(...keys).all();
    for (const r of q.results) last[r.k] = r.at;
  }
  const msgs = [], stmts = [];
  for (const r of rows.sort((a, b) => a.pub - b.pub)) {
    const f = C ? firsts(C, last, { ...r, seen: new Date(now).toISOString() }) : [];
    r.first = f;
    if (f.length) msgs.push(...candidates(C, r, f));
    stmts.push(env.DB.prepare("INSERT OR IGNORE INTO news (route, id, src, t, pub, seen, ents, lines, first) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(r.route, r.id, r.src, r.t.slice(0, 300), r.pub, now, r.ents.join("|"), r.lines.join("|"), f.join("|")));
  }
  for (const k of keys) if (last[k] != null) stmts.push(env.DB.prepare("INSERT INTO firsts (k, at) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET at = MAX(at, excluded.at)").bind(k, last[k]));
  if (stmts.length) await env.DB.batch(stmts);
  const backfilled = (await getState(env, "backfill_done")) != null;   // 回补跑完以前只标不推（Actions 跑完 backfill 会推这个状态）
  return { n: rows.length, msgs: backfilled ? msgs : [] };
}

async function news(env, now) {
  const minute = new Date(now).getUTCMinutes(), got = {}, health = [];
  const H = Object.fromEntries((await env.DB.prepare("SELECT * FROM sources").all()).results.map(r => [r.id, r]));
  for (const [id, r] of newsJobs(minute)) {
    const h = H[id] || { id, fails: 0 };
    if ((h.stop_until || 0) > now) continue;
    try {
      const res = await fetch(r.url, { headers: { "user-agent": r.ua }, signal: AbortSignal.timeout(15000) });
      if (!res.ok) throw new Error("HTTP " + res.status);
      got[id] = parse(r.kind, await res.text(), r.src);
      Object.assign(h, { ok_at: now, fails: 0, n: got[id].length, err: null, stop_until: null });
    } catch (e) {
      h.fails = (h.fails || 0) + 1; h.err = String(e.message || e).slice(0, 60);
      if (h.fails >= FAIL_STOP) Object.assign(h, { stop_until: now + STOP_H * 3600e3, fails: 0 });
    }
    health.push(env.DB.prepare("INSERT OR REPLACE INTO sources (id, ok_at, fails, stop_until, n, err) VALUES (?, ?, ?, ?, ?, ?)").bind(id, h.ok_at || null, h.fails, h.stop_until || null, h.n || 0, h.err || null));
  }
  if (health.length) await env.DB.batch(health);
  const { msgs } = await ingest(env, got, now);
  if (msgs.length) await pushAll(env, msgs, now);
}

// ---------------------------------------------------------------- 价格
// markets（Actions 推来）：{syms: {代码: 市场}, sessions: {市场: [[开 ms, 收 ms], ...]}, always: [市场], rare: {代码: {up, down}}, names: {代码: 名字}}
async function prices(env, now) {
  const m = await getState(env, "markets");
  if (!m) return;
  const S = m.v, open = new Set(S.always || []);
  for (const [mk, ss] of Object.entries(S.sessions || {})) if (ss.some(([a, b]) => a <= now && now < b)) open.add(mk);
  const syms = Object.keys(S.syms || {}).filter(s => open.has(S.syms[s]));
  const out = {};
  for (let i = 0; i < syms.length && i < 20 * 10; i += 20) {         // 最多 10 批（子请求上限 50）
    try {
      const r = await fetch(sparkUrl(syms.slice(i, i + 20)), { headers: { "user-agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(15000) });
      if (r.ok) Object.assign(out, parseSpark(await r.text()));
    } catch { /* 这一批没取到，页面退回"15 分钟前，GitHub" */ }
  }
  const old = ((await getState(env, "prices")) || {}).v || {};
  const pack = { ...(old.p || {}), ...out };
  await putState(env, "prices", { p: pack, fetched: now, open: [...open] }, now).run();
  const msgs = moveMsgs(S, out, now, RARE_PUSH);                    // 十年 2 次以内的盘中涨跌（收益率按基点）
  if (msgs.length) await pushAll(env, msgs, now);
}

async function daily(env, now) {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM news WHERE seen < ?").bind(now - KEEP_DAYS * 86400e3),
    env.DB.prepare("DELETE FROM pushlog WHERE at < ?").bind(now - 7 * 86400e3),
  ]);
  await pushAll(env, [], now);                                       // 只为合成"没推的 N 件"
}

// ---------------------------------------------------------------- 页面现取
async function live(env, now) {
  const [p, rules, markets, src, nw, br] = await Promise.all([
    getState(env, "prices"), getState(env, "rules"), getState(env, "markets"),
    env.DB.prepare("SELECT * FROM sources").all(),
    env.DB.prepare("SELECT route, id, src, t, pub, seen, ents, lines, first FROM news WHERE seen > ? AND (ents != '' OR lines != '') ORDER BY pub DESC LIMIT 20").bind(now - SHOW_H * 3600e3).all(),
    env.DB.prepare("SELECT at, slot, text FROM brief ORDER BY at DESC LIMIT 1").first(),
  ]);
  return { now, prices: p && p.v, prices_at: p && p.at, state_at: { rules: rules && rules.at, markets: markets && markets.at }, sources: src.results, news: nw.results, brief: br || null };
}

// ---------------------------------------------------------------- 接口
async function body(req) { try { return await req.json(); } catch { return null; } }

export default {
  async fetch(req, env) {
    const url = new URL(req.url), p = url.pathname, now = Date.now();
    const cors = { "access-control-allow-origin": ORIGIN, "access-control-allow-headers": "authorization, content-type", vary: "Origin" };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    const no = () => json({ error: "auth" }, 401, cors);
    if (p === "/live" && req.method === "GET") {
      if (!authed(req, env, "READ_TOKEN")) return no();
      if (limited(req)) return json({ error: "slow down" }, 429, cors);
      return json(await live(env, now), 200, cors);
    }
    if (p === "/ack" && req.method === "GET") {
      const id = (url.searchParams.get("id") || "").slice(0, 40);
      if (!/^[0-9a-f]{16,40}$/.test(id)) return json({ error: "id" }, 400);
      await putState(env, "ack:" + id, now, now).run();
      return json({ ok: true, at: now });
    }
    if (p === "/brief" && req.method === "POST") {
      if (!authed(req, env, "BRIEF_TOKEN")) return no();
      const b = await body(req);
      if (!b || typeof b.text !== "string") return json({ error: "body" }, 400);
      await env.DB.prepare("INSERT OR REPLACE INTO brief (at, slot, text) VALUES (?, ?, ?)").bind(now, String(b.slot || ""), b.text.slice(0, 20000)).run();
      return json({ ok: true });
    }
    if (p === "/ingest" && req.method === "POST") {
      if (!authed(req, env, "INGEST_TOKEN")) return no();
      const b = await body(req);
      const xs = (Array.isArray(b) ? b : []).filter(x => x && x.id && x.t).slice(0, 200).map(x => ({ id: String(x.id), t: String(x.t), src: String(x.src || "路透"), pub: +x.pub || Math.floor(now / 1000) }));
      const r = await ingest(env, { LSEG: xs }, now);
      if (r.msgs.length) await pushAll(env, r.msgs, now);
      return json({ ok: true, n: r.n });
    }
    if (!authed(req, env, "WRITE_TOKEN")) return no();
    if (p === "/state" && req.method === "POST") {
      const b = await body(req) || {};
      const st = Object.entries(b).filter(([k]) => ["rules", "markets", "backfill_done"].includes(k)).map(([k, v]) => putState(env, k, v, now));
      if (st.length) await env.DB.batch(st);
      return json({ ok: true, n: st.length });
    }
    if (p === "/firsts" && req.method === "POST") {
      const b = (await body(req)) || [];
      const st = b.filter(x => x && x.k && x.at).slice(0, 2000).map(x => env.DB.prepare("INSERT INTO firsts (k, at) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET at = MAX(at, excluded.at)").bind(String(x.k), +x.at));
      if (st.length) await env.DB.batch(st);
      return json({ ok: true, n: st.length });
    }
    if (p === "/news" && req.method === "GET") {
      const since = +url.searchParams.get("since") || now - 86400e3;
      const r = await env.DB.prepare("SELECT route, id, src, t, pub, seen, ents, lines, first FROM news WHERE seen > ? ORDER BY seen LIMIT 3000").bind(since).all();
      return json({ ok: true, rows: r.results });
    }
    if (p === "/push" && req.method === "POST") {
      const b = await body(req) || {};
      const msgs = (b.msgs || []).filter(m => m && m.key && m.title).slice(0, 50);
      return json({ ok: true, sent: await pushAll(env, msgs, now) });
    }
    return json({ error: "not found" }, 404);
  },

  async scheduled(ev, env) {
    const now = ev.scheduledTime, m = new Date(now).getUTCMinutes();
    if (ev.cron === "0 0 * * *") return daily(env, now);
    if (m % 5 === 2) return prices(env, now);
    return news(env, now);
  },
};
