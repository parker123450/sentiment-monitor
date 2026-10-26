// node --test worker/test   （不用装任何包；Actions 的 worker.yml 也这样跑）
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { compile, tag, firsts, gate, digest, pushDay, rarity, candidates } from "../src/rules.js";
import { parseRss, parseTv, parseWscn, parseSpark, newsJobs, norm } from "../src/sources.js";

const fx = n => readFileSync(new URL(`./fixtures/${n}`, import.meta.url), "utf8");
const P = JSON.parse(fx("parity.json"));
const C = compile(P.rules);

test("打标签和 Python 一样", () => {
  for (const c of P.cases) assert.deepEqual(tag(C, c.t), { ents: c.ents, lines: c.lines }, c.t);
});

test("\"第一次\"和 Python 一样（按能看到的时间排序逐条算）", () => {
  const last = {}, got = {};
  const rows = [...P.rows].sort((a, b) => (a.seen || a.pub).localeCompare(b.seen || b.pub) || a.id.localeCompare(b.id));
  for (const r of rows) {
    const f = firsts(C, last, { ...r, ents: r.ents.split("|").filter(Boolean), lines: r.lines.split("|").filter(Boolean) });
    if (f.length) got[r.id] = f.join("|");
  }
  assert.deepEqual(got, P.firsts);
});

test("推送候选只要观察名单 × 融资和信用 / 地缘和政策", () => {
  const row = { t: "x", src: "路透" };
  const m = candidates(C, row, ["coreweave:credit", "coreweave:rates", "fed:credit", "nvidia:geo"]);
  assert.deepEqual(m.map(x => x.key), ["first:coreweave:credit", "first:nvidia:geo"]);
});

test("推送上限：每天 6 条，少见的不占名额，超了的第二天 08:00 合成一条", () => {
  const R = { day_cap: 6, day_start_bj: 8, repeat_h: 24 }, st = {};
  const t0 = Date.parse("2026-10-27T01:00:00Z");                 // 北京 09:00
  const msgs = Array.from({ length: 9 }, (_, i) => ({ key: "k" + i, title: "t" + i }));
  msgs.push({ key: "rare", title: "r", rare: true });
  assert.equal(gate(R, st, msgs, t0).length, 7);                  // 6 + 1 条少见的
  assert.equal(st.held[pushDay(t0)].length, 3);
  assert.equal(gate(R, st, [{ key: "k0", title: "again" }], t0 + 3600e3).length, 0);   // 24 小时内不重复
  assert.equal(digest(st, t0 + 3600e3).length, 0);               // 还是同一天
  const d = digest(st, Date.parse("2026-10-28T00:30:00Z"));       // 北京 08:30
  assert.equal(d.length, 1);
  assert.match(d[0].title, /没推的 3 件/);
});

test("推送的一天从北京 08:00 算", () => {
  assert.equal(pushDay(Date.parse("2026-10-26T23:59:00Z")), "2026-10-26");   // 北京 07:59
  assert.equal(pushDay(Date.parse("2026-10-27T00:00:00Z")), "2026-10-27");   // 北京 08:00
});

test("少见查表", () => {
  const tb = { up: [[0.03, 40], [0.05, 8], [0.08, 2]], down: [[0.03, 50], [0.06, 5]] };
  assert.equal(rarity(tb, 0.02), null);
  assert.equal(rarity(tb, 0.06), 8);
  assert.equal(rarity(tb, 0.09), 2);
  assert.equal(rarity(tb, -0.07), 5);
});

test("解析：TradingView 路透频道", () => {
  const xs = parseTv(fx("tv.html"));
  assert.ok(xs.length >= 10);
  assert.ok(xs.every(x => x.id.startsWith("https://www.tradingview.com/news/") && x.pub > 1.7e9 && x.t));
});

test("解析：谷歌新闻 RSS（来源名换成中文）", () => {
  const xs = parseRss(fx("gn.xml"), "");
  assert.ok(xs.length >= 1);
  assert.ok(xs.every(x => x.src === "路透" && !x.t.endsWith(" - Reuters")));
});

test("解析：华尔街见闻只要\"重要\"", () => {
  const xs = parseWscn(fx("wscn.json"));
  assert.ok(xs.length >= 1 && xs.every(x => x.src.startsWith("华尔街见闻")));
});

test("解析：Yahoo spark v7", () => {
  const q = parseSpark(fx("spark.json"));
  assert.ok(q["^GSPC"] && q["^GSPC"].p > 0 && q["^GSPC"].at > 1.7e9);
});

test("每 5 分钟轮一个谷歌新闻栏目", () => {
  const ids = [0, 5, 10, 15, 20].map(m => newsJobs(m)[2][0]);
  assert.deepEqual(ids, ["R3:markets", "R3:business", "R3:technology", "R3:world", "R3:markets"]);
  assert.equal(norm("https://a.com/x?y=1#z"), "https://a.com/x");
});
