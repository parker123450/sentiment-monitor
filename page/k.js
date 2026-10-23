// 情绪阶段页面的脚本。RAW 由 qx/page.py 塞在前面。K 线部分照「科技情绪全景」的 K 线（版式、交互、画线、面板）搬过来，换成新的阶段和恐慌读数。
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
  const fmt = (x, dp = 2) => x == null || !isFinite(x) ? "—" : x.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const sgn = (x, dp = 2) => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), dp);
  const lastOf = a => a[a.length - 1];
  const tok = name => (getComputedStyle(document.documentElement).getPropertyValue(name) || "").trim();
  function hexToRgb(h) {
    h = (h || "").trim(); if (h.startsWith("rgb")) return h.replace(/[^\d,]/g, "").split(",").slice(0, 3).map(Number);
    if (h.length === 4) h = "#" + h[1] + h[1] + h[2] + h[2] + h[3] + h[3];
    const v = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); return v.some(isNaN) ? [128, 128, 128] : v;
  }
  const cP = v => v == null || !isFinite(v) ? "" : ` class="${v >= 0 ? "pos" : "neg"}"`;
  const pctP = v => v == null || !isFinite(v) ? "—" : sgn(v, 1) + "%";
  const md = s => `${+s.slice(5, 7)} 月 ${+s.slice(8)} 日`;
  const D = RAW.daily, DMAP = new Map(D.d.map((d, i) => [d, i])), NAMES = RAW.stnames, LASTK = D.d.length - 1;
  const SFILL = s => tok(["--grid", "--s1", "--s2", "--s3", "--s4"][s] || "--grid"), SINK = s => tok(["--ink-3", "--s1i", "--s2i", "--s3i", "--s4i"][s] || "--ink-3");
  const row = k => { const o = {}; for (const key in D) o[key] = D[key][k]; return o; };
  const FOMC = (RAW.happen && RAW.happen.day && RAW.happen.day.fomc) || {}, DAYNEWS = (RAW.happen && RAW.happen.day && RAW.happen.day.news) || {};

  // ---------- 把一天的数字写成白话（三段各几条）
  const level = p => p == null ? [0, "—"] : p >= 90 ? [2, "历史上少见"] : p >= 70 ? [1, "偏高"] : [0, "平常"];
  function facts(r) {
    const pc = (a, b) => Math.round((a / b - 1) * 100);
    return [
      [[r.nb20p, `${r.nb20} / ${r.n20} 只半导体股跌破了 20 日线`],
       [r.nlowp, `最近 5 天平均每天 ${fmt(r.nlow, 1)} 只创 20 天新低`],
       [r.volxp, `成交量是平时的 ${fmt(r.volx, 2)} 倍`],
       [r.r10p, `10 天${r.r10 < 0 ? "跌" : "涨"}了 ${fmt(Math.abs(r.r10), 1)}%，是平常 10 天波动的 ${fmt(r.r10x, 1)} 倍`]],
      [[r.vxnrp, `科技股保险（VXN）${fmt(r.vxn, 1)}，平时 ${fmt(r.vxnm, 1)}，${r.vxn >= r.vxnm ? "贵了" : "便宜"} ${Math.abs(pc(r.vxn, r.vxnm))}%`],
       [r.vixrp, `大盘保险（VIX）${fmt(r.vix, 1)}，平时 ${fmt(r.vixm, 1)}，${r.vix >= r.vixm ? "贵了" : "便宜"} ${Math.abs(pc(r.vix, r.vixm))}%`],
       [r.t3rp, `1 个月保险的价格是 3 个月的 ${Math.round(r.t3 * 100)}%（平时 ${Math.round(r.t3m * 100)}%）${r.t3 >= 1 ? "：近的比远的还贵，大家怕的就是眼前" : ""}`],
       [r.aaiisp, `散户看多减看空 ${sgn(r.aaii, 1)}%，一周前 ${sgn(r.aaiip, 1)}%`]],
      [[r.pcrp, `股票期权里买跌和买涨的比例 ${fmt(r.pc, 2)}，平时 ${fmt(r.pcm, 2)}${r.pcrp < 70 ? "：没人抢着买保护" : r.pcrp >= 90 ? "：大家在抢着买保护" : ""}`],
       [r.etfp, `信用 ETF 跑输国债：${r.etfp == null ? "—" : r.etfp >= 90 ? "比历史上 90% 的日子都差" : r.etfp >= 70 ? "比平时差" : "平常"}（单独提醒，不算进投降）`],
       [r.baarp, `公司债比国债多要的利息，20 天里${r.baa20 >= 0 ? "多了" : "少了"} ${Math.abs(r.baa20)} 个基点`],
       [r.vixlp, `VIX ${fmt(r.vix, 1)}；大跌见底时常在 30 上下`]],
    ];
  }
  const factHTML = (list, s) => list.map(([p, t]) => { const [lv, w] = level(p), c = lv === 2 ? SINK(s) : lv === 1 ? tok("--ink-2") : tok("--ink-3");
    return `<div class="fact"><span class="m" style="color:${c}">${lv === 2 ? "✓" : "·"}</span><span class="x">${t}</span><span class="w" style="color:${c}">${w}</span></div>`; }).join("");

  // ---------- 顶部：一句话、四条读数、最近一年
  const LVW = p => level(p)[1], MW = RAW.momwords || [];
  const LVS = p => p == null ? "—" : p >= 90 ? "少见" : p >= 70 ? "偏高" : "平常";      // 副图那一行地方小，用短词
  const LN = [["sell", "抛售", "msell", "成分股一起跌、创新低"], ["price", "定价", "mprice", "科技股保险比平时贵"], ["pos", "仓位", "mpos", "抢买认沽、散户转空"], ["credit", "信用", "mcredit", "信用 ETF 跑输国债"]];
  (function head() {
    const r = row(LASTK), st = r.state, ccc = RAW.ice["CCC 及以下"], ig = RAW.ice["投资级"];
    $("asof").textContent = `数据截至 ${RAW.asof} 收盘`;
    $("upd").textContent = ` 页面更新于北京时间 ${RAW.updated}。`;
    const warn = [];
    for (const [nm, v] of Object.entries(RAW.status || {})) {
      if (!v.last) { warn.push(`${nm}没有数据`); continue; }
      const lag = (Date.parse(RAW.asof) - Date.parse(v.last)) / 864e5;
      if (lag > (nm.startsWith("AAII") ? 9 : 4)) warn.push(`${nm}最新只到 ${md(v.last)}`);
    }
    if (warn.length) { $("warn").hidden = false; $("warn").textContent = "数据提醒：" + warn.join("；") + "。相关读数沿用最近一次的。"; }
    const tail = { 0: "没有在下跌。", 1: "抛售开始了，还没人怕。", 2: "投降还没来。", 3: "历史上最低点多在这几天或之后。", 4: "恐慌在退。" }[st];
    $("hero").innerHTML = `<span class="tag" style="background:${SFILL(st)};color:${SINK(st)}">${st >= 1 && st <= 3 ? "第" + "一二三"[st - 1] + "段" : "现在"}</span>${NAMES[st]}。${tail}`;
    let lead = `费城半导体 10 天${r.r10 < 0 ? "跌" : "涨"}了 ${fmt(Math.abs(r.r10), 1)}%，离一年高点 ${fmt(r.dd, 1)}%。`;
    if (r.regime === 1) lead += `这次是宏观冲击型：这一段 VIX 最高到过 ${fmt(r.vixmax, 1)}，大盘也在怕。`;
    if (r.regime === 2) lead += `这次是板块自己跌：这一段 VIX 最高只有 ${fmt(r.vixmax, 1)}，大盘读数看不出来，要看"比自己最近"的读数和成分股。`;
    if (st >= 1) lead += `${r.n20} 只半导体股里 ${r.nb20} 只跌破了 20 日线，成交量是平时的 ${fmt(r.volx, 2)} 倍。`;
    if (st >= 2) lead += `科技股保险比平时贵了 ${Math.round((r.vxn / r.vxnm - 1) * 100)}%。`;
    if (st === 2) {
      const parts = [r.etfp >= 90 ? "信用 ETF 已经明显跑输国债" : "信用 ETF 还在平常范围"];
      if (ccc) parts.push(`最差的公司（CCC）利差一个月${ccc.now >= ccc.m1 ? "走阔" : "收窄"}了 ${Math.abs(ccc.now - ccc.m1)} 个基点`);
      lead += parts.join("，") + "；" + (r.pcrp >= 90 ? "大家已经在抢着买保护" : "但还没人抢着买保护") + (ig ? `，投资级利差一个月${ig.now >= ig.m1 ? "多" : "少"}了 ${Math.abs(ig.now - ig.m1)} 个基点。` : "。");
    }
    $("lead").textContent = lead;
    $("lines").innerHTML = LN.map(([k, nm, mk, what]) => { const [lv, w] = level(r[k]), m = r[mk], c = lv === 2 ? tok("--alert") : lv === 1 ? tok("--ink-2") : tok("--ink-3");
      return `<div class="ln"><span class="k">${nm}</span><span class="mv" style="white-space:normal">${what}</span><span class="w"><b style="color:${c}">${w}</b>${m == null ? "" : " · " + MW[m]}</span></div>`; }).join("") +
      (RAW.cnn ? `<div class="ln cnn"><span class="k">CNN</span><span>恐慌贪婪 ${RAW.cnn.now}，${esc(RAW.cnn.word)}${RAW.cnn.w1 != null ? `（一周前 ${RAW.cnn.w1}，一个月前 ${RAW.cnn.m1 ?? "—"}）` : ""}。只作参考，用的都是大盘读数</span></div>` : "");
    const F3 = facts(r), since = s => { if (!(st >= s && st <= 3)) return null; let k = LASTK; while (k > 0 && D.state[k - 1] >= s && D.state[k - 1] <= 3) k--; return D.d[k]; };
    ["在卖", "在怕", "投降"].forEach((nm, i) => {
      const s = i + 1, on = st >= s && st <= 3, sd = since(s), el = document.createElement("div");
      el.className = "step" + (on ? " on" : ""); if (on) el.style.borderColor = SINK(s);
      el.innerHTML = `<div class="no">第${"一二三"[i]}段</div><div class="t">${nm}</div><div class="st" style="color:${on ? SINK(s) : tok("--ink-3")}">${on ? "✓ 已到" + (sd ? "，" + md(sd) + "起" : "") : "○ 还没来"}</div>${factHTML(F3[i], s)}`;
      $("steps").appendChild(el);
    });
    const NEXT = {
      0: `<b>说明：</b>三段是历次大跌的共同顺序：先在卖，再在怕，最后投降。现在没有在下跌。`,
      1: `<b>接下来看什么：</b>在怕那一步：大盘或科技股保险比平时贵、散户突然转空，历史上多在最低点前 1 到 3 周。`,
      2: `<b>接下来看什么：</b>投降那一步通常是：股票期权里买跌的比例突然升高（大家抢着买保护）、信用利差从最差的公司扩散到投资级、VIX 冲高。历史上这一步多在最低点前后几天出现。` + (r.regime === 2 ? `这次是半导体自己跌（大盘 VIX 不高），投降可能只体现在"比平时"高很多，VIX 未必到 30。` : ""),
      3: `<b>接下来看什么：</b>投降已经来了，但进入投降只有约两成在 3 周内见底。看恐慌什么时候退：三条读数一起回落、价格不再创新低。`,
      4: `<b>接下来看什么：</b>恐慌在退。留意二次探底：价格回到这一段低点附近，但恐慌没跟上，历史上多是好事；恐慌重新升起来就要回到前面几段。`,
    };
    $("next").innerHTML = NEXT[st];
    $("groups").innerHTML = `<tr><th>组</th><th class="r">跌破 20 日线</th><th class="r">今天创新低</th><th class="r">10 天</th><th class="r">离一年高点</th></tr>` +
      RAW.groups.map(g => `<tr><td class="nm">${esc(g.name)}${g.names ? `<small>${esc(g.names)}</small>` : ""}</td><td class="r num">${g.below} / ${g.n}</td><td class="r num">${g.low}</td><td class="r num ${g.r10 < 0 ? "neg" : "pos"}">${sgn(g.r10, 1)}%</td><td class="r num">${g.dd}%</td></tr>`).join("");
    $("ice").innerHTML = `<tr><th>评级</th><th class="r">现在</th><th class="r">一个月里</th><th>三年里的位置</th></tr>` +
      Object.entries(RAW.ice).map(([k, v]) => { const p = (v.now - v.lo) / ((v.hi - v.lo) || 1) * 100, ch = v.now - v.m1;
        return `<tr><td>${esc(k)}</td><td class="r num">${v.now}</td><td class="r num" style="color:${ch >= 30 ? tok("--alert") : tok("--ink-2")}">${sgn(ch, 0)}</td><td><div class="bar" title="三年最低 ${v.lo}，最高 ${v.hi}"><i style="width:${Math.max(3, p).toFixed(0)}%"></i></div></td></tr>`; }).join("");
  })();

  // ---------- 今天要知道的（规则在 口径.md 第三节；文字在 qx/watch.py 写好，这里只排版）
  (function today() {
    const T = RAW.today, el = $("today"); if (!T || !el) return;
    const wk = d => "周" + "日一二三四五六"[new Date(d + "T12:00:00").getDay()];
    const card = x => `<div class="it${x.us ? " us" : ""}"><div class="it-h"><span>${x.n10 == null ? esc(x.hist || "") : `过去 10 年 ${x.n10 < 1 ? "不到 1" : Math.round(x.n10)} 次`}</span>${x.live ? `<span class="it-tag">${esc(x.state || "盘中")}</span>` : ""}<span>${md(x.date)}</span></div>
      <div class="it-t">${esc(x.title)}</div>${(x.facts || []).length ? `<ul>${x.facts.map(f => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}${x.mean ? `<p class="it-m"><b>说明什么：</b>${esc(x.mean)}</p>` : ""}${(x.news || []).length ? `<div class="nwh">同一时间的新闻（程序按关键词配的，可能不是原因）</div><ul class="nw">${x.news.map(n => `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.t)}</a><small>${esc(n.src)} · ${esc(n.ago)}</small></li>`).join("")}</ul>` : ""}</div>`;
    let html = `<h2>今天要知道的<small>${md(T.asof)} 收盘${T.items.some(x => x.live) ? " · 含盘中" : ""}，越少见越靠前</small></h2>`;
    html += T.items.length ? T.items.map(card).join("") : `<div class="quiet">今天没有值得看的变化。</div>`;
    if ((T.upcoming || []).length) html += `<ul class="up"><b>接下来两个交易日</b>${T.upcoming.map(e => `<li>${md(e.date)}（${wk(e.date)}）${esc(e.time || "")} · ${esc(e.kind === "earnings" ? (e.name || e.sym) + " 财报" : e.title)}${e.note && e.kind === "macro" ? "" : ""}</li>`).join("")}</ul>`;
    if ((T.recent || []).length) html += `<details><summary>前几天说过的（${T.recent.length} 条）</summary>${T.recent.map(card).join("")}</details>`;
    if ((T.trends || []).length) {
      const c = (w, n, u) => w ? `<td class="${w === "上行" ? "s-up" : w === "下行" ? "s-dn" : ""}">${w} ${n} ${u}</td>` : "<td>—</td>";
      html += `<details><summary>所有品种的趋势状态（日 / 周 / 月）</summary><p>上行 = 收盘在均线上方、均线在升；下行反过来；其他是震荡。日线 20 日均线，周线 10 周，月线 10 个月；数字是这个状态持续了多久。</p><table class="tbl tr"><tr><th>品种</th><th>日线</th><th>周线</th><th>月线</th></tr>${T.trends.map(r => `<tr><td>${esc(r.name)}</td>${c(r.d, r.dn, "天")}${c(r.w, r.wn, "周")}${c(r.m, r.mn, "个月")}</tr>`).join("")}</table></details>`;
    }
    el.innerHTML = html;
  })();

  // ---------- 期权：五个问题（规则在 口径.md 第四节；白话在 qx/options.py 写好）
  (function opt() {
    const O = RAW.options, el = $("opt"); if (!O || !el || !(O.rows || []).length) return;
    const Q = [["保险贵不贵", "q1"], ["更怕跌还是更想涨", "q2"], ["大家押在哪个价位", "q3"], ["做市商对冲会放大还是压住波动", "q4"], ["定价了多大的涨跌", "q5"]];
    el.innerHTML = `<summary>期权：五个问题<small>${esc(O.summary || "")}</small></summary>
      <p>大盘：${esc(O.market)}</p>
      <div class="oq">${O.rows.map(r => `<div class="oc"><h4>${esc(r.name)}<small>${r.live ? "盘中 · 延迟 15 分钟" : md(r.date || RAW.asof) + " 收盘"}</small></h4>${r.ans.map(a => `<div class="oa${a.warn ? " w" : ""}"><b>${esc(a.q)}</b>：${esc(a.a)}</div>`).join("")}</div>`).join("")}</div>
      <details><summary>这五个问题是什么意思</summary><dl class="ox">${Q.map(([q, k]) => `<dt>${q}</dt><dd>${esc(O.explain[k])}</dd>`).join("")}</dl></details>
      <p class="knote">期权链是 CBOE 延迟 15 分钟的报价，从 2026-10-19 起每天攒，现在 ${O.days} 天；攒满 250 个交易日以后才和历史比"少见不少见"。K 线上 SMH、英伟达、美光、台积电标了做市商 gamma 转负 / 转正的日子。</p>`;
  })();

  // ---------- 预测市场（第 5 块）、新闻和日历（第 6 块）；规则在 口径.md 第五节
  (function happen() {
    const H = RAW.happen; if (!H) return;
    const pct = x => x == null ? "—" : Math.round(x * 100) + "%", chg = x => x == null ? "" : (x >= 0 ? "+" : "−") + Math.abs(Math.round(x * 100));
    const wk = d => "周" + "日一二三四五六"[new Date(d + "T12:00:00").getDay()];
    const pm = $("pm");
    if (pm && (H.pm.topics || []).length) {
      pm.innerHTML = `<summary>预测市场<small>Polymarket，按话题、成交大的；概率后面是 1 天 / 1 周的变化（百分点）</small></summary>` +
        H.pm.topics.map(t => `<div class="pmt"><h4>${esc(t.name)}</h4>${t.events.map(e => `<div class="pme"><a href="https://polymarket.com/event/${esc(e.slug || "")}" target="_blank" rel="noopener">${esc(e.title)}</a>${e.end ? `<small>　到 ${esc(e.end)}</small>` : ""}<div class="m">${e.markets.map(m => `${esc(m.label || "是")} <b>${pct(m.p)}</b>（${chg(m.d1)} / ${chg(m.d7)}）`).join("　")}</div></div>`).join("")}</div>`).join("") +
        `<p class="knote">概率是下注的人用钱投出来的，不是真实概率。1 天里变了 15 个百分点以上、成交又大的，会进"今天要知道的"。</p>`;
    }
    const nw = $("news"); if (!nw) return;
    const N = H.news || {}, C = H.calendar || [];
    const li = n => `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.t)}</a><small>${esc(n.topic ? n.topic + " · " : "")}${esc(n.src)} · ${esc(n.ago)}${n.k > 1 ? ` · ${n.k} 家报道` : ""}</small></li>`;
    const what = e => e.kind === "earnings" ? `${esc(e.name || e.sym)} 财报` : esc(e.title);
    const extra = e => { const a = [];
      if (e.pm) a.push(`Polymarket：不变 ${pct(e.pm.hold)} · 降息 ${pct(e.pm.cut)} · 加息 ${pct(e.pm.hike)}${e.pm.stale ? "（上次的）" : ""}`);
      if ((e.implied || []).length) a.push("期权定价：" + e.implied.map(x => `${x.sym} ±${(x.move * 100).toFixed(1)}%（到 ${x.exp}）`).join("、"));
      if (e.kind === "macro" && e.note) a.push(esc(e.note));
      return a.length ? `<small>${a.join("；")}</small>` : ""; };
    const short = n => String(n || "").replace(/,? (Inc\.?|Corp(oration)?\.?|Holdings?.*|N\.V\.|plc|PLC|Ltd\.?|Limited|Company.*|Technology.*|Incorporated|Co\.?)$/,"").replace(/,$/, "");
    function calRows(C) {           // 同一天的财报合成一行；其他事件一件一行
      const days = [...new Set(C.map(e => e.date))], out = [];
      for (const d of days) {
        const ev = C.filter(e => e.date === d), er = ev.filter(e => e.kind === "earnings");
        for (const e of ev.filter(e => e.kind !== "earnings")) out.push(`<tr><td class="d">${md(d)} ${wk(d)}<small>${esc(e.time || "")}</small></td><td>${what(e)}${extra(e)}</td></tr>`);
        if (er.length) out.push(`<tr><td class="d">${md(d)} ${wk(d)}</td><td>财报：${er.map(e => `${esc(short(e.name || e.sym))}<span style="color:var(--ink-3)">（${esc(e.time)}${(e.implied || []).length ? "，期权定价 ±" + (e.implied[0].move * 100).toFixed(1) + "%" : ""}）</span>`).join("、")}</td></tr>`);
      }
      return out.join("");
    }
    nw.innerHTML = `<h2>新闻和日历</h2>` +
      (N.top && N.top.length ? `<ul class="nw">${N.top.map(li).join("")}</ul>` : `<p class="quiet">最近 24 小时没有和美股有关的要闻。</p>`) +
      (C.length ? `<h3 style="font-size:15px;margin:16px 0 4px">接下来 7 天</h3><table class="tbl cal">${calRows(C)}</table>` : "") +
      ((N.more || []).length ? `<details><summary>更多新闻（按话题）</summary>${N.more.map(g => `<p style="margin:10px 0 2px"><b>${esc(g.topic)}</b></p><ul class="nw">${g.items.map(li).join("")}</ul>`).join("")}</details>` : "") +
      `<p class="knote">新闻只从路透、彭博、华尔街日报、金融时报、CNBC、日经亚洲、美联储、韩联社、CoinDesk 和华尔街见闻"重要"快讯里取。期权定价包含到期前的正常波动，偏大一点。</p>`;
  })();

  // ---------- 最近一年：阶段一条 + 四行热度（和 K 线副图同一套颜色）
  function drawYear() {
    const cv = $("yr"); if (!cv || !cv.getContext) return;
    const W = Math.max(260, cv.parentElement.clientWidth - 28), H = 132, dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px";
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const n = Math.min(252, D.d.length), k0 = D.d.length - n, L = 40, R = W - 4, bw = (R - L) / n, fb = tok("--f-body") || "sans-serif";
    const dark = (() => { const c = hexToRgb(tok("--bg")); return (c[0] * 299 + c[1] * 587 + c[2] * 114) / 1000 < 128; })();
    const HR = hexToRgb(tok("--heat")).join(","), rows = [["state", "阶段"]].concat(LN.map(x => [x[0], x[1]]));
    const top = 2, rh = (H - top - 18) / rows.length;
    g.font = "700 11px " + fb; g.textBaseline = "middle"; g.textAlign = "left";
    rows.forEach(([key, nm], r) => {
      const y0 = top + r * rh;
      g.fillStyle = dark ? "rgba(255,255,255,.03)" : "rgba(0,0,0,.03)"; g.fillRect(L, y0 + 1, R - L, rh - 2);
      for (let j = 0; j < n; j++) { const v = D[key][k0 + j]; if (v == null) continue;
        if (key === "state") { if (!v) continue; g.fillStyle = SFILL(v); }
        else g.fillStyle = `rgba(${HR},${v >= 90 ? 0.95 : v >= 70 ? 0.5 : v >= 50 ? 0.2 : 0.06})`;
        g.fillRect(L + j * bw, y0 + 1, bw + 0.6, rh - 2); }
      g.fillStyle = tok("--ink"); g.fillText(nm, 2, y0 + rh / 2 + 0.5);
    });
    g.fillStyle = tok("--ink-3"); g.font = "11px " + fb; g.textAlign = "center"; g.textBaseline = "alphabetic";
    let lastM = null, lastX = -99;
    for (let j = 0; j < n; j++) { const d = D.d[k0 + j], m = d.slice(0, 7); if (lastM && m !== lastM) { const x = L + j * bw; if (x - lastX > 34 && x < R - 12) { g.fillText(d.slice(5, 7) === "01" ? d.slice(0, 4) : (+d.slice(5, 7)) + "月", x, H - 3); lastX = x; } } lastM = m; }
  }
  drawYear();
  addEventListener("resize", () => drawYear());
  try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => drawYear()); } catch (e) {}

  // ---------- K 线（照「科技情绪全景」）
  const KL = (function () {
    const LS = "qx-kline-v1", LSD = "qx-draw-v1";
    const ld = (k, dflt) => { try { const v = JSON.parse(localStorage.getItem(k) || "null"); return v == null ? dflt : v; } catch (e) { return dflt; } };
    const sv = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
    const SYMS = (RAW.chart || []).filter(s => s.rows && s.rows.length > 30);
    const DEF_MA = [5, 10, 20, 50, 100, 200];
    const MA_COL = { 5: ["#c98a00", "#e8b23a"], 10: ["#c2457a", "#ed93b1"], 20: ["#6250d6", "#a49cf0"], 50: ["#2a78d6", "#5b9be6"], 100: ["#178f66", "#3cc794"], 200: ["#d9561f", "#f08a5d"] };
    const XCOL = [["#7a6f5c", "#b5a98f"], ["#4d7c8a", "#86b6c4"], ["#8a5a44", "#c9967e"], ["#5c6b2e", "#a3b56a"]];
    const SUBS = [["heat", "恐慌热度（四行色块）"], ["fomc", "下次议息会降息概率"], ["sell", "抛售恐慌"], ["price", "定价恐慌"], ["pos", "仓位恐慌"], ["credit", "信用压力"], ["rsi", "RSI"], ["vix", "VIX"], ["t3", "VIX 期限结构"], ["breadth", "成分股广度"], ["none", "不显示"]];
    const cfg = Object.assign({ sym: SYMS[0].k, n: 252, mas: DEF_MA.slice(), on: { 5: 0, 10: 0, 20: 1, 50: 1, 100: 0, 200: 1 }, sub: "heat", mk: true, smk: true, bg: true, sw: true, redUp: false }, ld(LS, {}));
    if (!SYMS.some(s => s.k === cfg.sym)) cfg.sym = SYMS[0].k;
    if (ld(LS, null) == null && window.innerWidth < 560) cfg.n = 126;      // 手机第一次打开默认 6 个月
    if (!SUBS.some(s => s[0] === cfg.sub)) cfg.sub = "heat";
    cfg.mas = [...new Set((cfg.mas || []).map(Number).filter(p => p >= 2 && p <= 400))].sort((a, b) => a - b);
    if (!cfg.mas.length) cfg.mas = DEF_MA.slice();
    const saveCfg = () => sv(LS, cfg);
    const allDraws = ld(LSD, {}) || {};
    const draws = () => (allDraws[cfg.sym] = allDraws[cfg.sym] || []);
    const saveDraws = () => sv(LSD, allDraws);
    let DARK = false;
    const isDark = () => { const c = hexToRgb(tok("--bg")); return (c[0] * 299 + c[1] * 587 + c[2] * 114) / 1000 < 128; };
    const maCol = p => { const c = MA_COL[p] || XCOL[Math.max(0, cfg.mas.indexOf(p)) % XCOL.length]; return c[DARK ? 1 : 0]; };
    const setUpDown = () => { try { document.documentElement.setAttribute("data-updown", cfg.redUp ? "red" : "green"); } catch (e) {} };
    setUpDown();
    const sma = (a, p) => { const r = new Float64Array(a.length).fill(NaN); let s = 0; for (let i = 0; i < a.length; i++) { s += a[i]; if (i >= p) s -= a[i - p]; if (i >= p - 1) r[i] = s / p; } return r; };
    // 别的品种（KOSPI 等）交易日和美股不一样：取那天或之前最近一个美股交易日的市场读数（最多往前 5 天）
    const dayIdx = d => { if (DMAP.has(d)) return DMAP.get(d); let lo = 0, hi = D.d.length - 1, k = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (D.d[m] <= d) { k = m; lo = m + 1; } else hi = m - 1; } return k >= 0 && (Date.parse(d) - Date.parse(D.d[k])) / 864e5 <= 5 ? k : null; };
    let B = [], DI = new Map(), MA = {}, XMA = {}, V50 = [], ohlc = false, hasVol = false, cur = null, CLX = new Set(), HOT = new Set(), PIV = [];
    function build() {
      cur = SYMS.find(s => s.k === cfg.sym) || SYMS[0];
      B = cur.rows.map((r, i) => { const [d, o, h, l, c, v] = r, real = o != null && h != null && l != null;
        return { d, c, o: real ? o : c, h: real ? Math.max(h, o, c) : c, l: real ? Math.min(l, o, c) : c, v: v || 0, real, rsi: cur.rsi ? cur.rsi[i] : null, di: dayIdx(d) }; });
      ohlc = B.filter(b => b.real).length > B.length / 2; hasVol = B.some(b => b.v > 0);
      DI = new Map(B.map((b, i) => [b.d, i]));
      const cs = B.map(b => b.c); MA = {}; for (const p of cfg.mas) MA[p] = sma(cs, p);
      XMA = {}; for (const p of [5, 20, 50, 200]) XMA[p] = MA[p] || sma(cs, p);
      V50 = sma(B.map(b => b.v), 50);
      CLX = new Set(cur.climax || []); HOT = new Set(cur.hot || []);
      PIV = (cur.pivots || []).map(([d, t, p]) => ({ i: DI.get(d), t, p })).filter(x => x.i != null);
    }
    // 标签：进入某一段的第一天（同一段相邻 10 天只算一次），加这个品种自己的抛售日、涨过头日
    const MK = new Map();
    function buildMarkers() {
      MK.clear();
      const add = (d, m) => { if (!d) return; const a = MK.get(d) || []; a.push(m); MK.set(d, a); };
      const barDate = d => { if (DI.has(d)) return d; let lo = 0, hi = B.length - 1, k = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (B[m].d >= d) { k = m; hi = m - 1; } else lo = m + 1; } return k >= 0 && (Date.parse(B[k].d) - Date.parse(d)) / 864e5 <= 5 ? B[k].d : null; };
      if (cfg.mk) for (const s of [1, 2, 3]) { let last = -99; for (let k = 1; k < D.d.length; k++) { const on = D.state[k] === s, ent = on && D.state[k - 1] !== s; if (ent && k - last > 10) add(barDate(D.d[k]), { t: NAMES[s], side: s === 4 ? "risk" : "turn", st: s }); if (on) last = k; } }
      if (cfg.smk) {
        let last = -99; B.forEach((b, i) => { if (CLX.has(b.d)) { if (i - last > 10) add(b.d, { t: "抛售", side: "turn", col: "alert", ol: 1 }); last = i; } });
        last = -99; B.forEach((b, i) => { if (HOT.has(b.d)) { if (i - last > 10) add(b.d, { t: "涨过头", side: "risk", col: "greed", ol: 1 }); last = i; } });
      }
      // 转折标签（口径.md 二.2；整个半导体市场的，和阶段一样按同一天对照）
      const TK = { peak: [{ t: "恐慌高峰", side: "turn", col: "fear" }], ebb: [{ t: "恐慌退潮", side: "risk", st: 4 }], retest: [{ t: "二次探底", side: "turn", col: "violet", ol: 1 }], lead: [{ t: "参与度先走", side: "risk", col: "watch", ol: 1 }] };
      if (cfg.mk) for (const [d, k] of RAW.turns || []) for (const m of TK[k] || []) add(barDate(d), Object.assign({}, m));
      if (cfg.smk) for (const [d, w] of cur.opt || []) add(barDate(d), { t: "gamma " + w, side: w === "转负" ? "turn" : "risk", col: w === "转负" ? "alert" : "ok", ol: 1 });
    }
    const view = { n: 252, end: 0 };
    const G = { W: 300, H: 400, L: 2, R: 240, pH: 280, vTop: 290, vH: 60, sTop: 360, sH: 100, barW: 1, first: 0, i0: 0, i1: 0, lo: 0, hi: 1, sub: null };
    let hover = null, sel = null, pend = null, tool = "pick", clearArm = 0, gest = null, previewI = null;
    function clampView() { const N = B.length; view.n = Math.max(15, Math.min(N + 10, view.n)); view.end = Math.max(Math.min(N - 1, view.n * 0.5), Math.min(N - 1 + Math.max(3, view.n * 0.2), view.end)); }
    function setRange(n) { view.n = n > 0 ? n : B.length + 4; view.end = B.length - 1 + Math.max(2, Math.round(view.n * 0.03)); clampView(); }
    const xOf = i => G.L + (i - G.first + 0.5) * G.barW;
    const idxAt = x => Math.round((x - G.L) / G.barW - 0.5 + G.first);
    const STRIP = () => cfg.bg ? 16 : 0;
    const yP = p => 8 + (G.hi - p) / (G.hi - G.lo) * (G.pH - 16 - STRIP());
    const pAt = y => G.hi - (y - 8) / (G.pH - 16 - STRIP()) * (G.hi - G.lo);
    const yS = v => G.sTop + 4 + (G.sub.hi - v) / (G.sub.hi - G.sub.lo) * (G.sH - 8);
    const sAt = y => G.sub.hi - (y - G.sTop - 4) / (G.sH - 8) * (G.sub.hi - G.sub.lo);
    const fmtP = v => v == null || !isFinite(v) ? "—" : fmt(v, Math.abs(v) >= 1000 ? 0 : 2);
    const fmtV = v => !v ? "—" : v >= 1e8 ? fmt(v / 1e8, 2) + " 亿" : v >= 1e4 ? fmt(v / 1e4, 0) + " 万" : fmt(v, 0);
    const clampI = i => Math.max(0, Math.min(B.length - 1, i));
    function zoomAt(x, n) { const fAt = G.first + (x - G.L) / G.barW - 0.5, nn = Math.max(15, Math.min(B.length + 10, n)), bw = (G.R - G.L) / nn; view.n = nn; view.end = fAt - (x - G.L) / bw + 0.5 + nn - 1; clampView(); schedule(); }
    let raf = 0;
    const schedule = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };
    function nice(lo, hi, k) { const span = hi - lo || 1, raw = span / k, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag; const st = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag, out = []; for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) out.push(+v.toFixed(10)); return { out, st }; }
    const dv = (i, key) => { const k = B[i] && B[i].di; return k == null || !D[key] ? null : D[key][k]; };
    const HEATROWS = [["sell", "抛售"], ["price", "定价"], ["pos", "仓位"], ["credit", "信用"]];
    function subDef(T) {
      const s = cfg.sub;
      if (s === "none") return null;
      if (s === "heat") return { lo: 0, hi: 4, lines: [], heat: true, lab: "恐慌热度（越深越恐慌）", dp: 0 };
      const one = { sell: ["抛售恐慌（成分股创新低的多少）", "sell"], price: ["定价恐慌（科技股保险比平时贵多少）", "price"], pos: ["仓位恐慌（抢买认沽、散户转空）", "pos"], credit: ["信用压力（信用 ETF 跑输国债）", "credit"] }[s];
      if (one) return { lo: 0, hi: 100, lines: [50, 70, 90], labs: { 50: "中位", 70: "偏高", 90: "少见" }, ser: [{ f: i => dv(i, one[1]), col: T.heat, w: 1.6 }], area: one[1], lab: one[0], dp: 0, fill: [[90, 100, T.heat]] };
      if (s === "fomc") return { lo: 0, hi: 100, lines: [25, 50, 75], ser: [{ f: i => { const x = FOMC[B[i].d]; return x ? x[2] * 100 : null; }, col: T.accent, w: 1.6 }, { f: i => { const x = FOMC[B[i].d]; return x ? x[3] * 100 : null; }, col: T.alert, w: 1.2 }], lab: "下次议息会：降息（蓝）/ 加息（红）的概率 %（Polymarket，从 2026-10 开始攒）", dp: 0 };
      if (s === "rsi") return { lo: 0, hi: 100, lines: [30, 50, 70], ser: [{ f: i => B[i].rsi, col: T.ink, w: 1.4 }], lab: "RSI(14)", dp: 0, fill: [[70, 100, T.greed], [0, 30, T.fear]] };
      if (s === "vix") { let lo = Infinity, hi = -Infinity; for (let i = G.i0; i <= G.i1; i++) { const v = dv(i, "vix"); if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
        if (!isFinite(lo)) return { lo: 0, hi: 1, lines: [], ser: [], lab: "VIX（这段时间没有数据）", dp: 1 };
        lo = Math.min(lo, 15) - 1; hi = Math.max(hi, 22) + 2;
        return { lo, hi, lines: [20, 30, 40].filter(v => v > lo && v < hi), ser: [{ f: i => dv(i, "vix"), col: T.fear, w: 1.5 }], lab: "VIX · 20 正常 / 30 恐慌 / 40 极度恐慌", dp: 1 }; }
      if (s === "t3") { let lo = Infinity, hi = -Infinity; for (let i = G.i0; i <= G.i1; i++) { const v = dv(i, "t3"); if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
        if (!isFinite(lo)) return { lo: 0, hi: 1, lines: [], ser: [], lab: "VIX ÷ VIX3M", dp: 2 };
        lo = Math.min(lo, 0.8) - 0.02; hi = Math.max(hi, 1.02) + 0.02;
        return { lo, hi, lines: [0.85, 0.95, 1], ser: [{ f: i => dv(i, "t3"), col: T.fear, w: 1.5 }], lab: "VIX ÷ VIX3M · ≥ 1 近的比远的贵（倒挂）", dp: 2, fill: [[1, hi, T.fear]] }; }
      if (s === "breadth") return { lo: 0, hi: 100, lines: [20, 50, 80], ser: [{ f: i => dv(i, "pct50"), col: T.accent, w: 1.5 }, { f: i => dv(i, "pct200"), col: T.ink3, w: 1.2 }], lab: "成分股在 50 日线（蓝）/ 200 日线（灰）上方的比例 %", dp: 0 };
      return null;
    }
    function draw() {
      const cv = $("kc"); if (!cv || !cv.getContext || !B.length) return;
      const W = Math.max(300, cv.parentElement.clientWidth || 700), H = W < 560 ? 500 : 560, dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px"; }
      const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
      DARK = isDark();
      const T = { ink: tok("--ink"), ink2: tok("--ink-2"), ink3: tok("--ink-3"), line: tok("--line"), grid: tok("--grid"), fear: tok("--fear"), greed: tok("--greed"), ok: tok("--ok"), alert: tok("--alert"), accent: tok("--accent"), panel: tok("--panel"), heat: tok("--heat"), watch: tok("--watch"), violet: tok("--violet") };
      const up = cfg.redUp ? tok("--down") : tok("--up"), dn = cfg.redUp ? tok("--up") : tok("--down");
      const fd = tok("--f-data") || "monospace", fb = tok("--f-body") || "sans-serif";
      const AXR = W < 560 ? 54 : 64, AXB = 22, plotH = H - AXB;
      G.W = W; G.H = H; G.L = 2; G.R = W - AXR;
      G.barW = (G.R - G.L) / view.n; G.first = view.end - view.n + 1;
      G.i0 = Math.max(0, Math.floor(G.first)); G.i1 = Math.min(B.length - 1, Math.ceil(view.end));
      const sub = subDef(T); G.sub = sub;
      const vFrac = hasVol ? 0.13 : 0, sFrac = sub ? (sub.heat ? 0.17 : 0.22) : 0;
      G.pH = Math.round(plotH * (1 - vFrac - sFrac)) - (hasVol ? 6 : 0) - (sub ? 6 : 0);
      G.vTop = G.pH + 8; G.vH = hasVol ? Math.round(plotH * vFrac) : 0;
      G.sTop = G.vTop + G.vH + (hasVol ? 8 : 0); G.sH = sub ? plotH - G.sTop : 0;
      let lo = Infinity, hi = -Infinity;
      for (let i = G.i0; i <= G.i1; i++) { const b = B[i]; lo = Math.min(lo, b.l); hi = Math.max(hi, b.h);
        for (const p of cfg.mas) if (cfg.on[p]) { const m = MA[p][i]; if (isFinite(m)) { lo = Math.min(lo, m); hi = Math.max(hi, m); } } }
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.02 || 1; G.lo = lo - pad; G.hi = hi + pad;
      const bw = G.barW;
      g.save(); g.beginPath(); g.rect(G.L, 0, G.R - G.L, plotH); g.clip();
      // 投降的日子，价格区铺一层浅红
      if (cfg.bg) { const S3 = hexToRgb(tok("--s3")).join(","); for (let i = G.i0; i <= G.i1; i++) if (dv(i, "state") === 3) { g.fillStyle = `rgba(${S3},${DARK ? 0.22 : 0.28})`; g.fillRect(xOf(i) - bw / 2, 0, bw + 0.6, G.pH - STRIP()); } }
      // 阶段色带：价格区最下面一条，同一段连成一块，够宽就写名字
      if (cfg.bg) {
        const sy = G.pH - STRIP() + 1, sh = STRIP() - 3;
        g.fillStyle = DARK ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)"; g.fillRect(G.L, sy, G.R - G.L, sh);
        g.font = "700 11px " + fb; g.textAlign = "center"; g.textBaseline = "middle";
        for (let i = G.i0; i <= G.i1; i++) {
          const s = dv(i, "state"); let j = i; while (j < G.i1 && dv(j + 1, "state") === s) j++;
          const x0 = xOf(i) - bw / 2, x1 = xOf(j) + bw / 2;
          if (s) { g.fillStyle = SFILL(s); g.fillRect(x0, sy, x1 - x0 + 0.6, sh); const nm = NAMES[s]; if (x1 - x0 >= g.measureText(nm).width + 14) { g.fillStyle = SINK(s); g.fillText(nm, (x0 + x1) / 2, sy + sh / 2 + 0.5); } }
          i = j;
        }
        g.textBaseline = "alphabetic";
      }
      if (sel && sel.type === "day") { g.fillStyle = DARK ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.06)"; g.fillRect(xOf(sel.i) - Math.max(bw, 3) / 2, 0, Math.max(bw, 3), plotH); }
      const pt = nice(G.lo, G.hi, Math.max(3, Math.round(G.pH / 70)));
      g.strokeStyle = T.grid; g.lineWidth = 1;
      for (const v of pt.out) { const y = Math.round(yP(v)) + 0.5; g.beginPath(); g.moveTo(G.L, y); g.lineTo(G.R, y); g.stroke(); }
      if (!ohlc || bw < 2) {
        g.strokeStyle = T.ink2; g.lineWidth = 1.4; g.lineJoin = "round"; g.beginPath();
        for (let i = G.i0; i <= G.i1; i++) { const x = xOf(i), y = yP(B[i].c); i === G.i0 ? g.moveTo(x, y) : g.lineTo(x, y); }
        g.stroke();
      } else {
        const body = Math.max(1, Math.min(14, Math.floor(bw * 0.68)));
        for (let i = G.i0; i <= G.i1; i++) {
          const b = B[i], x = Math.round(xOf(i)) + 0.5, col = b.c >= b.o ? up : dn;
          g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
          g.beginPath(); g.moveTo(x, yP(b.h)); g.lineTo(x, yP(b.l)); g.stroke();
          if (bw >= 3) { const yo = yP(b.o), yc = yP(b.c); g.fillRect(Math.round(x - body / 2), Math.min(yo, yc), body, Math.max(1, Math.abs(yc - yo))); }
        }
      }
      g.lineJoin = "round";
      for (const p of cfg.mas) { if (!cfg.on[p]) continue; const a = MA[p]; g.strokeStyle = maCol(p); g.lineWidth = 1.3; g.beginPath(); let on = false;
        for (let i = G.i0; i <= G.i1; i++) { const m = a[i]; if (!isFinite(m)) { on = false; continue; } const x = xOf(i), y = yP(m); on ? g.lineTo(x, y) : g.moveTo(x, y); on = true; }
        g.stroke(); }
      g.save(); g.beginPath(); g.rect(G.L, 0, G.R - G.L, G.pH); g.clip();
      if (cfg.sw && PIV.length) {
        g.strokeStyle = T.ink3; g.lineWidth = 1.2;
        for (const pv of PIV) { if (pv.i < G.i0 - 1 || pv.i > G.i1 + 1) continue; const y = yP(pv.p) + (pv.t === "H" ? -6 : 6); g.beginPath(); g.arc(xOf(pv.i), y, 2.4, 0, 7); g.stroke(); }
        for (const t of ["H", "L"]) { const ps = PIV.filter(x => x.t === t).slice(-2); if (ps.length < 2) continue;
          const [a, b] = ps, x1 = xOf(a.i), x2 = xOf(b.i), y1 = yP(a.p), y2 = yP(b.p), sl = (y2 - y1) / ((x2 - x1) || 1);
          g.strokeStyle = t === "H" ? T.greed : T.fear; g.globalAlpha = .75; g.lineWidth = 1.2; g.setLineDash([6, 4]);
          g.beginPath(); g.moveTo(x1, y1); g.lineTo(G.R, y1 + sl * (G.R - x1)); g.stroke(); g.setLineDash([]); g.globalAlpha = 1; }
      }
      for (const dw of draws()) {
        const on = sel && sel.type === "draw" && sel.id === dw.id;
        g.strokeStyle = T.accent; g.fillStyle = T.accent; g.lineWidth = on ? 2.4 : 1.5;
        if (dw.type === "h") { const y = Math.round(yP(dw.p)) + 0.5; if (y < 0 || y > G.pH) continue; g.setLineDash([7, 4]); g.beginPath(); g.moveTo(G.L, y); g.lineTo(G.R, y); g.stroke(); g.setLineDash([]); }
        else { const a = DI.get(dw.d1), b = DI.get(dw.d2); if (a == null || b == null) continue;
          const x1 = xOf(a), y1 = yP(dw.p1), x2 = xOf(b), y2 = yP(dw.p2), sl = (y2 - y1) / ((x2 - x1) || 1);
          g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
          g.setLineDash([4, 4]); g.lineWidth = 1; g.beginPath(); g.moveTo(x2, y2); g.lineTo(G.R, y2 + sl * (G.R - x2)); g.stroke(); g.setLineDash([]);
          for (const [x, y] of [[x1, y1], [x2, y2]]) { g.beginPath(); g.arc(x, y, on ? 4 : 3, 0, 7); g.fill(); } }
      }
      g.restore();
      if (pend) { g.fillStyle = T.accent; g.beginPath(); g.arc(xOf(pend.i), yP(pend.p), 4, 0, 7); g.fill();
        if (hover && hover.y <= G.pH) { g.strokeStyle = T.accent; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(xOf(pend.i), yP(pend.p)); g.lineTo(hover.x, hover.y); g.stroke(); g.setLineDash([]); } }
      // 标签：阶段在 K 线下方（出清在上方），抛售在下方，涨过头在上方；放不下时退成小圆点
      g.font = "700 11px " + fb; g.textBaseline = "middle"; g.textAlign = "center";
      const placed = [], top = 4, bot = G.pH - STRIP() - 4;
      const hit = (x0, y0, x1, y1) => placed.some(r => x0 < r[2] && x1 > r[0] && y0 < r[3] && y1 > r[1]);
      for (let i = G.i0; i <= G.i1; i++) {
        const ms = MK.get(B[i].d); if (!ms) continue; const b = B[i], x0 = xOf(i);
        let ya = yP(b.h) - 8, yb = yP(b.l) + 8;
        for (const m of ms) {
          const risk = m.side === "risk", col = m.st ? SINK(m.st) : (T[m.col] || T.ink2), fill = m.st ? SFILL(m.st) : null, tw = g.measureText(m.t).width + 12, h = 17;
          const x = Math.max(G.L + tw / 2 + 1, Math.min(G.R - tw / 2 - 1, x0));
          let y = null;
          for (let k = 0; k < 4; k++) { const yy = risk ? ya - h - k * (h + 3) : yb + k * (h + 3); if (yy < top || yy + h > bot) break; if (!hit(x - tw / 2, yy, x + tw / 2, yy + h)) { y = yy; break; } }
          g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
          if (y == null) { const yy = risk ? ya - 4 : yb + 4; g.beginPath(); g.arc(x0, yy, 3.2, 0, 7); g.fill(); continue; }
          placed.push([x - tw / 2, y, x + tw / 2, y + h]);
          g.beginPath(); g.moveTo(x, risk ? y + h : y); g.lineTo(x0, risk ? yP(b.h) - 2 : yP(b.l) + 2); g.stroke();
          const rx = x - tw / 2, rr = 8.5;
          g.beginPath(); g.moveTo(rx + rr, y); g.arcTo(rx + tw, y, rx + tw, y + h, rr); g.arcTo(rx + tw, y + h, rx, y + h, rr); g.arcTo(rx, y + h, rx, y, rr); g.arcTo(rx, y, rx + tw, y, rr); g.closePath();
          if (fill) { g.fillStyle = fill; g.fill(); g.lineWidth = 1.2; g.stroke(); g.fillStyle = col; }
          else if (m.ol) { g.fillStyle = T.panel; g.fill(); g.lineWidth = 1.4; g.stroke(); g.fillStyle = col; }
          else { g.fill(); g.fillStyle = "#fff"; }
          g.fillText(m.t, x, y + h / 2 + 0.5);
          if (risk) ya = y - 3; else yb = y + h + 3;
        }
      }
      g.textBaseline = "alphabetic";
      // 成交量
      if (hasVol) {
        let vmax = 0; for (let i = G.i0; i <= G.i1; i++) vmax = Math.max(vmax, B[i].v); vmax = vmax || 1;
        const yV = v => G.vTop + G.vH - v / vmax * (G.vH - 4), vb = Math.max(1, Math.min(12, bw * 0.72));
        for (let i = G.i0; i <= G.i1; i++) { const b = B[i]; if (!b.v) continue; const climax = isFinite(V50[i]) && b.v >= 2 * V50[i];
          g.globalAlpha = climax ? 1 : 0.42; g.fillStyle = b.c >= (i ? B[i - 1].c : b.o) ? up : dn; g.fillRect(xOf(i) - vb / 2, yV(b.v), vb, G.vTop + G.vH - yV(b.v)); }
        g.globalAlpha = 1; g.strokeStyle = T.ink2; g.lineWidth = 1.1; g.beginPath(); let on = false;
        for (let i = G.i0; i <= G.i1; i++) { const m = V50[i]; if (!isFinite(m)) { on = false; continue; } const x = xOf(i), y = yV(m); on ? g.lineTo(x, y) : g.moveTo(x, y); on = true; }
        g.stroke();
      }
      // 副图
      if (sub && sub.heat) {
        const rh = (G.sH - 24) / HEATROWS.length, HR = hexToRgb(T.heat).join(",");
        HEATROWS.forEach(([key, nm], r) => {
          const y0 = G.sTop + 20 + r * rh;
          g.fillStyle = DARK ? "rgba(255,255,255,.03)" : "rgba(0,0,0,.025)"; g.fillRect(G.L, y0 + 1, G.R - G.L, rh - 2);
          for (let i = G.i0; i <= G.i1; i++) { const v = dv(i, key); if (v == null) continue;
            const a = v >= 90 ? 0.95 : v >= 70 ? 0.5 : v >= 50 ? 0.2 : 0.06;
            g.fillStyle = `rgba(${HR},${a})`; g.fillRect(xOf(i) - bw / 2, y0 + 1, bw + 0.6, rh - 2); }
          g.font = "700 11px " + fb; g.textAlign = "left"; g.textBaseline = "middle";
          const tw = g.measureText(nm).width + 8; g.fillStyle = DARK ? "rgba(27,31,34,.85)" : "rgba(255,255,255,.85)"; g.fillRect(G.L + 2, y0 + rh / 2 - 8, tw, 16);
          g.fillStyle = T.ink; g.fillText(nm, G.L + 6, y0 + rh / 2 + 0.5); g.textBaseline = "alphabetic";
        });
      } else if (sub) {
        g.strokeStyle = T.grid; g.lineWidth = 1;
        if (sub.fill) for (const [a, b, col] of sub.fill) { const y1 = yS(Math.min(b, sub.hi)), y2 = yS(Math.max(a, sub.lo)); g.fillStyle = `rgba(${hexToRgb(col).join(",")},${DARK ? .12 : .08})`; g.fillRect(G.L, y1, G.R - G.L, y2 - y1); }
        g.setLineDash([3, 4]); for (const v of sub.lines) { const y = Math.round(yS(v)) + 0.5; g.beginPath(); g.moveTo(G.L, y); g.lineTo(G.R, y); g.stroke(); } g.setLineDash([]);
        if (sub.area) { const y0 = yS(0); g.fillStyle = `rgba(${hexToRgb(T.heat).join(",")},${DARK ? .28 : .2})`; let run = [];
          const flush = () => { if (run.length > 1) { g.beginPath(); g.moveTo(run[0][0], y0); for (const [x, y] of run) g.lineTo(x, y); g.lineTo(run[run.length - 1][0], y0); g.closePath(); g.fill(); } run = []; };
          for (let i = G.i0; i <= G.i1; i++) { const v = dv(i, sub.area); if (v == null) { flush(); continue; } run.push([xOf(i), yS(v)]); } flush(); }
        for (const s of sub.ser || []) { g.strokeStyle = s.col; g.lineWidth = s.w; g.beginPath(); let on = false;
          for (let i = G.i0; i <= G.i1; i++) { const v = s.f(i); if (v == null || !isFinite(v)) { on = false; continue; } const x = xOf(i), y = yS(v); on ? g.lineTo(x, y) : g.moveTo(x, y); on = true; }
          g.stroke(); }
      }
      const ci = hover ? clampI(Math.max(G.i0, Math.min(G.i1, idxAt(hover.x)))) : null;
      if (ci != null) { const x = Math.round(xOf(ci)) + 0.5; g.strokeStyle = T.ink3; g.lineWidth = 1; g.setLineDash([3, 3]);
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, plotH); g.stroke();
        if (hover.y >= 0 && hover.y <= plotH) { const y = Math.round(hover.y) + 0.5; g.beginPath(); g.moveTo(G.L, y); g.lineTo(G.R, y); g.stroke(); }
        g.setLineDash([]); }
      g.restore();
      g.strokeStyle = T.line; g.lineWidth = 1;
      if (hasVol) { g.beginPath(); g.moveTo(0, G.vTop - 3.5); g.lineTo(W, G.vTop - 3.5); g.stroke(); }
      if (sub) { g.beginPath(); g.moveTo(0, G.sTop - 3.5); g.lineTo(W, G.sTop - 3.5); g.stroke(); }
      g.beginPath(); g.moveTo(G.R + 0.5, 0); g.lineTo(G.R + 0.5, plotH); g.stroke();
      g.fillStyle = T.ink3; g.font = "11px " + fd; g.textAlign = "left";
      const dpT = pt.st >= 1 ? 0 : pt.st >= 0.1 ? 1 : 2;
      for (const v of pt.out) { const y = yP(v); if (y < 10 || y > G.pH - 6) continue; g.fillText(fmt(v, dpT), G.R + 6, y + 4); }
      if (sub && !sub.heat) for (const v of sub.lines) g.fillText(sub.labs ? sub.labs[v] : fmt(v, sub.dp), G.R + 6, yS(v) + 4);
      const axBox = (txt, y, col) => { g.fillStyle = col; g.fillRect(G.R + 1, y - 9, AXR - 1, 18); g.fillStyle = "#fff"; g.fillText(txt, G.R + 6, y + 4); };
      const lb = B[B.length - 1], ly = yP(lb.c);
      if (ly > 0 && ly < G.pH) axBox(fmtP(lb.c), ly, lb.c >= (B[B.length - 2] || lb).c ? up : dn);
      for (const dw of draws()) if (dw.type === "h") { const y = yP(dw.p); if (y > 0 && y < G.pH) axBox(fmtP(dw.p), y, T.accent); }
      g.fillStyle = T.ink3; g.font = "11px " + fb; g.textAlign = "center";
      const mode = view.n > 520 ? "y" : view.n > 80 ? "m" : "d", every = Math.max(1, Math.ceil(56 / bw));
      let lastKey = null, lastX = -99;
      for (let i = G.i0; i <= G.i1; i++) { const d = B[i].d; let key, txt;
        if (mode === "y") { key = d.slice(0, 4); txt = key; } else if (mode === "m") { key = d.slice(0, 7); txt = d.slice(5, 7) === "01" ? d.slice(0, 4) : (+d.slice(5, 7)) + "月"; } else { key = Math.floor(i / every); txt = (+d.slice(5, 7)) + "/" + (+d.slice(8)); }
        if (lastKey !== null && key !== lastKey) { const x = xOf(i); if (x - lastX >= 46 && x > G.L + 14 && x < G.R - 14) { g.fillText(txt, x, H - 6); lastX = x; } }
        lastKey = key; }
      if (ci != null) { g.font = "11px " + fd;
        if (hover.y <= G.pH) axBox(fmtP(pAt(hover.y)), hover.y, T.ink2);
        else if (sub && !sub.heat && !sub.labs && hover.y >= G.sTop && hover.y <= plotH) axBox(fmt(sAt(hover.y), sub.dp), hover.y, T.ink2);
        const x = xOf(ci), tw = 74; g.fillStyle = T.ink2; g.fillRect(Math.max(0, Math.min(G.R - tw, x - tw / 2)), plotH + 2, tw, 18);
        g.fillStyle = "#fff"; g.textAlign = "center"; g.fillText(B[ci].d, Math.max(tw / 2, Math.min(G.R - tw / 2, x)), plotH + 15); }
      legend(ci != null ? ci : sel && sel.type === "day" ? sel.i : B.length - 1);
      const pv = hover && hover.mouse && !gest && tool === "pick" ? ci : null;
      if (pv !== previewI) { previewI = pv; panel(); }
      const pn = $("kpan"); if (pn) { pn.min = 0; pn.max = Math.max(1, Math.round(B.length - 1 + Math.max(3, view.n * 0.2))); pn.value = Math.round(view.end); }
    }
    const stTag = i => { const s = dv(i, "state"); return s == null ? "" : `<b style="color:${SINK(s)}">${NAMES[s]}</b>`; };
    function legend(i) {
      const b = B[i]; if (!b) return;
      const pv = B[i - 1], ch = pv ? (b.c / pv.c - 1) * 100 : null, col = ch == null ? "var(--ink)" : ch >= 0 ? "var(--pos)" : "var(--neg)";
      $("klegend").innerHTML = `<div class="l1"><b>${esc(cur.n)}</b><span class="num">${b.d}</span>${stTag(i)}` +
        (b.real ? `<span>开 <i>${fmtP(b.o)}</i></span><span>高 <i>${fmtP(b.h)}</i></span><span>低 <i>${fmtP(b.l)}</i></span>` : "") +
        `<span>收 <i style="color:${col}">${fmtP(b.c)}</i></span><span><i style="color:${col}">${ch == null ? "" : sgn(ch, 2) + "%"}</i></span>${(MK.get(b.d) || []).filter(m => !m.st).map(m => `<b style="color:var(--${m.col})">${m.t}</b>`).join(" ")}</div>` +
        `<div class="l2">${cfg.mas.filter(p => cfg.on[p]).map(p => `<span style="color:${maCol(p)}">MA${p} <i>${fmtP(MA[p][i])}</i></span>`).join("")}</div>`;
      const kv = $("kvl"), ks = $("ksl");
      if (hasVol) { kv.hidden = false; kv.style.top = (G.vTop + 1) + "px"; const r = isFinite(V50[i]) && V50[i] > 0 ? b.v / V50[i] : null; kv.innerHTML = `${esc(cur.vnote || "成交量")} <b>${fmtV(b.v)}</b>${r == null ? "" : ` · 50 日均量的 <b>${fmt(r, 2)}</b> 倍`}`; } else kv.hidden = true;
      if (G.sub) { ks.hidden = false; ks.style.top = (G.sTop + 1) + "px"; let val = "";
        const mw = k => { const m = dv(i, "m" + k); return m == null ? "" : MW[m]; };
        if (cfg.sub === "heat") val = HEATROWS.map(([k, nm]) => `${nm}${LVS(dv(i, k))}`).join(G.W < 560 ? " " : " · ");
        else if (["sell", "price", "pos", "credit"].includes(cfg.sub)) val = `${LVS(dv(i, cfg.sub))}${mw(cfg.sub) ? " · " + mw(cfg.sub) : ""}`;
        else if (cfg.sub === "rsi") val = fmt(b.rsi, 0);
        else if (cfg.sub === "fomc") { const x = FOMC[b.d]; val = x ? `${md(x[0])}：不变 ${Math.round(x[1] * 100)}% · 降 ${Math.round(x[2] * 100)}% · 加 ${Math.round(x[3] * 100)}%` : "这天没有数据"; }
        else if (cfg.sub === "vix") val = fmt(dv(i, "vix"), 1);
        else if (cfg.sub === "t3") val = fmt(dv(i, "t3"), 3);
        else if (cfg.sub === "breadth") val = `${fmt(dv(i, "pct50"), 0)}% / ${fmt(dv(i, "pct200"), 0)}%`;
        ks.innerHTML = cfg.sub === "heat" && G.W < 560 ? `<b>${val}</b>` : `${esc(G.sub.lab)}：<b>${val}</b>`; } else ks.hidden = true;
    }
    function maState(i) {
      const ps = DEF_MA.filter(p => isFinite((MA[p] || XMA[p] || [])[i])), v = ps.map(p => (MA[p] || XMA[p])[i]);
      let bull = v.length >= 3, bear = v.length >= 3;
      for (let k = 1; k < v.length; k++) { if (!(v[k - 1] > v[k])) bull = false; if (!(v[k - 1] < v[k])) bear = false; }
      const below = ps.filter((p, k) => B[i].c < v[k]).length;
      return { n: ps.length, below, txt: bull ? "多头排列" : bear ? "空头排列" : "均线交织", cls: bull ? "pos" : bear ? "neg" : "" };
    }
    function lastCross(a, b, i, back) {
      const A = XMA[a], Bm = XMA[b];
      for (let k = i; k > Math.max(0, i - back); k--) { if (!isFinite(A[k - 1]) || !isFinite(Bm[k - 1])) break; const s0 = Math.sign(A[k - 1] - Bm[k - 1]), s1 = Math.sign(A[k] - Bm[k]); if (s0 !== s1 && s1 !== 0) return { i: k, gold: s1 > 0 }; }
      let n = 0; for (let k = i; k > Math.max(0, i - back) && isFinite(A[k]) && isFinite(Bm[k]); k--) n++; return { none: n };
    }
    const crossTxt = (a, b, i, back) => { const c = lastCross(a, b, i, back); if (c.none != null) return c.none < 2 ? "数据不足" : `近 ${c.none} 个交易日没有交叉`; return `<span class="${c.gold ? "pos" : "neg"}">${c.gold ? "金叉" : "死叉"}</span> ${B[c.i].d}`; };
    function swingNow() {
      const H = PIV.filter(x => x.t === "H").slice(-2), L = PIV.filter(x => x.t === "L").slice(-2), c = lastOf(B).c;
      if (H.length < 2 || L.length < 2) return "摆动点不够，判断不了结构";
      const hh = H[1].p > H[0].p, hl = L[1].p > L[0].p, st = hh && hl ? "上升结构" : !hh && !hl ? "下降结构" : "震荡结构";
      return `${st}（最近两个高点 ${fmtP(H[0].p)} → ${fmtP(H[1].p)}，低点 ${fmtP(L[0].p)} → ${fmtP(L[1].p)}）。现价离上一个摆动低点 ${sgn((c / L[1].p - 1) * 100, 1)}%，离上一个摆动高点 ${sgn((c / H[1].p - 1) * 100, 1)}%`;
    }
    function renderMA() {
      const i = B.length - 1, m = maState(i);
      $("kma").innerHTML = `<span><b>均线（${B[i].d}）</b></span><span class="${m.cls}">${m.txt}</span><span>价格在 ${m.n} 条均线中的 ${m.below} 条下方</span><span>MA50 / MA200：${crossTxt(50, 200, i, 1000)}</span><span>MA5 / MA20：${crossTxt(5, 20, i, 120)}</span><span>趋势结构：${swingNow()}</span>`;
      $("kkey").innerHTML = `<b>阶段标签</b>（进入某一段的那天）：<b style="color:var(--s1i)">在卖</b> 成分股普跌、放量 · <b style="color:var(--s2i)">在怕</b> 保险比平时贵、散户突然转空 · <b style="color:var(--s3i)">投降</b> 抢买保护、信用利差走阔、VIX 冲高（价格区也铺一层浅红）。同一段相邻 10 天只标一次。<br><b>转折标签</b>：<b style="color:var(--fear)">恐慌高峰</b> 一段下跌里恐慌最高的那天（要等恐慌退了才标出来）· <b style="color:var(--s4i)">恐慌退潮</b> 怕过以后各项读数都退了 · 空心的 <b style="color:var(--violet)">二次探底</b> 价格回到低点附近、恐慌没跟上 · 空心的 <b style="color:var(--watch)">参与度先走</b> 指数在高点附近、成分股却少了一截（只是描述，不说明到顶）。<br><b>品种自己的标签</b>（可以单独关掉）：空心的 <b style="color:var(--alert)">抛售</b> 2 倍成交量的大跌、而且已经超卖${cur.k === "SOX" ? "（用 SMH 的成交量）" : ""} · 空心的 <b style="color:var(--greed)">涨过头</b> RSI 高于 75、比 50 日线高 15% 以上（只说明涨得急，不说明哪天见顶）。<br><b>色带</b>：价格区最下面一条，每天一个颜色，就是当天在哪一段；空白是平稳。阶段和恐慌热度都是整个半导体市场的读数，KOSPI、海力士等别的品种按同一天（或之前最近一个美股交易日）对照。<b>灰色小圈</b> = 摆动高点和低点，虚线连着最近两个高点（橙）和最近两个低点（蓝）。成交量里颜色深的柱子是平时 2 倍以上的量。`;
    }
    const fwdK = (i, k) => i + k < B.length ? (B[i + k].c / B[i].c - 1) * 100 : null;
    const extK = (i, k, upw) => { if (i + 1 >= B.length) return null; let m = 0; for (let j = i + 1; j <= Math.min(B.length - 1, i + k); j++) { const r = B[j].c / B[i].c - 1; m = upw ? Math.max(m, r) : Math.min(m, r); } return m * 100; };
    function dayPanel(i) {
      const b = B[i], last = i === B.length - 1, pv = B[i - 1], ch = pv ? (b.c / pv.c - 1) * 100 : null;
      const maRows = cfg.mas.map(p => { const m = MA[p][i]; if (!isFinite(m)) return ""; const d = (b.c / m - 1) * 100, m5 = i >= 5 ? MA[p][i - 5] : NaN, sl = isFinite(m5) ? (m > m5 ? "↗" : m < m5 ? "↘" : "→") : "";
        return `<tr><td><i class="sw" style="background:${maCol(p)}"></i>MA${p}</td><td class="num">${fmtP(m)} ${sl}</td><td class="num"${cP(d)}>${sgn(d, 1)}%</td></tr>`; }).join("");
      const ms = maState(i), k = b.di;
      let state = "<p>这一天没有半导体市场的读数（这个市场单独开市的日子，或者在数据开始之前）。</p>";
      if (k != null) { const r = row(k), F3 = facts(r), rg = r.regime === 1 ? "宏观冲击型" : r.regime === 2 ? "板块自己跌型" : "";
        const mv = LN.map(([key, nm, mk]) => `${nm}<b>${LVW(r[key])}</b>${r[mk] == null ? "" : "，" + MW[r[mk]]}`).join(" · ");
        state = `<div class="big" style="color:${SINK(r.state)}">${NAMES[r.state]}${rg ? ` <span style="font-size:13px;color:var(--ink-3);font-weight:500">${rg}</span>` : ""}</div><p>${mv}</p><div class="three">` + ["在卖", "在怕", "投降"].map((nm, j) => `<div><p style="margin-top:6px"><b>${nm}</b></p>${factHTML(F3[j], j + 1)}</div>`).join("") + `</div>`; }
      const dn = (DAYNEWS[b.d] || []), fx = FOMC[b.d];
      const dayInfo = dn.length || fx ? `<div class="kpc" style="grid-column:1/-1"><h4>这一天存下的新闻和预测市场</h4>${fx ? `<p>下次议息会（${md(fx[0])}）：不变 ${Math.round(fx[1] * 100)}% · 降息 ${Math.round(fx[2] * 100)}% · 加息 ${Math.round(fx[3] * 100)}%</p>` : ""}${dn.length ? `<ul class="nw">${dn.map(([tp, t, src, url]) => `<li><a href="${esc(url)}" target="_blank" rel="noopener">${esc(t)}</a><small>${esc(tp)} · ${esc(src)}</small></li>`).join("")}</ul>` : ""}</div>` : "";
      const vr = isFinite(V50[i]) && V50[i] > 0 ? b.v / V50[i] : null;
      const mom = `<table><tr><td>RSI(14)</td><td class="num">${fmt(b.rsi, 0)}</td></tr><tr><td>10 日</td><td class="num"${cP(i >= 10 ? b.c / B[i - 10].c - 1 : null)}>${i >= 10 ? pctP((b.c / B[i - 10].c - 1) * 100) : "—"}</td></tr><tr><td>20 日</td><td class="num"${cP(i >= 20 ? b.c / B[i - 20].c - 1 : null)}>${i >= 20 ? pctP((b.c / B[i - 20].c - 1) * 100) : "—"}</td></tr>${hasVol ? `<tr><td>成交量 ÷ 50 日均量</td><td class="num">${vr == null ? "—" : fmt(vr, 2)}</td></tr>` : ""}</table>`;
      const after = last ? "<p>这是最新一天，之后的走势待观察。</p>"
        : `<table><tr><td>5 日后</td><td class="num"${cP(fwdK(i, 5))}>${pctP(fwdK(i, 5))}</td></tr><tr><td>20 日后</td><td class="num"${cP(fwdK(i, 20))}>${pctP(fwdK(i, 20))}</td></tr><tr><td>60 日后</td><td class="num"${cP(fwdK(i, 60))}>${pctP(fwdK(i, 60))}</td></tr><tr><td>20 日内最大跌幅</td><td class="num neg">${pctP(extK(i, 20, false))}</td></tr><tr><td>20 日内最大涨幅</td><td class="num pos">${pctP(extK(i, 20, true))}</td></tr></table>`;
      return `<div class="kph"><b>${esc(cur.n)} · ${b.d}</b><span class="num">收 ${fmtP(b.c)}</span><span class="num"${cP(ch)}>${ch == null ? "" : sgn(ch, 2) + "%"}</span><span class="sp"></span>${last ? "" : '<button type="button" class="kbtn" data-act="latest">回到最新一天</button>'}</div>
        <div class="kpg"><div class="kpc" style="grid-column:1/-1"><h4>半导体市场这一天在哪一段${cur.k === "SOX" ? "" : "（整个半导体市场的读数）"}</h4>${state}</div>
        <div class="kpc"><h4>动量和量能</h4>${mom}</div>
        <div class="kpc"><h4>均线 · ${ms.txt}</h4><table>${maRows}</table><p>MA50/MA200：${crossTxt(50, 200, i, 1000)}</p></div>
        <div class="kpc"><h4>之后的走势</h4>${after}</div>${dayInfo}</div>`;
    }
    function hPanel(dw) {
      const P = dw.p, n = B.length, ev = []; let lastT = -99;
      for (let i = 5; i < n; i++) { const b = B[i], t = b.real ? (b.h >= P * 0.99 && b.l <= P * 1.01) : Math.abs(b.c / P - 1) <= 0.015; if (t && i - lastT > 10) ev.push(i); if (t) lastT = i; }
      const rows = ev.map(i => { const kind = B[i - 5].c >= P ? "s" : "r"; let res = "进行中";
        if (i + 10 < n) { const w = B.slice(i + 1, i + 11).map(x => x.c); res = kind === "s" ? (Math.min(...w) >= P * 0.97 ? "守住" : "跌破") : (Math.max(...w) > P * 1.03 ? "突破" : "受阻"); }
        return { i, kind, res, st: dv(i, "state"), f10: fwdK(i, 10), f20: fwdK(i, 20) }; });
      const curP = B[n - 1].c, dist = (curP / P - 1) * 100, role = curP >= P ? "支撑" : "压力";
      const grp = (k, r) => rows.filter(x => x.kind === k && x.res === r), sH = grp("s", "守住"), sB = grp("s", "跌破"), rT = grp("r", "突破"), rS = grp("r", "受阻");
      const ins = rows.length ? `作为支撑被测试 ${sH.length + sB.length} 次，守住 ${sH.length} 次；作为压力被测试 ${rT.length + rS.length} 次，突破 ${rT.length} 次。` : "这条线在现有数据里没有被触及过。";
      const tbl = rows.length ? `<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>日期</th><th>测试</th><th>当时阶段</th><th>结果</th><th class="r">10 日后</th><th class="r">20 日后</th></tr></thead><tbody>${rows.slice().reverse().map(r => `<tr><td><button type="button" class="jd" data-jump="${B[r.i].d}">${B[r.i].d}</button></td><td>${r.kind === "s" ? "支撑" : "压力"}</td><td>${r.st == null ? "—" : NAMES[r.st]}</td><td>${r.res}</td><td class="r"${cP(r.f10)}>${pctP(r.f10)}</td><td class="r"${cP(r.f20)}>${pctP(r.f20)}</td></tr>`).join("")}</tbody></table></div>` : "";
      return `<div class="kph"><b>水平线 ${fmtP(P)}</b><span>现价 ${fmtP(curP)}，在线${curP >= P ? "上方" : "下方"} ${fmt(Math.abs(dist), 1)}%，按${role}看</span><span class="sp"></span><button type="button" class="kbtn" data-act="del" data-id="${dw.id}">删除这条线</button></div>
        <p class="kpins">${ins}${rows.length && rows.length < 8 ? ` 样本只有 ${rows.length} 次，只作参考。` : ""}</p>${tbl}
        <p class="knote">触及：当天最高价和最低价跨过这条线上下 1%，相邻 10 个交易日只算一次。守住：之后 10 个交易日收盘没有跌破线下 3%。突破：之后 10 个交易日有收盘站上线上 3%。</p>`;
    }
    function tPanel(dw) {
      const a = DI.get(dw.d1), b = DI.get(dw.d2);
      if (a == null || b == null) return `<div class="kph"><b>趋势线</b><span class="sp"></span><button type="button" class="kbtn" data-act="del" data-id="${dw.id}">删除这条线</button></div><p class="kpins">这条线的日期不在当前数据里。</p>`;
      const chg = (B[b].c / B[a].c - 1) * 100; let pk = B[a].c, mdd = 0, tr = B[a].c, mup = 0;
      for (let i = a; i <= b; i++) { pk = Math.max(pk, B[i].c); mdd = Math.min(mdd, B[i].c / pk - 1); tr = Math.min(tr, B[i].c); mup = Math.max(mup, B[i].c / tr - 1); }
      const sigs = []; for (let i = a; i <= b; i++) { const ms = MK.get(B[i].d); if (ms) for (const m of ms) sigs.push(`<span class="chip"><button type="button" class="jd" data-jump="${B[i].d}">${B[i].d.slice(5)}</button> ${m.t}</span>`); }
      const L = B.length - 1, pNow = dw.p1 + (dw.p2 - dw.p1) * (L - a) / ((b - a) || 1), dNow = (B[L].c / pNow - 1) * 100, slope = (Math.pow(dw.p2 / dw.p1, 1 / ((b - a) || 1)) - 1) * 100;
      const st = i => `RSI ${fmt(B[i].rsi, 0)} · 阶段 ${dv(i, "state") == null ? "—" : NAMES[dv(i, "state")]}`;
      return `<div class="kph"><b>趋势线 ${dw.d1} → ${dw.d2}</b><span class="num">${fmtP(dw.p1)} → ${fmtP(dw.p2)}，每天 ${sgn(slope, 2)}%</span><span class="sp"></span><button type="button" class="kbtn" data-act="del" data-id="${dw.id}">删除这条线</button></div>
        <div class="kpg"><div class="kpc"><h4>区间行情（${b - a} 个交易日）</h4><table><tr><td>收盘涨跌</td><td class="num"${cP(chg)}>${pctP(chg)}</td></tr><tr><td>区间最大回撤</td><td class="num neg">${pctP(mdd * 100)}</td></tr><tr><td>区间最大反弹</td><td class="num pos">${pctP(mup * 100)}</td></tr></table></div>
        <div class="kpc"><h4>起点和终点</h4><p>起点：${st(a)}</p><p>终点：${st(b)}</p></div>
        <div class="kpc"><h4>区间里的标签</h4>${sigs.length ? `<div class="chips">${sigs.join("")}</div>` : "<p>没有。</p>"}</div>
        <div class="kpc"><h4>延伸到今天</h4>${b < L ? `<div class="big num">${fmtP(pNow)}</div><p>现价 ${fmtP(B[L].c)}，在线${dNow >= 0 ? "上方" : "下方"} ${fmt(Math.abs(dNow), 1)}%</p>` : "<p>终点就是最新一天。</p>"}</div></div>`;
    }
    function panel() {
      const el = $("kpanel"); let html;
      if (previewI != null && !(sel && sel.type === "draw")) { el.innerHTML = dayPanel(previewI); return; }
      if (sel && sel.type === "draw") { const dw = draws().find(x => x.id === sel.id); html = dw ? (dw.type === "h" ? hPanel(dw) : tPanel(dw)) : null; if (!dw) sel = null; }
      if (!html) html = dayPanel(sel && sel.type === "day" ? clampI(sel.i) : B.length - 1);
      el.innerHTML = html;
    }
    function toolbar() {
      const on = c => c ? " on" : "";
      $("ktools").innerHTML = `
        <div class="kgrp" role="group" aria-label="品种">${SYMS.map(s => `<button type="button" class="kbtn${on(s.k === cfg.sym)}" data-sym="${esc(s.k)}">${esc(s.n)}</button>`).join("")}</div>
        <div class="kgrp" role="group" aria-label="时间范围">${[[63, "3月"], [126, "6月"], [252, "1年"], [756, "3年"], [0, "全部"]].map(([n, t]) => `<button type="button" class="kbtn${on(cfg.n === n)}" data-rng="${n}">${t}</button>`).join("")}<button type="button" class="kbtn" data-zoom="0.8" aria-label="放大">＋</button><button type="button" class="kbtn" data-zoom="1.25" aria-label="缩小">－</button></div>
        <div class="kgrp" role="group" aria-label="画线工具"><span class="kl">画线</span>${[["pick", "点选"], ["h", "水平线"], ["t", "趋势线"]].map(([k, t]) => `<button type="button" class="kbtn${on(tool === k)}" data-tool="${k}">${t}</button>`).join("")}<button type="button" class="kbtn" data-act="clear">${clearArm ? "再点一次确认" : "清除画线"}</button></div>
        <div class="kgrp" role="group" aria-label="均线"><span class="kl">均线</span>${cfg.mas.map(p => `<button type="button" class="kbtn mach${cfg.on[p] ? "" : " off"}" data-ma="${p}"><i style="background:${maCol(p)}"></i>MA${p}${DEF_MA.includes(p) ? "" : ' <span data-rm="' + p + '" aria-label="删除">×</span>'}</button>`).join("")}<input id="k-maadd" type="number" min="2" max="400" step="1" placeholder="周期" aria-label="添加均线周期"><button type="button" class="kbtn" data-act="addma">添加</button></div>
        <div class="kgrp"><label for="k-sub" class="kl">副图</label><select id="k-sub">${SUBS.map(([id, t]) => `<option value="${id}"${cfg.sub === id ? " selected" : ""}>${t}</option>`).join("")}</select>
          <label><input type="checkbox" id="k-mk"${cfg.mk ? " checked" : ""}>阶段标签</label><label><input type="checkbox" id="k-smk"${cfg.smk ? " checked" : ""}>抛售 / 涨过头</label><label><input type="checkbox" id="k-bg"${cfg.bg ? " checked" : ""}>阶段色带</label><label><input type="checkbox" id="k-sw"${cfg.sw ? " checked" : ""}>摆动结构</label>
          <button type="button" class="kbtn" data-act="updown">${cfg.redUp ? "红涨绿跌" : "绿涨红跌"}</button></div>`;
      $("k-sub").onchange = e => { cfg.sub = e.target.value; saveCfg(); schedule(); };
      $("k-mk").onchange = e => { cfg.mk = e.target.checked; saveCfg(); buildMarkers(); schedule(); };
      $("k-smk").onchange = e => { cfg.smk = e.target.checked; saveCfg(); buildMarkers(); schedule(); };
      $("k-bg").onchange = e => { cfg.bg = e.target.checked; saveCfg(); schedule(); };
      $("k-sw").onchange = e => { cfg.sw = e.target.checked; saveCfg(); schedule(); };
      $("k-maadd").onkeydown = e => { if (e.key === "Enter") addMA(); };
    }
    function addMA() { const el = $("k-maadd"), p = Math.round(+el.value); if (!(p >= 2 && p <= 400)) { el.value = ""; el.placeholder = "2–400"; return; }
      if (!cfg.mas.includes(p)) { cfg.mas.push(p); cfg.mas.sort((a, b) => a - b); } cfg.on[p] = 1; saveCfg(); build(); toolbar(); panel(); schedule(); }
    function setTool(t) { tool = t; pend = null; $("khint").hidden = t === "pick"; $("khint").textContent = t === "h" ? "在价格区点一下，放一条水平线" : t === "t" ? "点第一个点" : ""; toolbar(); schedule(); }
    $("ktools").addEventListener("click", e => {
      const t = e.target.closest("button"), rm = e.target.closest("[data-rm]");
      if (rm) { const p = +rm.dataset.rm; cfg.mas = cfg.mas.filter(x => x !== p); delete cfg.on[p]; saveCfg(); build(); toolbar(); panel(); schedule(); return; }
      if (!t) return;
      if (t.dataset.sym) { cfg.sym = t.dataset.sym; saveCfg(); sel = null; pend = null; build(); buildMarkers(); setRange(cfg.n); toolbar(); panel(); renderMA(); schedule(); }
      else if (t.dataset.rng != null) { cfg.n = +t.dataset.rng; saveCfg(); setRange(cfg.n); toolbar(); schedule(); }
      else if (t.dataset.zoom) zoomAt(G.R - 10, view.n * +t.dataset.zoom);
      else if (t.dataset.tool) setTool(t.dataset.tool);
      else if (t.dataset.ma) { const p = +t.dataset.ma; cfg.on[p] = cfg.on[p] ? 0 : 1; saveCfg(); toolbar(); panel(); schedule(); }
      else if (t.dataset.act === "addma") addMA();
      else if (t.dataset.act === "updown") { cfg.redUp = !cfg.redUp; saveCfg(); setUpDown(); toolbar(); schedule(); }
      else if (t.dataset.act === "clear") {
        if (clearArm && Date.now() - clearArm < 4000) { allDraws[cfg.sym] = []; saveDraws(); clearArm = 0; if (sel && sel.type === "draw") sel = null; panel(); }
        else { clearArm = Date.now(); setTimeout(() => { if (clearArm && Date.now() - clearArm >= 3900) { clearArm = 0; toolbar(); } }, 4000); }
        toolbar(); schedule();
      }
    });
    $("kpanel").addEventListener("click", e => { const t = e.target.closest("button[data-act]"); if (!t) return;
      if (t.dataset.act === "del") { allDraws[cfg.sym] = draws().filter(x => x.id !== t.dataset.id); saveDraws(); sel = null; panel(); schedule(); }
      if (t.dataset.act === "latest") { sel = null; setRange(cfg.n); panel(); schedule(); } });
    const cv = $("kc"), ptrs = new Map();
    const pos = e => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    function snap(i, y) { const b = B[i], cands = b.real ? [b.h, b.l, b.o, b.c] : [b.c]; let best = null, bd = 10; for (const p of cands) { const d = Math.abs(yP(p) - y); if (d < bd) { bd = d; best = p; } } return best != null ? best : pAt(y); }
    function hitDraw(x, y) { const list = draws();
      for (let k = list.length - 1; k >= 0; k--) { const dw = list[k];
        if (dw.type === "h") { if (y <= G.pH && Math.abs(y - yP(dw.p)) < 7) return dw; continue; }
        const a = DI.get(dw.d1), b = DI.get(dw.d2); if (a == null || b == null) continue;
        const x1 = xOf(a), y1 = yP(dw.p1), x2 = xOf(b), y2 = yP(dw.p2), sl = (y2 - y1) / ((x2 - x1) || 1), xe = Math.max(x2, G.R), ye = y2 + sl * (xe - x2);
        const vx = xe - x1, vy = ye - y1, L2 = vx * vx + vy * vy || 1, t = Math.max(0, Math.min(1, ((x - x1) * vx + (y - y1) * vy) / L2));
        if (Math.hypot(x - (x1 + t * vx), y - (y1 + t * vy)) < 7) return dw; }
      return null; }
    function addDraw(o) { o.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6); draws().push(o); saveDraws(); sel = { type: "draw", id: o.id }; setTool("pick"); panel(); }
    function tap(x, y) {
      const i = clampI(idxAt(x));
      if (tool === "h") { if (y > G.pH) return; addDraw({ type: "h", p: snap(i, y) }); return; }
      if (tool === "t") { if (y > G.pH) return; const p = snap(i, y);
        if (!pend) { pend = { i, p }; $("khint").textContent = "再点第二个点"; schedule(); return; }
        if (i === pend.i) return; const [A, Z] = pend.i < i ? [pend, { i, p }] : [{ i, p }, pend];
        pend = null; addDraw({ type: "t", d1: B[A.i].d, p1: A.p, d2: B[Z.i].d, p2: Z.p }); return; }
      const dw = hitDraw(x, y); sel = dw ? { type: "draw", id: dw.id } : { type: "day", i }; panel(); schedule();
    }
    cv.addEventListener("pointerdown", e => { const p = pos(e); ptrs.set(e.pointerId, p); try { cv.setPointerCapture(e.pointerId); } catch (er) {}
      if (ptrs.size === 1) gest = { x0: p.x, y0: p.y, end0: view.end, moved: false, t0: Date.now() };
      else if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; gest = { pinch: true, d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, n0: view.n, mid: (a.x + b.x) / 2, moved: true }; } });
    cv.addEventListener("pointermove", e => { const p = pos(e); if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, p);
      if (gest && gest.pinch && ptrs.size === 2) { const [a, b] = [...ptrs.values()]; zoomAt(gest.mid, gest.n0 * gest.d0 / Math.max(10, Math.hypot(a.x - b.x, a.y - b.y))); return; }
      if (gest && ptrs.size === 1) { const dx = p.x - gest.x0; if (gest.moved || Math.abs(dx) > 6) { gest.moved = true; view.end = gest.end0 - dx / G.barW; clampView(); }
        if (e.pointerType !== "mouse") { if (gest.moved) hover = null; schedule(); return; } }
      hover = p; hover.mouse = e.pointerType === "mouse"; schedule(); });
    const endPtr = e => { const p = pos(e); ptrs.delete(e.pointerId); if (gest && !gest.pinch && !gest.moved && Date.now() - gest.t0 < 700 && e.type === "pointerup") tap(p.x, p.y); if (!ptrs.size) gest = null; };
    cv.addEventListener("pointerup", endPtr); cv.addEventListener("pointercancel", endPtr);
    cv.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") { hover = null; schedule(); } });
    cv.addEventListener("wheel", e => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoomAt(pos(e).x, view.n * (e.deltaY > 0 ? 1.12 : 1 / 1.12)); }
      else if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) { e.preventDefault(); view.end += e.deltaX / G.barW; clampView(); schedule(); } }, { passive: false });
    cv.addEventListener("keydown", e => { const c = sel && sel.type === "day" ? sel.i : B.length - 1;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); sel = { type: "day", i: clampI(c + (e.key === "ArrowLeft" ? -1 : 1)) }; if (xOf(sel.i) < G.L || xOf(sel.i) > G.R) { view.end = sel.i + view.n * 0.3; clampView(); } panel(); schedule(); }
      else if (e.key === "+" || e.key === "=") zoomAt(G.R - 10, view.n * 0.8);
      else if (e.key === "-") zoomAt(G.R - 10, view.n * 1.25);
      else if (e.key === "Escape") setTool("pick"); });
    $("kpan").addEventListener("input", e => { view.end = +e.target.value; clampView(); schedule(); });
    window.addEventListener("resize", () => schedule());
    build(); buildMarkers(); setRange(cfg.n); toolbar(); renderMA(); panel(); draw();
    try { new MutationObserver(() => schedule()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); } catch (e) {}
    return {
      jump(d) { let i = DI.get(d); if (i == null) { i = B.findIndex(b => b.d >= d); if (i < 0) i = B.length - 1; }
        view.end = i + view.n * 0.35; clampView(); sel = { type: "day", i }; panel(); schedule(); }
    };
  })();
  document.addEventListener("click", e => { const b = e.target.closest && e.target.closest("[data-jump]"); if (b) KL.jump(b.dataset.jump); });
})();
