// 快讯的几条路和解析（和 qx/flash.py 的 ROUTES、parse_* 一样）。解析用正则，不建 DOM（省 CPU）。
// Worker 每 5 分钟只取三样：TradingView 路透频道（R6）、谷歌新闻路透一个栏目（R3，四个栏目轮流，每个栏目 20 分钟一次）、华尔街见闻快讯（R5）。
// 别的 RSS 留在 Actions 里每 15 分钟取。

export const UA = "qx-radar/1.0 (+https://github.com/parker123450/sentiment-monitor)";
export const UA_PANEL = "Mozilla/5.0";      // 面板现有来源（谷歌新闻、华尔街见闻）原来的请求头，用户定之前不改
export const R3_SECTIONS = ["markets", "business", "technology", "world"];
export const r3Url = s => `https://news.google.com/rss/search?q=${encodeURIComponent(`when:1h site:reuters.com/${s}`)}&hl=en-US&gl=US&ceid=US:en`;
export const ROUTES = {
  R6: { src: "路透", via: "TradingView", url: "https://www.tradingview.com/news/top-providers/reuters/", ua: UA, kind: "tv" },
  R5: { src: "华尔街见闻", via: "", url: "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=100", ua: UA_PANEL, kind: "wscn" },
};
const SRC_MAP = { "Reuters": "路透", "Bloomberg.com": "彭博", "Bloomberg": "彭博", "WSJ": "华尔街日报", "The Wall Street Journal": "华尔街日报",
  "Financial Times": "金融时报", "CNBC": "CNBC", "Nikkei Asia": "日经", "Yonhap News Agency": "韩联社" };
const WSCN_DROP = /归母净利润|营业收入|营收同比|净利润同比|扣非|^提醒：日内请重点关注|^早间要闻汇总/;

const unesc = s => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&amp;/g, "&");
const cdata = s => s.replace(/^<!\[CDATA\[|\]\]>$/g, "").trim();

export function norm(link) {
  if (link.includes("news.google.com")) return link.split("?")[0];
  try { const u = new URL(link); return `${u.protocol}//${u.host}${u.pathname}`; } catch { return link; }
}

export function parseRss(xml, src) {
  const out = [];
  for (const m of xml.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/g)) {
    const it = m[1], g = tag => { const x = it.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`)); return x ? x[1].trim() : ""; };
    let title = unesc(cdata(g("title"))), link = unesc(cdata(g("link"))), s = unesc(g("source"));
    if (s && title.endsWith(" - " + s)) title = title.slice(0, -(s.length + 3)).trim();
    const pub = Date.parse(g("pubDate"));
    if (!title || !link.startsWith("http") || isNaN(pub)) continue;
    out.push({ id: norm(link), t: title, src: src || SRC_MAP[s] || s, pub: Math.floor(pub / 1000) });
  }
  return out;
}

const TV_RE = /\{"id":"(tag:reuters\.com[^"]+)","title":"((?:[^"\\]|\\.)*)","storyPath":"([^"]*)","published":(\d+),"urgency":(\d)/g;
export function parseTv(text) {
  const out = [];
  for (const m of text.matchAll(TV_RE)) out.push({ id: "https://www.tradingview.com" + m[3], t: JSON.parse(`"${m[2]}"`), src: "路透", pub: +m[4], urgent: m[5] === "1" });
  return out;
}

export function parseWscn(text) {
  const j = JSON.parse(text), out = [];
  for (const x of (j.data && j.data.items) || []) {
    const body = (x.title || "") + (x.content_text || "");
    if ((x.score || 1) < 2 || WSCN_DROP.test(body)) continue;
    const t = (x.title || "").trim() || (x.content_text || "").replace(/\s+/g, " ").trim().slice(0, 90);
    if (!t || !x.display_time) continue;
    const src = "华尔街见闻" + (body.includes("路透") ? "（转述路透）" : body.includes("彭博") ? "（转述彭博）" : "");
    out.push({ id: `https://wallstreetcn.com/livenews/${x.id}`, t, src, pub: x.display_time });
  }
  return out;
}

export function parse(kind, text, src) {
  return kind === "tv" ? parseTv(text) : kind === "wscn" ? parseWscn(text) : parseRss(text, src);
}

// 这次（第几个 5 分钟）要取哪几条路
export function newsJobs(minute) {
  const s = R3_SECTIONS[Math.floor(minute / 5) % R3_SECTIONS.length];
  return [["R6", ROUTES.R6], ["R5", ROUTES.R5], [`R3:${s}`, { src: "", via: "谷歌新闻", url: r3Url(s), ua: UA_PANEL, kind: "rss" }]];
}

// Yahoo 批量行情（v7 spark 带 regularMarketTime；第 0 步实测一次 20 个）
export const sparkUrl = syms => `https://query1.finance.yahoo.com/v7/finance/spark?symbols=${encodeURIComponent(syms.join(","))}&range=1d&interval=5m`;
export function parseSpark(text) {
  const j = JSON.parse(text), out = {};
  for (const x of (j.spark && j.spark.result) || []) {
    const r = (x.response || [])[0] || {}, m = r.meta || {};
    if (m.regularMarketPrice != null) out[x.symbol] = { p: m.regularMarketPrice, at: m.regularMarketTime, pc: m.chartPreviousClose ?? m.previousClose };
  }
  return out;
}
