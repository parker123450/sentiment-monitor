// 情绪阶段页面的脚本。RAW 由 qx/page.py 塞在前面。K 线部分照「科技情绪全景」的 K 线（版式、交互、画线、面板）搬过来，换成新的阶段和恐慌读数。
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
  const fmt = (x, dp = 2) => x == null || !isFinite(x) ? "—" : x.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const sgn = (x, dp = 2) => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), dp);
  const lastOf = a => a[a.length - 1];
  const tok = name => (getComputedStyle(document.documentElement).getPropertyValue(name) || "").trim();
  // 点了才取的加密小文件（K 线 k/*.enc；说明、状态 v/*.enc）：用解锁时留下的钥匙（window.QX_KEY）解开；本机预览是明文
  async function fetchEnc(path) {
    const r = await fetch(path, { cache: "force-cache" }); if (!r.ok) throw new Error("HTTP " + r.status);
    if (!window.QX_KEY) return await r.text();
    const b = new Uint8Array(await r.arrayBuffer()), key = await crypto.subtle.importKey("raw", window.QX_KEY, "AES-GCM", false, ["decrypt"]);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b.slice(0, 12) }, key, b.slice(12));
    return await new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  }
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
  const bjDay = d => new Date(Date.parse(d + "T12:00:00Z") + 864e5).toISOString().slice(0, 10);     // 议息会决议美东 14:00 = 北京第二天 02:00 / 03:00
  const FOMC = (RAW.happen && RAW.happen.day && RAW.happen.day.fomc) || {}, DAYNEWS = (RAW.happen && RAW.happen.day && RAW.happen.day.news) || {};

  // ---------- 把一天的数字写成白话（三段各几条）
  const level = p => p == null ? [0, "—"] : [p >= 90 ? 2 : p >= 70 ? 1 : 0, "分位 " + Math.round(p)];      // 颜色、✓ 的门槛 90 / 70 不变，只是不写词（口径十四.2）
  const fr = f => f == null ? "—" : f < 0.001 ? "不到 0.1%" : (f * 100).toFixed(f < 0.1 ? 1 : 0) + "%";      // "历史上百分之几的日子更极端"
  const plain = s => String(s == null ? "" : s).replace(/neocloud/g, "算力云")      // 登记表里的英文名、"2/5"写成白话（只改显示）；第 0 环写"还没走到第 1 环"
    .replace(/(走到)?第 (\d+)\/(\d+) 环/g, (_, w, a, b) => +a ? `${w || ""}第 ${a} 环（共 ${b} 环）` : `还没走到第 1 环（共 ${b} 环）`);
  // "今天变了什么"的条目是推送也读的字（qx/watch.py，口径三），里面"少见"没有数；页面上换成登记的门槛，字和推送都不动：
  // 四条读数和阶段的分项是分位 ≥90；单日 / 5 日涨跌是过去 10 年同方向一样极端的日子 ≤ RARE_US（美股以外 RARE_LINKED）；保险比实际波动是过去 10 年两头各 RARE。
  // 门槛的数从 qx/front.py build() 的 rare 来（就是 qx/watch.py 的常量），页面不另写一份；拿不到就只写"过了门槛"
  const RQ = (RAW.front && RAW.front.rare) || null, rp = x => +(x * 100).toFixed(2) + "%", yr = RQ ? `过去 ${RQ.yrs} 年` : "";
  const RWD = [[/第一次到了历史上少见的程度/g, "第一次到分位 90 以上"], [/今天到了历史上少见的：/g, "今天到了分位 90 以上的："], [/第一次到少见的读数：/g, "第一次到分位 90 以上的读数："],
    [/单独一条读数到少见/g, "单独一条读数到分位 90 以上"], [/^也少见：/, RQ ? `同组也过了门槛（${yr}同方向一样极端的日子不超过 ${rp(RQ.us)}，美股以外 ${rp(RQ.linked)}）：` : "同组也过了门槛："],
    [/比实际波动贵得少见：/, RQ ? `比实际波动贵到了${yr}最贵的 ${rp(RQ.ivrv)}：` : "比实际波动贵过了门槛："], [/比实际波动便宜得少见：/, RQ ? `比实际波动便宜到了${yr}最便宜的 ${rp(RQ.ivrv)}：` : "比实际波动便宜过了门槛："]];
  const rwd = s => RWD.reduce((a, [r, t]) => a.replace(r, t), String(s == null ? "" : s));
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
       [r.etfp, `信用 ETF 跑输国债（单独提醒，不算进投降）`],
       [r.baarp, `公司债比国债多要的利息，20 天里${r.baa20 >= 0 ? "多了" : "少了"} ${Math.abs(r.baa20)} 个基点`],
       [r.vixlp, `VIX ${fmt(r.vix, 1)}；大跌见底时常在 30 上下`]],
    ];
  }
  const factHTML = (list, s) => list.map(([p, t]) => { const [lv, w] = level(p), c = lv === 2 ? SINK(s) : lv === 1 ? tok("--ink-2") : tok("--ink-3");
    return `<div class="fact"><span class="m" style="color:${c}">${lv === 2 ? "✓" : "·"}</span><span class="x">${t}</span><span class="w" style="color:${c}">${w}</span></div>`; }).join("");

  // ---------- 顶部：一句话、四条读数、最近一年
  const LVW = p => level(p)[1], MW = RAW.momwords || [];
  const LVS = p => p == null ? "—" : Math.round(p);      // 副图那一行地方小，只写分位
  const LN = [["sell", "抛售", "msell", "成分股创 20 天新低的多少"], ["price", "定价", "mprice", "科技股保险比平时贵"], ["pos", "仓位", "mpos", "抢买认沽、散户转空"], ["credit", "信用", "mcredit", "信用 ETF 跑输国债"]];
  (function head() {
    const r = row(LASTK), st = r.state, ccc = RAW.ice["CCC 及以下"], ig = RAW.ice["投资级"];
    if ($("upd")) $("upd").textContent = `页面更新于北京时间 ${RAW.updated}。`;
    const warn = [];
    for (const [nm, v] of Object.entries(RAW.status || {})) {
      if (!v.last) { warn.push(`${nm}没有数据`); continue; }
      const lag = (Date.parse(RAW.asof) - Date.parse(v.last)) / 864e5;
      if (lag > (nm.startsWith("AAII") ? 9 : 4)) warn.push(`${nm}最新只到 ${md(v.last)}`);
    }
    if (warn.length && $("warn")) { $("warn").hidden = false; $("warn").textContent = "数据提醒：" + warn.join("；") + "。相关读数沿用最近一次的。"; }
    // 新4：情绪全部（大标题、导语、四条读数、三段、谁跌得最深、信用分层表）不画了，节点不在页面上；代码留着（_impl/design/hidden_draft.md）
    if (!$("hero")) return;
    $("asof").textContent = `数据截至 ${RAW.asof} 收盘`;
    const tail = { 0: "没有在下跌。", 1: "抛售开始了，还没人怕。", 2: "投降还没来。", 3: "历史上最低点多在这几天或之后。", 4: "恐慌在退。" }[st];
    $("hero").innerHTML = `<span class="tag" style="background:${SFILL(st)};color:${SINK(st)}">${st >= 1 && st <= 3 ? "第" + "一二三"[st - 1] + "段" : "现在"}</span>${NAMES[st]}。${tail}`;
    let lead = `费城半导体 10 天${r.r10 < 0 ? "跌" : "涨"}了 ${fmt(Math.abs(r.r10), 1)}%，离一年高点 ${fmt(r.dd, 1)}%。`;
    if (r.regime === 1) lead += `这次是宏观冲击型：这一段 VIX 最高到过 ${fmt(r.vixmax, 1)}，大盘也在怕。`;
    if (r.regime === 2) lead += `这次是板块自己跌：这一段 VIX 最高只有 ${fmt(r.vixmax, 1)}，大盘读数看不出来，要看"比自己最近"的读数和成分股。`;
    if (st >= 1) lead += `${r.n20} 只半导体股里 ${r.nb20} 只跌破了 20 日线，成交量是平时的 ${fmt(r.volx, 2)} 倍。`;
    if (st >= 2) lead += `科技股保险比平时贵了 ${Math.round((r.vxn / r.vxnm - 1) * 100)}%。`;
    if (st === 2) {
      const parts = [`信用 ETF 跑输国债${r.etfp == null ? "" : `，分位 ${Math.round(r.etfp)}`}`];
      if (ccc) parts.push(`最差的公司（CCC）利差一个月${ccc.now >= ccc.m1 ? "走阔" : "收窄"}了 ${Math.abs(ccc.now - ccc.m1)} 个基点`);
      lead += parts.join("，") + "；" + (r.pcrp >= 90 ? "大家已经在抢着买保护" : "但还没人抢着买保护") + (ig ? `，投资级利差一个月${ig.now >= ig.m1 ? "多" : "少"}了 ${Math.abs(ig.now - ig.m1)} 个基点。` : "。");
    }
    $("lead").textContent = lead;
    $("lines").innerHTML = LN.map(([k, nm, mk, what]) => { const [lv, w] = level(r[k]), m = r[mk], c = lv === 2 ? tok("--alert") : lv === 1 ? tok("--ink-2") : tok("--ink-3");
      return `<div class="ln"><span class="k">${nm}</span><span class="mv" style="white-space:normal">${what}</span><span class="w"><b style="color:${c}">${w}</b>${m == null ? "" : " · " + MW[m]}</span></div>`; }).join("") +
      "";                                              // CNN 恐慌贪婪那一行搬到 说明（第四轮后台精简第 2 步；口径二.4 本来就不进阶段）
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
    $("ice").innerHTML = `<tr><th>评级</th><th class="r">现在（基点）</th><th class="r">5 日</th><th class="r">一个月里</th><th>三年里的位置</th></tr>` +
      Object.entries(RAW.ice).map(([k, v]) => { const p = (v.now - v.lo) / ((v.hi - v.lo) || 1) * 100, ch = v.now - v.m1;
        return `<tr><td>${esc(k)}<small>截至 ${md(v.date)}</small></td><td class="r num">${v.now}</td><td class="r num">${sgn(v.c5, 0)}${v.lvl5 && v.f5 != null ? `<small style="color:var(--alert)">历史上 ${fr(v.f5)} 的日子更极端</small>` : ""}</td><td class="r num">${sgn(ch, 0)}</td><td><div class="bar" title="三年最低 ${v.lo}，最高 ${v.hi}"><i style="width:${Math.max(3, p).toFixed(0)}%"></i></div></td></tr>`; }).join("");
  })();

  // ---------- 前台（新4，qx/front.py page_keys()；口径十四）：①–⑤ 每样一行，整行点开，一次只开一样；点开里每样最多 5 行
  // 旧的五样写法（结论句、表格、触发行）不画了：触发行全进"今天变了什么"（qx/front.py page_changes()），其余见 _impl/design/hidden_draft.md
  const FR = RAW.front || {};
  const D2 = s => s ? `${+s.slice(5, 7)}/${+s.slice(8, 10)}` : "";
  const N0 = x => x == null || !isFinite(x) ? "—" : Math.round(x).toLocaleString("en-US");
  const S1 = x => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(1);
  const S0 = x => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(Math.round(x)).toLocaleString("en-US");
  const NOS = ["·", "①", "②", "③", "④", "⑤"];
  // 推送条目归哪一样（和 qx/front.py _pillar_of_item() 一样；测试页、盘中补进来的条目页面自己算）
  const pil = x => { const k = x.kind || String(x.key || "").split(":")[0];
    if (["stage", "line", "term", "small", "ivrv"].includes(k)) return 1;
    if (k === "move") return x.group === "美股保险" ? 1 : x.group === "美元和美债" && /美债/.test(String(x.title || "").split("：").pop().slice(0, 8)) ? 5 : 2;
    if (["trend", "relation", "rel"].includes(k)) return 2;
    if (k === "gamma") return 3;                     // 做市商 gamma 转向：③ 点开第 2 行是做市商（新4 复查改正，和 page_changes() 一样）
    return k === "pm" ? 4 : 0; };
  // 点开：整行（[aria-expanded][aria-controls]）点一下开那一块，再点收；前台一次只开一样（开新的，旧的自动收）
  const ctlOf = t => $(t.getAttribute("aria-controls"));
  function toggle(t, on) {
    const r = ctlOf(t); if (!r) return;
    if (on == null) on = t.getAttribute("aria-expanded") !== "true";
    if (on) for (const o of document.querySelectorAll('[aria-expanded="true"][aria-controls]')) {
      const ro = ctlOf(o); if (o === t || o.closest(".view") || (ro && ro.contains(t))) continue;
      toggle(o, false);
    }
    t.setAttribute("aria-expanded", on ? "true" : "false"); r.hidden = !on;
  }
  document.addEventListener("click", e => {
    const t = e.target.closest && e.target.closest("[aria-expanded][aria-controls]"); if (!t || t.closest(".view")) return;
    const a = e.target.closest("a"); if (a && a !== t && t.contains(a)) return;
    e.preventDefault(); toggle(t);
  });
  document.addEventListener("keydown", e => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const t = e.target; if (!t.matches || !t.matches('[role="button"][aria-expanded][aria-controls]') || t.closest(".view")) return;
    e.preventDefault(); toggle(t);
  });
  // "另有 N 件 / 其余 N 类 / 其余 N 张"：露出同一块里收着的 [data-mr] 行（一次露 data-more 行），露完按钮就不出了
  function moreSync(bl) {
    if (!bl) return;
    const n = bl.querySelectorAll("[data-mr][hidden]").length;
    for (const b of bl.querySelectorAll("[data-more]")) { b.hidden = !n; if (n) b.textContent = b.dataset.tpl.replace("N", n); }
  }
  document.addEventListener("click", e => {
    const b = e.target.closest && e.target.closest("[data-more]"); if (!b) return; e.preventDefault();
    const bl = b.closest("[data-blk]"); if (!bl) return; let n = +b.dataset.more || 99;
    for (const r of bl.querySelectorAll("[data-mr][hidden]")) { if (n-- <= 0) break; r.hidden = false; }
    moreSync(bl);
  });

  (function front() {
    if (FR.err) return;
    const RR = RAW.radar || {}, R = new Map((FR.rows || []).map(r => [r.k, r])), V = FR.five || {};
    const E = FR.emo || {}, K = row(LASTK), K5 = row(Math.max(0, LASTK - 5));
    const li = (lb, t, sm) => t ? `<li>${lb ? `<b>${lb}：</b>` : ""}${sm ? `（${sm}）` : ""}${t}</li>` : "";
    // 点开：最多 5 行 + 1 句"如果……就……"（口径十四.12）；句子从 qx/front.py five_state() 来，节号只在数据里（自测查），页面不写
    const ift = o => { const t = o && o.if && o.if.t, i = t ? t.indexOf("就") : -1;
      return t && t.startsWith("如果") && i > 2 ? `<p class="ift"><b>如果</b>${esc(t.slice(2, i))}<b>就</b>${esc(t.slice(i + 1))}</p>` : ""; };
    // more：不画的行（带 hidden，推送点进来 reveal() 才露），不占 5 行
    const put = (k, rows, more) => { const el = $("xl-" + k); if (!el) return; el.innerHTML = rows.filter(Boolean).slice(0, 5).join("") + (more || []).join("");
      const x = $("x-" + k); if (!x) return; for (const p of x.querySelectorAll(":scope > .ift")) p.remove(); el.insertAdjacentHTML("afterend", ift(V[k])); };
    // 状态词：颜色点 + 字（颜色旁边一定有字）；20 日小线（① 四个数从 RAW.daily，② 半导体收盘从 RAW.chart，⑤ CCC 利差从 five_state）
    const chip = (w, lv) => w ? `<span class="chip ${lv === "red" || lv === "yellow" ? lv : "gray"}" title="${esc(w)}"><i></i><span class="chw">${esc(w)}</span></span>` : "";
    const spark = (vs, w, h, lo, hi) => {
      const xs = (vs || []).map(v => v == null || !isFinite(v) ? null : +v), ok = xs.filter(v => v != null); if (ok.length < 2) return "";
      const a = lo != null ? lo : Math.min(...ok), b = hi != null ? hi : Math.max(...ok), n = xs.length, pts = [];
      xs.forEach((v, i) => { if (v != null) pts.push([1.5 + (w - 3) * i / (n - 1), b === a ? h / 2 : 1.5 + (h - 3) * (b - v) / (b - a)]); });
      const L = pts[pts.length - 1];
      return `<svg class="sp" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")}"/><circle cx="${L[0].toFixed(1)}" cy="${L[1].toFixed(1)}" r="2"/></svg>`; };
    const SOXC = ((RAW.chart || []).find(s => s.k === "SOX") || {}).rows || [];
    const SPK = { price: SOXC.slice(-20).map(r => r[4]), fund: (V.fund || {}).spark };
    // 每样那一行：名字、状态词、一句话、离下一步（qx/front.py page_rows()）；一句话和离下一步在 400 宽各截成 1 行
    for (const k of ["emo", "price", "flow", "expect", "fund"]) {
      const r = R.get(k), t = $("r-" + k); if (!t) continue;
      if (!r) { t.innerHTML = `<div class="rh"><span class="nm">${NOS[["", "emo", "price", "flow", "expect", "fund"].indexOf(k)]} —</span></div><div class="rl"><span class="l1 clip">这次没算出来</span><span class="go" aria-hidden="true">›</span></div>`; continue; }
      let h = `<div class="rh"><span class="nm"><b>${esc(r.no)}</b> ${esc(r.name)}</span><span class="chips">${chip(r.word, r.lv)}${(r.chips || []).map(c => chip(c.w, c.lv)).join("")}</span></div>`;
      const go = `<span class="go" aria-hidden="true">›</span>`;
      if (k === "emo") {
        const rd = E.read || {};
        h += `<div class="tiles">${LN.map(([key, nm]) => `<div class="tile"><span class="tlb">${nm}</span><span class="tvr"><span class="tv num">${LVS(rd[key])}</span>${spark(D[key].slice(-20), 40, 18, 0, 100)}</span></div>`).join("")}</div>` +
          `<p class="scale">0 = 没人怕，100 = 历史上最怕（只量怕，不量热）</p>`;
      }
      const sp = SPK[k] ? spark(SPK[k], 52, 18) : "";
      if (r.line) h += `<div class="rl"><span class="l1 clip">${esc(rwd(r.line))}</span>${sp}${r.next ? "" : go}</div>`;
      if (r.next) h += `<div class="rl"><span class="l2 clip">${esc(r.next)}</span>${go}</div>`;
      t.innerHTML = h;
    }
    // 顶上判断条（只在错的条件第一次出现、要人看的事两个交易日内）：点了开"我的判断"
    const dk = x => x.key && x.date ? ` data-ks="${esc(x.key + "|" + x.date)}"` : "";
    const tl = $("tline"), J = FR.judge || [];
    if (tl && J.length) { tl.hidden = false; tl.innerHTML = J.map(x => `<a class="tg2" href="#v-pd" data-view="pd" data-k="${esc(x.key)}"${dk(x)}>${esc(x.title)} → 我的判断 ›</a>`).join(""); }
    const dy = s => s ? (s.slice(0, 4) === String(FR.asof || "").slice(0, 4) ? D2(s) : `${s.slice(0, 4)} 年 ${D2(s)}`) : "";

    // ① 情绪：四个数一周前到今天（全部历史分位）、保险（近 10 年分位，VIX 只在这里出）、这一段、热的一头、离出清 / 离平稳
    { const rows = [], S = V.emo || {};
      rows.push(li("一周前 → 今天", LN.map(([key, nm]) => `${nm} ${LVS(K5[key])} → ${LVS(K[key])}`).join(" · "), "全部历史分位"));
      // 分位写清基数：opt_market() 是近 10 年（2,520 天）；它没算出来时退回 emotion() 的 VIX，那个分位是全部历史，括号里跟着写全部历史
      const M = FR.optmkt, m10 = !!(M && M.vix);
      rows.push(li("保险", (m10 ? [`VIX ${Number(M.vix.now).toFixed(1)}（${M.vix.p}）`, M.skew ? `SKEW ${M.skew.now}（${M.skew.p}）` : "", M.vvix ? `VVIX ${M.vvix.now}（${M.vvix.p}）` : ""].filter(Boolean).join(" · ")
        : E.vix != null ? `VIX ${E.vix}${E.vix_pct != null ? `（${E.vix_pct}）` : ""}` : "") + (E.t3 != null ? ` · 1 个月 ÷ 3 个月 ${E.t3}${E.t3 >= 1 ? "（倒挂）" : ""}` : ""),
        m10 ? "近 10 年分位" : E.vix_pct != null ? "全部历史分位" : ""));
      if (E.asof) rows.push(li("这一段", E.stage ? `${esc(E.name)}，${D2(E.since)} 起第 ${E.ndays} 个交易日` +
        (E.regime === 2 ? `；板块自己跌，VIX 最高 ${E.vixmax}，没到 30` : E.regime === 1 ? `；宏观冲击，VIX 最高到过 ${E.vixmax}` : "") : "平稳：费城半导体没在跌"));
      if (S.hot_last || S.lead_last) rows.push(li("热的一头", [S.hot_last ? `涨过头最近 ${dy(S.hot_last)}` : "", S.lead_last ? `参与度先走最近 ${dy(S.lead_last)}` : ""].filter(Boolean).join(" · ") +
        ((S.chips || []).some(c => c.w === "涨过头") ? "；今天涨过头" : ""), "只作描述"));
      const s2 = x => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2);
      if (S.out && S.stage !== 3) rows.push(li(`离${esc(S.out.to)}`, `不再亮的话，最早 ${D2(S.out.date)} 收盘`));
      else if (S.ddv != null) rows.push(li("回撤 ÷ 长期波动", `${s2(S.ddv)}，到 −0.3 以下算在跌（收盘算）`));
      put("emo", rows); }

    // ② 价格位置
    { const rows = [], P = FR.pos || [], S = V.price || {};
      const SN = { "^SOX": "半导体", "^NDX": "纳指", "^GSPC": "标普" };
      if (P.length) rows.push(li("离一年高点", P.map(x => `${esc(SN[x.k] || x.name)} ${S1(x.dd)}%${x.below_since ? `（200 日线下第 ${x.below_days} 天）` : ""}`).join(" · ")));
      if (S.m20 != null) rows.push(li("均线", `收盘 ${N0(S.close)} 在 20 日线 ${N0(S.m20)} ${S.close >= S.m20 ? "上" : "下"}，20 日线比 5 天前（${N0(S.m20_5)}）${S.m20 > S.m20_5 ? "高" : S.m20 < S.m20_5 ? "低" : "持平"}` +
        (S.trend ? `；${esc(S.trend)}第 ${S.trend_n} 天` : "")));
      const O = RAW.options, OD = FR.optdate || {}, bet = [];
      for (const sym of ["SMH", "QQQ", "SPY"]) {
        const r = O && (O.rows || []).find(x => x.sym === sym), a = r && (r.ans || []).find(x => /押在哪个价位/.test(x.q));
        const up = a && /上方最大押注 ([\d,.]+)/.exec(a.a), dn = a && /下方最大押注 ([\d,.]+)/.exec(a.a);
        if (up || dn) bet.push(`${sym} ${dn ? dn[1] : "—"}–${up ? up[1] : "—"}`);
      }
      const od = OD.SMH || OD.SPY;
      if (bet.length) rows.push(li("支撑压力", bet.join(" · "), `期权最大押注，45 天内${od ? `，${D2(od.date)} 的链` : ""}`));
      const HL = FR.hl;
      if (K.n20 || HL) rows.push(li("内部", [K.n20 ? `${K.nb20} / ${K.n20} 只在 20 日线下` : "", K.pct50 != null ? `${Math.round(K.pct50)}% 站上 50 日线` : "",
        HL ? `52 周新高减新低 ${HL.net > 0 ? "+" : HL.net < 0 ? "−" : ""}${Math.abs(HL.net)}（${HL.hi} − ${HL.lo}，算了 ${HL.n} 只）` : ""].filter(Boolean).join(" · ")));
      const N = FR.ends;
      if (N) rows.push(li("在交易什么", `${N.main ? `主线 ${esc(N.main.name)}（领跌）· ` : ""}最弱 ${esc(N.lo.name)} · 最强 ${esc(N.hi.name)}`));
      put("price", rows); }

    // ③ 买卖方：趋势基金、做市商、期货持仓（CFTC 和美股期指 TFF 并成一行；CFTC 那期的数只在这里）、保险和散户、杠杆 ETF
    { const rows = [], F = FR.flow, pc = p => `${Math.round(p * 100)}%`;
      const TR = (RR.pos && RR.pos.trend) || [];
      // 趋势基金翻转价（估，简化模型，不进任何规则）：只写半导体一行；纳指、标普的翻转价和三个打分新5 起不画，记在 hidden_draft
      const so = TR.find(x => x.sym === "^SOX");
      if (so && so.flip) rows.push(li("趋势基金翻转价", `半导体 ${N0(so.flip[20])} / ${N0(so.flip[60])} / ${N0(so.flip[120])}`, "估，20 / 60 / 120 日"));
      // 做市商：SPY、QQQ 的 gamma 和翻转价，数取期权块那一句（qx/options.py），写明是哪天的期权链（qx/front.py opt_dates()）
      const O = RAW.options, OD = FR.optdate || {}, gm = [];
      for (const sym of ["SPY", "QQQ"]) {
        const r = O && (O.rows || []).find(x => x.sym === sym), a = r && (r.ans || []).find(x => /做市商/.test(x.q)), s = a && /([正负]) gamma/.exec(a.a);
        if (!s) continue;
        const f = s[1] === "负" ? /涨回 ([\d,.]+) 以上/.exec(a.a) : /跌破 ([\d,.]+) 附近/.exec(a.a);
        gm.push({ sym, s: s[1], f: f && f[1], od: OD[sym] });
      }
      if (gm.length) {
        const g0 = gm[0], one = g => `${g.sym} ${g.s} gamma${g.f ? (g.s === "负" ? `，${g.f} 以上才翻正` : `，跌破 ${g.f} 翻负`) : ""}`;
        const ds = [...new Set(gm.filter(g => g.od).map(g => `${D2(g.od.date)} 的期权链${g.od.lag ? `，晚 ${g.od.lag} 天` : ""}`))];
        rows.push(li("做市商（估）", gm.map((g, i) => i && g.f && g0.f && g.s === g0.s ? `${g.sym} 要 ${g.f}` : one(g)).join("；"),
          (ds.length > 1 ? gm.filter(g => g.od).map(g => `${g.sym} ${D2(g.od.date)}`).join("、") + " 的期权链" : ds[0] || "").replace("的期权链，晚", "的链晚")));
      }
      // 期货持仓：挤着的、这一期变了的（CFTC 那几个读数的历史位置），美股"方向不一致"时写资管、杠杆基金各在哪（TFF，只写有读数在 10% 以外的合约）
      if (F) {
        const ns = F.nums || [], dw = d => d === "有加有减" ? d : `在${d}`;
        const at = m => { const xs = ns.filter(x => x.market === m && x.pos != null); return xs.length ? xs.map(x => `${esc(xs.length > 1 ? x.lab || m : m)} ${pc(x.pos)}`).join("、") : esc(m); };
        const parts = [], by = {};
        for (const x of F.still || []) (by[x.word] = by[x.word] || []).push(x);
        for (const [w, xs] of Object.entries(by)) { const same = xs[0].dir && xs.every(x => x.dir === xs[0].dir);
          parts.push(xs.map(x => at(x.market) + (!same && x.dir ? `（${dw(x.dir)}）` : "")).join("、") + ` ${esc(w.replace("挤在", "挤"))}` + (same ? `，${xs.length > 1 ? "都" : ""}${dw(xs[0].dir)}` : "")); }
        for (const x of F.changed || []) { const p = ns.filter(n => n.market === x.market && n.pos != null);
          parts.push(`${esc(x.market)}${p.length ? " " + p.map(n => pc(n.pos)).join("、") : ""} ${x.runs ? "不再挤" : "新" + esc(x.word)}`); }
        const us = (F.calm || []).find(x => x.market === "美股" && x.word === "方向不一致");
        if (us) { const TF = F.tff || [], cs = [...new Set(TF.map(x => x.code))].map(c => TF.filter(x => x.code === c)).filter(xs => xs.some(x => x.side === "多头" || x.side === "空头"));
          parts.push((cs.length ? cs.map(xs => xs.map((x, j) => `${j ? "" : esc(x.name)}${esc(x.who)} ${x.pos == null ? "—" : pc(x.pos)}`).join("、")).join("；") + "，" : "美股") + "方向不一致"); }
        rows.push(li("期货持仓", parts.join("；") || "没有挤在一边的市场", `CFTC ${D2(F.asof)}，历史位置`));
      }
      if (K.pc != null || K.aaii != null) rows.push(li("保险和散户", [K.pc != null ? `买跌 ÷ 买涨 ${fmt(K.pc, 2)}（平时 ${fmt(K.pcm, 2)}）` : "", K.aaii != null ? `散户多减空 ${sgn(K.aaii, 1)}%（一周前 ${sgn(K.aaiip, 1)}%）` : ""].filter(Boolean).join(" · ")));
      // 杠杆 ETF：SOXL 股数占比（qx/positioning.py letf_readings() 的份额比，口径十四.7 只作对照）；最近一天的净申赎（letf_flow()）连着两个交易日都有份额才算
      const LR = ((RR.pos && RR.pos.readings) || []).find(x => x.src === "Direxion" && /^SOXL 份额/.test(x.name || "")), L = F && F.letf;
      if (LR || L) rows.push(li("杠杆 ETF", [LR ? `SOXL 股数占比 ${LR.value}%（${D2(LR.asof)}${LR.pos == null ? "" : `，历史位置 ${pc(LR.pos)}`}）` : "",
        L ? `${D2(L.day)} 净申赎 ${["soxl", "soxs"].map(k => `${k.toUpperCase()} ${L[k] == null ? "不算" : S1(L[k]) + " 亿美元"}`).join("、")}` +
          (L.net == null ? "" : `，合起来钱往${L.net >= 0 ? "做多" : "做空"}那边 ${Math.abs(L.net).toFixed(1)} 亿${L.pos == null ? "" : `（历史位置 ${pc(L.pos)}）`}`) : ""].filter(Boolean).join("；")));
      put("flow", rows); }

    // ④ 预期（期权五个问题、预测市场照旧放在点开里，第 7 件）；议息会只在这里出
    { const rows = [], M = FR.m1 || [];
      if (M.length) rows.push(li("期权定价接下来一个月", M.map(x => `${esc(x.name)} ±${x.m}%${x.lo != null && x.name === "费城半导体" ? `（${N0(x.lo)}–${N0(x.hi)}）` : ""}`).join(" · "), "只说幅度，不说方向"));
      const F = FR.fomc || [];
      if (F.length) { const none = F.every(x => x.why === "nosave");
        const pr = x => x.hold != null ? `：不变 ${x.hold}%、降息 ${x.cut}%、加息 ${x.hike}%${x.stale ? "（上次取到的）" : x.asof ? `（${D2(x.asof)} 存的）` : ""}`
          : x.why === "nomkt" ? "：预测市场还没有盘口" : x.why === "fail" ? "：预测市场的概率没取到" : none ? "" : "：没存概率";
        rows.push(li("议息会", F.map((x, i) => `${i ? "下下次" : "下次"} ${D2(x.bj)}${pr(x)}`).join("；"), `北京时间${F.some(x => x.hold != null) ? " · Polymarket" : ""}`)); }
      const Rr = FR.react, s2 = x => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2);
      if (Rr) rows.push(li("认不认消息", `${esc(Rr.word)}已报 ${Rr.n} 家，好消息不涨 ${Rr.bad}、坏消息不跌 ${Rr.good}（好消息不涨占 ${Rr.share}%${Rr.past_n ? `，以往 ${Rr.past_n} 季 ${Rr.past_lo}–${Rr.past_hi}%` : ""}）` +
        (Rr.beat_med != null ? `；超预期的 ${Rr.beat_n} 家反应中位数 ${s2(Rr.beat_med)} 个日度波动` : "")));
      put("expect", rows); }

    // ⑤ 基本面：信用分档只在这里（⑤ 的状态词照 5 日走阔，口径十一）；利率和美债波动；生意；三种走向（每个情景一行，最多露 2 行）
    { const rows = [], C = FR.credit || [], Y = FR.y10, SE = FR.season, W = FR.tw, MV = FR.move;
      const w20 = x => x.lvl20 && x.c20 > 0, w5 = x => x.lvl5 && x.up5;
      // 20 日的配对读数（口径十，w20）、到了偏高那一档"历史上百分之几的日子更极端"（w5、x.f5；收着那行已写"到了最极端的 5% / 1%"）新5 起不在这里画，记在 hidden_draft。
      // 这样带一个情景时 ⑤ 点开在 400 宽还在 260 px 以内
      if (C.length) rows.push(li("信用利差", C.map(x => `${esc(x.name)} ${N0(x.now)}（${S0(x.c5)}）`).join(" · "), `基点，FRED ${D2(C[0].date)}，括号里是 5 日走阔`));
      if (Y || MV) rows.push(li("利率", [Y ? `10 年 ${Number(Y.now).toFixed(2)}%，20 日 ${S0(Y.c20)} 基点${Y.date !== FR.asof ? "（" + D2(Y.date) + "）" : ""}` : "", MV ? `MOVE ${Number(MV.now).toFixed(1)}` : ""].filter(Boolean).join(" · ")));
      // 生意：台积电月营收、AI 链超预期几家。财报季已报几家、中位超多少新5 起不在这里画（④"认不认消息"写了已报几家）；
      // AI 账本那个数先不画：账本里排在前面的常是 FRED 的财政部账户、银行准备金，单位写成了"十亿美元"（实际是百万美元，qx/ledger.py），修好以前不露。都记在 hidden_draft
      const biz = [W ? `台积电 ${+W.ym.slice(5)} 月营收同比 ${S1(W.yoy)}%` : "", SE && SE.ai_n ? `AI 链 ${SE.ai_n} 家里 ${SE.ai_beat} 家超预期` : ""].filter(Boolean).join("；");
      if (biz) rows.push(li("生意", biz));
      const SC = (RR.fwd && RR.fwd.scenarios) || [];
      const scl = (S, i) => `<li data-k="scen:${esc(S.id || S.name)}"${i >= 2 ? " hidden" : ""}><b>三种走向：</b>（情景，不是买卖建议）${esc(S.name)}：${(S.ways || []).map(w => `<span data-k="scen:${esc((S.id || S.name) + ":" + (w.id || w.name))}">${esc(w.name)} 亮了 ${w.lit} 个</span>`).join(" · ")}</li>`;
      put("fund", rows.filter(Boolean).concat(SC.slice(0, 2).map(scl)), SC.slice(2).map((S, i) => scl(S, i + 2))); }
  })();
  // 全部（后台）：点"全部 ›"或最下面的按钮打开，跳到那一组
  function openBack(id) {
    const bk = $("back"); if (!bk) return;
    if (bk.hidden) { bk.hidden = false; $("backbtn").hidden = true; dispatchEvent(new Event("resize")); }
    const el = id && $(id); if (el) { if (el.closest("#detail")) openDetail(); el.scrollIntoView({ block: "start" }); }
  }
  // ---------- 说明 / 明细 / 状态（第四轮后台精简第 2 步，方案第四节）
  // 明细在"全部"里面（#detail，同一个加密包），平时收着；说明、状态点了才取 v/<名字>.enc（qx/front.py views() 写好，和 K 线文件同一把钥匙）
  const broken = () => ((RAW.flash && RAW.flash.health) || []).filter(h => !h.ok);     // 快讯停了 / 没取到的路（和 qx/front.py broken_routes() 一样）
  const VIEWS = { shuo: "说明", zt: "状态" }, VST = {};
  function openDetail() {
    const bk = $("back"); if (bk && bk.hidden) openBack(null);
    const d = $("detail"); if (d && d.hidden) { d.hidden = false; dispatchEvent(new Event("resize")); }
    return d;
  }
  async function openView(name, sec) {
    if (name === "detail") { const d = openDetail(); if (d) d.scrollIntoView({ block: "start" }); return; }
    if (name === "pd") { const v = $("v-pd"); if (v) { v.hidden = false; v.scrollIntoView({ block: "start" }); } return; }      // 我的判断：页面里就有（#judge），不用取
    const el = $("v-" + name); if (!el || !VIEWS[name]) return;
    const bar = `<div class="vbar"><h2>${VIEWS[name]}</h2><button type="button" data-vclose="${name}">收起 ×</button></div>`;
    const go = () => ((sec && $(sec)) || el).scrollIntoView({ block: "start" });
    el.hidden = false;
    if (VST[name] === "ok") return go();
    if (VST[name] === "loading") return;
    VST[name] = "loading"; el.innerHTML = bar + `<p class="knote">正在取…</p>`; go();
    try {
      const x = (RAW.vmore || {})[name]; if (!x) throw new Error("这次没生成");
      el.innerHTML = bar + JSON.parse(await fetchEnc("v/" + x.f + "?v=" + x.v)).html;      // 带内容的指纹，旧缓存不会冒充新的
      VST[name] = "ok"; go();
    } catch (err) { VST[name] = null; el.innerHTML = bar + `<p class="knote" style="color:var(--alert)">没取到（${esc(String(err.message || err))}）。</p>`; }
  }
  document.addEventListener("click", e => {
    const c = e.target.closest && e.target.closest("[data-vclose]");
    if (c) { e.preventDefault(); const el = $("v-" + c.dataset.vclose); if (el) el.hidden = true; return; }
    const a = e.target.closest && e.target.closest("[data-view]"); if (a) { e.preventDefault(); openView(a.dataset.view, a.dataset.sec); }
  });
  const vhash = () => { const m = /^#v-(shuo|zt|detail|pd)$/.exec(location.hash); if (m) openView(m[1]); };
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("[data-back]"); if (a) { e.preventDefault(); openBack(a.dataset.back); } });
  if ($("backbtn")) $("backbtn").addEventListener("click", () => openBack("b-emo"));
  if (/^#b-/.test(location.hash)) openBack(location.hash.slice(1));

  // ---------- 今天要知道的（规则在 口径.md 第三节；文字在 qx/watch.py 写好，这里只排版）
  (function today() {
    const T = RAW.today, el = $("today"); if (!T || !el || el.dataset.blk) return;      // 新4：today4() 画（这段留着，见 _impl/design/hidden_draft.md）
    const wk = d => "周" + "日一二三四五六"[new Date(d + "T12:00:00").getDay()];
    const card = x => `<div class="it${x.us ? " us" : ""}" data-k="${esc(x.key + "|" + x.date)}"><div class="it-h"><span>${x.n10 == null ? esc(x.hist || "") : `过去 10 年 ${x.n10 < 1 ? "不到 1" : Math.round(x.n10)} 次`}</span>${x.live ? `<span class="it-tag">${esc(x.state || "盘中")}</span>` : ""}<span>${md(x.date)}</span></div>
      <div class="it-t">${esc(rwd(x.title))}</div>${(x.facts || []).length ? `<ul>${x.facts.map(f => `<li>${esc(rwd(f))}</li>`).join("")}</ul>` : ""}${x.mean ? `<p class="it-m"><b>说明什么：</b>${esc(rwd(x.mean))}</p>` : ""}${(x.news || []).length ? `<div class="nwh">同一时间的新闻（程序按关键词配的，可能不是原因）</div><ul class="nw">${x.news.map(n => `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.t)}</a><small>${esc(n.src)} · ${esc(n.ago)}</small></li>`).join("")}</ul>` : ""}</div>`;
    let html = `<h2>今天变了什么<small>${md(T.asof)} 收盘${T.items.some(x => x.live) ? " · 含盘中" : ""}，过去 10 年次数越少越靠前</small></h2>`;
    const TOP3 = 3;                                   // 第四轮第 2 步：首屏只放最少见的 3 条（规则不变，只改显示）
    html += T.items.length ? T.items.slice(0, TOP3).map(card).join("") + (T.items.length > TOP3 ? `<details><summary>再看 ${T.items.length - TOP3} 条</summary>${T.items.slice(TOP3).map(card).join("")}</details>` : "") : `<div class="quiet">今天没有值得看的变化。</div>`;
    const n48 = $("n48");                             // 第四轮第 2 步：接下来 48 小时放在 K 线后面
    const FR = RAW.front || {}, H48 = FR.h48all || FR.h48 || [];       // h48all：另加褐皮书（旧列表一直列着，前台那一行不列）
    const late = FR.cal_late ? `；日历是 ${md(FR.cal_late)}取的，以前的日历没存，截到以前的日子列的不是那天的事` : "";
    if (n48 && H48.length) n48.innerHTML = `<ul class="up"><b>接下来 48 小时（两个交易日，北京时间${late}）</b>${H48.map(d => d.items.map(x => `<li>${esc(d.day)} ${esc(x.at)} · ${esc(x.text)}</li>`).join("")).join("")}</ul>`;
    if ((T.recent || []).length) html += `<details><summary>前几天说过的（${T.recent.length} 条）</summary>${T.recent.map(card).join("")}</details>`;
    if ((T.trends || []).length) {
      const c = (w, n, u) => w ? `<td class="${w === "上行" ? "s-up" : w === "下行" ? "s-dn" : ""}">${w} ${n} ${u}</td>` : "<td>—</td>";
      html += `<details><summary>所有品种的趋势状态（日 / 周 / 月）</summary><p class="vlink">上行、下行、震荡怎么定：<a href="#v-shuo" data-view="shuo" data-sec="s-trend">说明 ›</a></p><table class="tbl tr"><tr><th>品种</th><th>日线</th><th>周线</th><th>月线</th></tr>${T.trends.map(r => `<tr><td>${esc(r.name)}</td>${c(r.d, r.dn, "天")}${c(r.w, r.wn, "周")}${c(r.m, r.mn, "个月")}</tr>`).join("")}</table></details>`;
    }
    el.innerHTML = html;
  })();

  // ---------- 今天变了什么（新4，qx/front.py page_changes()）：推送条目和五样的触发行合成一张单子，每行标归哪一样；露 2 行，另有的收在按钮里
  // 前几天说过的、不归哪一样的不画（节点在，推送点开会露出来）；盘中、测试页补进来的条目照 RAW.today 现排
  (function today4() {
    const T = RAW.today || {}, el = $("today"); if (!el || !el.dataset.blk) return;
    const CH = FR.changes || [], by = new Map(CH.filter(c => c.key).map(c => [c.key + "|" + c.date, c]));
    const rows = [];
    for (const x of T.items || []) { if (x.kind === "judge") continue;
      const c = by.get(x.key + "|" + x.date); rows.push({ p: c ? c.p : pil(x), hide: c ? !!c.hide : false, k: x.key + "|" + x.date, t: x.title, live: x.live }); }
    for (const c of CH) if (c.src !== "today" && c.src !== "recent")
      rows.push({ p: c.p, hide: !!c.hide, k: c.key || "", ks: c.key && c.date && !/\s/.test(c.key) ? c.key + "|" + c.date : "", t: c.title });
    for (const x of T.recent || []) { const c = by.get(x.key + "|" + x.date);
      rows.push({ p: c ? c.p : pil(x), hide: true, k: x.key + "|" + x.date, t: `${D2(x.date)} 的 ${x.title}` }); }
    const vis = rows.filter(r => !r.hide), hid = rows.filter(r => r.hide), SHOW = 2, MORE = 10;
    // 第 13 件以后（data-xr）："另有 N 件"不露（最多再露 10 件），节点在；推送点到那一件、每日汇总点进来才露
    const one = (r, i) => `<div class="ti"${r.k ? ` data-k="${esc(r.k)}"` : ""}${r.ks ? ` data-ks="${esc(r.ks)}"` : ""}${i < 0 ? " hidden" : i >= SHOW + MORE ? " data-xr hidden" : i >= SHOW ? " data-mr hidden" : ""}><b class="bn">${NOS[r.p] || "·"}</b><span class="tt"><span class="kt">${esc(rwd(r.t))}</span></span></div>`;
    // #dg：每日汇总（digest:）点进来才出，在行的上面（plan 第三节第 5 小节），字在 jumpK 里按推送标题写
    el.innerHTML = `<div class="bh"><h2>今天变了什么</h2><span class="meta">${D2(T.asof || RAW.asof)} 收盘${(T.items || []).some(x => x.live) ? " · 含盘中" : ""}</span></div>` +
      `<p class="dg" id="dg" hidden></p>` +
      (vis.length ? "" : `<p class="quiet">今天没有值得看的变化。</p>`) + vis.map(one).join("") + hid.map(r => one(r, -1)).join("") +
      `<button type="button" class="more" data-more="99" data-tpl="另有 N 件 ›" hidden></button>`;
    moreSync(el);
  })();

  // ---------- 接下来 5 个交易日（新4，qx/front.py page_next5()；北京时间）
  (function cal4() {
    const el = $("cal"), N5 = FR.next5 || []; if (!el) return;
    if (!N5.length && !FR.later) { el.hidden = true; return; }
    const none = N5.length && N5.every(x => x.text === "—");
    el.innerHTML = `<div class="bh"><h2>接下来 5 个交易日</h2><span class="meta">北京时间${FR.cal_late ? ` · 日历是 ${D2(FR.cal_late)} 取的` : ""}</span></div>` +
      N5.map(x => `<div class="cr"><span class="cdt num">${esc(x.md)}</span><span class="cwd">${esc(x.wd)}</span><span class="ct">${esc(x.text)}</span></div>`).join("") +
      (FR.later ? `<div class="cr later"><span class="cdt">再往后</span><span class="ct">${esc(FR.later)}</span></div>` : "") +
      (none ? `<p class="knote">这几天的日历没存下来，只列得出日子。</p>` : "");
  })();

  // ---------- 期权：五个问题（规则在 口径.md 第四节；白话在 qx/options.py 写好）
  (function opt() {
    const O = RAW.options, el = $("opt"); if (!O || !el || !(O.rows || []).length) return;
    // 大盘那一行：数从 qx/front.py opt_market() 来（和 options.py 同一个 10 年分位），写"10 年分位 N"，不写"偏高 / 少见"
    // 数在后台已经按要写的位数取过整（只取一次），这里不再取整；VIX 补齐一位小数（20 写成 20.0，和 market() 那句一样，不改数）
    // 拿不到时用 options.py market() 那句，但把没登记的 95 / 70 / 30 那几个词（少见地高 / 偏高 / 偏低 / 平常）换成"10 年分位没算出来"，和正常那条同一个位置
    // （新5 起 p10、nowd 这两个不再画，代码照"不删代码"留着；放回见 _impl 的不再显示清单）
    const M = RAW.front && RAW.front.optmkt, p10 = x => `10 年分位 ${x.p}`;
    const nowd = String(O.market || "").replace(/（(?:10 年里少见地高|偏高|偏低|平常)）/g, "（10 年分位没算出来）").replace(/，(?:10 年里少见地高|偏高|偏低|平常)）/g, "，10 年分位没算出来）");
    // 做市商 gamma、最大押注写明用的是哪天的期权链、比数据日晚几个交易日（qx/front.py opt_dates()，新3）
    const OD = (RAW.front && RAW.front.optdate) || {}, d2 = s => s ? `${+s.slice(5, 7)}/${+s.slice(8, 10)}` : "";
    const chainOf = x => x ? `（${d2(x.date)} 的期权链${x.lag ? `，晚 ${x.lag} 天` : ""}）` : "", CQ = /做市商|押在哪个价位/;
    const ods = ["SPY", "SMH"].map(k => OD[k]).filter(Boolean), sumc = ods.length && ods.every(x => x.date === ods[0].date && x.lag === ods[0].lag) ? chainOf(ods[0]) : "";
    // 新5 一件事一个家：VIX、SKEW、VVIX 只在 ① 点开"保险"那一行（近 10 年分位），这里只留 9 天比 30 天；opt_market() 没算出来时这一行不出（market() 那句也带 VIX）
    const mk = M && M.r9 != null ? `9 天保险是 30 天的 ${M.r9}%${M.r9_ge1 ? "：眼前几天有事" : ""}。` : "";
    el.innerHTML = `<summary>期权：五个问题<small>${esc((O.summary || "").replace(/、一个月定价 ±\d+%/g, ""))}${O.summary ? sumc : ""}</small></summary>
      ${mk ? `<p>大盘：${esc(mk)}</p>` : ""}
      <div class="oq">${O.rows.map(r => `<div class="oc"><h4>${esc(r.name)}<small>${r.live ? "盘中 · 延迟 15 分钟" : md(r.date || RAW.asof) + " 收盘"}</small></h4>${r.ans.map(a => `<div class="oa${a.warn ? " w" : ""}"><b>${esc(a.q)}</b>：${esc(a.a)}${CQ.test(a.q) ? chainOf(OD[r.sym]) : ""}</div>`).join("")}</div>`).join("")}</div>
      <p class="vlink">这五个问题是什么意思：<a href="#v-shuo" data-view="shuo" data-sec="s-opt">说明 ›</a></p>
      <p class="knote">期权链是 CBOE 延迟 15 分钟的报价，从 2026-10-19 起每天攒，现在 ${O.days} 天；攒满 250 个交易日以后才和历史比。K 线上 SMH、英伟达、美光、台积电标了做市商 gamma 转负 / 转正的日子。</p>`;
  })();

  // ---------- 我的判断（第 3 块；规则在 口径.md 第六节，卡片原文加密存放）
  (function judge() {
    const J = RAW.judge || [], el = $("judge"); if (!el) return;
    if (!J.length) { el.innerHTML = `<p class="quiet">现在没有登记的判断。</p>`; return; }
    const cls = s => s === "支持" ? "s-for" : s === "反对" ? "s-against" : "s-mid";
    el.innerHTML = J.map(e => `<div class="jc">
      <div class="jt">${esc(e.title)}</div>
      <div class="jm">${md(e.made)} 提出 · ${e.expired ? "已到期，待复盘" : "还剩 " + e.left + " 天（到 " + md(e.end) + "）"} · ${esc(e.ref_name)}自那以来 ${sgn(e.chg, 1)}%（最多 ${sgn(e.mdd, 1)}%）</div>
      <p style="margin:0 0 6px;font-size:14px"><b>最弱的一环：</b>${e.weakest.length ? e.weakest.map(esc).join("、") : "现在没有反对的"}</p>
      ${e.links.map(L => `<div class="jl"><span>${esc(L.name)}</span><span class="st ${cls(L.status)}">${L.status}</span><span class="fx">程序今天读到：${esc(L.fact)}</span>
        <details><summary>证据和反证</summary>${L.con.length ? `<b>反对的：</b><ul>${L.con.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}${L.pro.length ? `<b>支持的：</b><ul>${L.pro.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}${L.note ? `<p style="margin:2px 0">${esc(L.note)}</p>` : ""}</details></div>`).join("")}
      <div style="border-top:1px solid var(--line);margin-top:6px;padding-top:6px"><b style="font-size:14px">什么情况算你错了</b>${e.wrong.map(w => `<div class="jw"><b style="color:${w.state === "出现了" ? "var(--alert)" : "var(--ink-3)"}">${esc(w.state)}</b> · ${esc(w.text)}<span style="color:var(--ink-3)">（${esc(w.detail || "")}）</span></div>`).join("")}</div>
      ${e.why ? `<p class="knote" style="margin-top:6px">当时的想法：${esc(e.why)}</p>` : ""}${e.review ? `<p class="kpins"><b>复盘：</b>${esc(e.review)}</p>` : ""}
    </div>`).join("") + `<p class="knote">支持 / 中性 / 反对是程序每天按事先写好的规则读的；证据和反证是 AI 在对话里写的，反证放在前面。某一环变了、错的条件出现了，会进"今天要知道的"。K 线上标了提出判断的那天。</p>`;
  })();

  // ---------- 试用记录（两周）：看了哪几块、帮上没有；发到 ntfy 的另一个频道，云端取回来加密存（qx/notify.py）
  (function trial() {
    const el = $("trial"); if (!el || !RAW.fb) return;
    const day = new Date().toISOString().slice(0, 10), K = "qx-trial-" + day;
    let done = false; try { done = !!localStorage.getItem(K); } catch (e) {}
    const blocks = ["今天要知道的", "情绪阶段", "K 线", "我的判断", "期权", "预测市场", "新闻和日历"];
    el.hidden = false;
    el.innerHTML = `<h3>试用记录（每天点一下，两周后看哪块真有用）</h3><p style="margin:0;color:var(--ink-2);font-size:13px">${done ? "今天已经记过了，再记一次也行。" : "今天看了哪几块？帮上了吗？"}</p>
      <div class="row">${blocks.map(b => `<label><input type="checkbox" value="${b}">${b}</label>`).join("")}</div>
      <div class="row">${["帮上了", "有一点", "没帮上"].map(u => `<label><input type="radio" name="tu" value="${u}">${u}</label>`).join("")}</div>
      <textarea id="tnote" placeholder="一句话（可以不写）：比如哪条提醒让你做了什么，或者哪里没用"></textarea>
      <button type="button" id="tsend">记下</button> <span id="tmsg" style="font-size:13px;color:var(--ink-3)"></span>`;
    $("tsend").addEventListener("click", async () => {
      const seen = [...el.querySelectorAll("input[type=checkbox]:checked")].map(x => x.value), u = el.querySelector("input[name=tu]:checked");
      const body = JSON.stringify({ day, seen, useful: u ? u.value : "", note: $("tnote").value.trim() });
      $("tmsg").textContent = "正在记…";
      try { const r = await fetch("https://ntfy.sh/" + RAW.fb, { method: "POST", body }); if (!r.ok) throw 0; try { localStorage.setItem(K, "1"); } catch (e) {} $("tmsg").textContent = "记下了，云端下一次运行会取回去。"; }
      catch (e) { $("tmsg").textContent = "没发出去，过一会再试。"; }
    });
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
    const N = H.news || {}, C = (H.calendar || []).concat((RAW.front && RAW.front.cal_add) || []);   // cal_add：纳斯达克漏了的非农，BLS 发布日表补的（qx/front.py nfp_add()，新3）
    const li = n => `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.t)}</a><small>${esc(n.topic ? n.topic + " · " : "")}${esc(n.src)} · ${esc(n.ago)}${n.k > 1 ? ` · ${n.k} 家报道` : ""}</small></li>`;
    if (nw.closest("[data-blk]")) {          // 新4："发生了什么"里的要闻按钮，点开是前 5 条；7 天日历、更多新闻不画（代码留着，_impl/design/hidden_draft.md）
      const top = (N.top || []).slice(0, 5), b = $("newsb");
      if (top.length && b) { b.textContent = `要闻 ${top.length} 条 ›`; b.hidden = false;
        nw.innerHTML = `<ul class="nw">${top.map(li).join("")}</ul><p class="vlink">新闻从哪几家取：<a href="#v-shuo" data-view="shuo" data-sec="s-news">说明 ›</a></p>`; }
      return;
    }
    const what = e => e.kind === "earnings" ? `${esc(e.name || e.sym)} 财报` : esc(e.title);
    const extra = e => { const a = [];
      if (e.pm) a.push(`Polymarket：不变 ${pct(e.pm.hold)} · 降息 ${pct(e.pm.cut)} · 加息 ${pct(e.pm.hike)}${e.pm.stale ? "（上次的）" : ""}`);
      if ((e.implied || []).length) a.push(e.implied[0].ev ? `期权算的财报这一下：一半机会超过 ±${(e.implied[0].move * 100).toFixed(1)}%`
                                          : "期权定价：" + e.implied.map(x => `${x.sym} ±${(x.move * 100).toFixed(1)}%（到 ${x.exp}）`).join("、"));
      if (e.kind === "macro" && e.note) a.push(esc(e.note));
      return a.length ? `<small>${a.join("；")}</small>` : ""; };
    const short = n => String(n || "").replace(/,? (Inc\.?|Corp(oration)?\.?|Holdings?.*|N\.V\.|plc|PLC|Ltd\.?|Limited|Company.*|Technology.*|Incorporated|Co\.?)$/,"").replace(/,$/, "");
    const FB = (RAW.front && RAW.front.fed_bj) || {}, late = RAW.front && RAW.front.cal_late;
    function calRows(C) {           // 同一天的财报合成一行；其他事件一件一行
      const days = [...new Set(C.map(e => e.date))], out = [];
      for (const d of days) {
        const ev = C.filter(e => e.date === d), er = ev.filter(e => e.kind === "earnings");
        // 议息会（决议、记者会）写北京时间，和前台议息会那一行、48 小时、时间轴一致（qx/front.py fed_bj()）；别的事件照日历写美东
        // 按写出来的那天排（决议在北京是第二天凌晨，排在美东当天的财报后面）
        const when = e => { const b = FB[e.kind + "|" + e.date]; return b ? [b.bj, `${md(b.bj)} ${wk(b.bj)}<small>${esc(b.hm)} 北京时间</small>`] : [d, `${md(d)} ${wk(d)}<small>${esc(e.time || "")}</small>`]; };
        for (const e of ev.filter(e => e.kind !== "earnings")) { const [k, w] = when(e); out.push([k, `<tr><td class="d">${w}</td><td>${what(e)}${extra(e)}</td></tr>`]); }
        if (er.length) out.push([d, `<tr><td class="d">${md(d)} ${wk(d)}</td><td>财报：${er.map(e => `${esc(short(e.name || e.sym))}<span style="color:var(--ink-3)">（${esc(e.time)}${(e.implied || []).length ? "，期权：一半机会超过 ±" + (e.implied[0].move * 100).toFixed(1) + "%" : ""}）</span>`).join("、")}</td></tr>`]);
      }
      return out.map((x, i) => [x, i]).sort((a, b) => a[0][0] < b[0][0] ? -1 : a[0][0] > b[0][0] ? 1 : a[1] - b[1]).map(x => x[0][1]).join("");
    }
    nw.innerHTML = `<h2>新闻和日历</h2>` +
      (N.top && N.top.length ? `<ul class="nw">${N.top.map(li).join("")}</ul>` : `<p class="quiet">最近 24 小时没有和美股有关的要闻。</p>`) +
      (C.length ? `<h3 style="font-size:15px;margin:16px 0 4px">接下来 7 天${late ? `<small>　日历是 ${md(late)}取的，不是这天的</small>` : ""}</h3><table class="tbl cal">${calRows(C)}</table>` : "") +
      ((N.more || []).length ? `<details><summary>更多新闻（按话题）</summary>${N.more.map(g => `<p style="margin:10px 0 2px"><b>${esc(g.topic)}</b></p><ul class="nw">${g.items.map(li).join("")}</ul>`).join("")}</details>` : "") +
      `<p class="vlink">新闻从哪几家取、日历里的期权幅度怎么算：<a href="#v-shuo" data-view="shuo" data-sec="s-news">说明 ›</a></p>`;
  })();

  for (const id of ["opt", "pm"]) { const d = $(id); if (d && !d.innerHTML.trim()) d.hidden = true; }      // ④ 点开里：这天没有期权、预测市场就不出空的折叠

  // ---------- 雷达（第四轮第 2 步）：顶栏时点、市场在交易什么、各市场一行；有 Worker 时每 60 秒现取价格（/live）
  const RD = RAW.radar || {};
  const bj = ms => new Date(ms + 8 * 3600e3).toISOString().slice(11, 16);
  const bjd = ms => { const s = new Date(ms + 8 * 3600e3).toISOString(); return `${+s.slice(5, 7)}/${+s.slice(8, 10)} ${s.slice(11, 16)}`; };
  let LIVE = null, LIVE_ERR = null;
  // 24 小时内推过的（口径十四.11）：Worker 的推送记录（/live 带回，公开的快讯、涨跌才带标题）和 Worker 连不上时云端直接发的记录（RD.pushed），按编号去重；
  // 没带标题的用页面上那一条的字
  function pushed() {
    const cut = Date.now() - 24 * 3600e3, by = new Map();
    for (const x of [].concat((LIVE && LIVE.pushed) || [], RD.pushed || [])) if (x && x.key && x.at > cut && !(by.has(x.key) && by.get(x.key).title)) by.set(x.key, x);
    return [...by.values()].sort((a, b) => b.at - a.at);
  }
  const TODAY_KINDS = ["stage", "line", "term", "trend", "rel", "small", "ivrv", "gamma", "pm"];
  function pushCat(k) {           // 页面上已经没有那一条的写类别（口径十四.11）
    const p = k.split(/[:|]/)[0];
    if (/^c[1-6]$/.test(p)) return "机会和风险卡";
    if (p === "move") return /:live\|/.test(k) ? "盘中少见的涨跌" : "今天变了什么";
    if (TODAY_KINDS.includes(p)) return "今天变了什么";
    return { selftest: "雷达 · 自检没过", stale: "雷达 · 数据没更新", digest: "没推的几件（合成一条）", first: "快讯：第一次", spread: "快讯：几家同时报道", judge: "我的判断", scen: "三种走向" }[p] || "推送";
  }
  function pushTitle(x) {
    if (x.title) return x.title;
    const el = findK(x.key), t = el && (el.matches(".trg") ? el.firstChild : el.querySelector(".kt, .it-t, summary b, a") || el);   // .kt：改成表格行以后的标题格
    if (t && t.textContent.trim()) return t.textContent.trim().slice(0, 80);
    return pushCat(x.key);
  }
  // 推送点开跳到那一条（#k=编号）：带 data-k / data-ks 的元素。按 原编号 → 加 card: 找；同一个编号前台有的先跳前台（不在点开里的），
  // 再点开里的，同一档取页面上最前面的；不去掉日期找（会跳到后来另一天同一类的那一条）
  function findK(k) {
    const q = x => `[data-k="${CSS.escape(x)}"],[data-ks~="${CSS.escape(x)}"]`;
    const ctl = new Set([...document.querySelectorAll("[aria-controls]")].map(t => t.getAttribute("aria-controls")).filter(Boolean));
    const at = e => { if (e.closest("#back,.xp,[data-xp]")) return 1; for (let p = e; p; p = p.parentElement) if (p.id && ctl.has(p.id)) return 1; return 0; };
    for (const x of [k, "card:" + k]) {
      const els = [...document.querySelectorAll(q(x))].filter(e => !e.closest(".view"));
      if (els.length) return els.reduce((a, b) => at(b) < at(a) ? b : a);
    }
    return null;
  }
  // 露出一个元素：一路往上，收着的点开（整行）打开、hidden 去掉、折叠打开；"其余 / 另有 N"的按钮跟着改数
  function reveal(el) {
    const tg = new Map([...document.querySelectorAll("[aria-expanded][aria-controls]")].filter(t => !t.closest(".view")).map(t => [t.getAttribute("aria-controls"), t]));
    const bls = [];
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      if (p.classList.contains("view")) break;
      const t = p.id && tg.get(p.id); if (t && t.getAttribute("aria-expanded") !== "true") toggle(t, true);
      if (p.hidden) p.hidden = false;
      if (p.tagName === "DETAILS" && p !== el) p.open = true;
      if (p.dataset && p.dataset.blk) bls.push(p);
    }
    bls.forEach(moreSync);
  }
  let HITT = 0;
  function hitEl(els) {
    els = [].concat(els).filter(Boolean); if (!els.length) return;
    els.forEach(reveal);
    document.querySelectorAll(".hit").forEach(x => x.classList.remove("hit"));
    els.forEach(x => x.classList.add("hit"));
    clearTimeout(HITT); HITT = setTimeout(() => els.forEach(x => x.classList.remove("hit")), 6000);
    els[0].scrollIntoView({ block: "center" });                                   // 先滚一次（页面在后台时 rAF 不跑）
    requestAnimationFrame(() => els[0].scrollIntoView({ block: "center" }));      // 排版定了再滚一次
  }
  const upd = () => { const m = /(\d{4})-(\d\d)-(\d\d)[ T](\d\d:\d\d)/.exec(RAW.updated || ""); return m ? `${+m[2]}/${+m[3]} ${m[4]}` : String(RAW.updated || ""); };
  // 自测没过 / 数据没更新：顶上红字写这页是什么时候生成的、数据到哪天
  function sysl(k, p) {
    const s = $("sysl"); if (!s) return null;
    const d = (k.split("|")[1] || "").trim();
    s.innerHTML = (p === "selftest" ? `这页是 ${esc(upd())} 生成的（数据到 ${D2(RAW.asof)} 收盘）；${d ? D2(d) + " " : ""}那次自测没过，网页没更新。`
      : `这页的数据到 ${D2(RAW.asof)} 收盘（${esc(upd())} 生成）；推送说最近一个交易日的数据还没来。`) + `<a href="#v-zt" data-view="zt">状态 ›</a>`;
    s.hidden = false; return s;
  }
  function jumpK() {
    const m = /^#k=(.+)$/.exec(location.hash); if (!m) return;
    let k; try { k = decodeURIComponent(m[1]); } catch (e) { return; }
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}   // 刷新不再跳
    const g = $("gone"); if (g) g.hidden = true;
    const p = k.split(/[:|]/)[0], all = x => [...document.querySelectorAll(`[data-k="${CSS.escape(x)}"],[data-ks~="${CSS.escape(x)}"]`)].filter(e => !e.closest(".view"));
    if (p === "digest") {                               // 每日汇总：今天变了什么里今天的全露出来（"另有 N 件"打开，第 13 件以后也露；前几天说过的不露），上面加一行灰字说没推的几件在哪
      const tb = $("today"); if (!tb) return;
      tb.querySelectorAll("[data-mr][hidden],[data-xr][hidden]").forEach(x => { x.hidden = false; }); moreSync(tb);
      const dg = $("dg"), x = pushed().find(y => y.key === k);
      if (dg) { dg.textContent = `"${(x && x.title) || "没推的几件"}"的标题在推送正文里；页面上还在的，都在下面和"机会和风险"里。`; dg.hidden = false; }
      return hitEl(dg || tb);
    }
    if (p === "selftest" || p === "stale") return hitEl(sysl(k, p));
    if (p === "scen") {                                 // 三种走向：编号 → 情景:走向 → 情景，取页面上最先有的那一级
      const [, S, W] = k.split(":");
      for (const x of [k, `scen:${S}:${W}`, `scen:${S}`]) { const els = all(x); if (els.length) return hitEl(els[0]); }
    }
    const el = findK(k);
    if (el) return hitEl(el);
    const mv = /^move:([^|]*):live\|/.exec(k);          // 盘中涨跌：页面上没有那一条时落到各市场里那一组的行（没有就落到各市场）
    if (mv) { const rows = mv[1] ? [...document.querySelectorAll(`[data-mk~="${CSS.escape(mv[1])}"]`)].filter(e => !e.closest(".view")) : []; return hitEl(rows.length ? rows : $("mkts")); }
    if (p === "first" || p === "spread") { const f = $("flash"); return hitEl(f && !f.hidden ? f : $("happen")); }
    if (p === "judge") return openView("pd");
    const x = pushed().find(y => y.key === k);            // 页面上已经没有那一条：顶上写一行（口径十四.11）
    if (g) { g.textContent = `这条说的事已经不在页面上了：${(x && x.title) || pushCat(k)}`; hitEl(g); }
  }
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("[data-pushl]"); if (!a) return; e.preventDefault();
    const el = $("pushl"); if (!el) return;
    el.hidden = !el.hidden; if (el.hidden) return;
    const pu = pushed();
    el.innerHTML = (pu.length ? pu.map(x => `<a href="#k=${encodeURIComponent(x.key)}">${bj(x.at)} · ${esc(pushTitle(x))}</a>`).join("") : `<p class="knote">24 小时内没有推送。</p>`) +
      `<p class="knote">北京时间。点一条跳到页面上那一条；合并成一条推的（"今天要知道的 N 件""新卡 N 张"）跳到第一件。</p>`; });
  function zword(z) { const a = Math.abs(z); return z == null ? "—" : (z < 0 ? "−" : "+") + a.toFixed(1); }
  function times() {
    const el = $("times"); if (!el) return;
    const age = Math.max(0, Math.round((Date.now() - (RD.built || Date.now())) / 60e3));
    const ago = age < 1 ? "刚刚" : age < 60 ? age + " 分钟前" : age < 1440 ? Math.floor(age / 60) + " 小时前" : Math.floor(age / 1440) + " 天前";
    const nb = broken().length;
    // 顶条（新4）：生成时刻 · 状态多久前 | 推送记录；数据各到哪天；有路断了另起一行红字
    let h = `<div class="tb1"><span>${bjd(RD.built || Date.now())} · <span class="${age > 40 ? "stale" : "ok"}">状态 ${ago}</span></span><a href="#" data-pushl>推送记录 ›</a></div>`;
    const as = [`美股到 ${D2(RAW.asof)} 收盘`];
    if ((FR.credit || []).length) as.push(`利差到 ${D2(FR.credit[0].date)}`);
    if (FR.flow) as.push(`CFTC ${D2(FR.flow.asof)} 那期`);
    if (LIVE && LIVE.prices) {
      const P = LIVE.prices.p || {}, by = {};
      for (const r of RD.mkts || []) for (const x of r.items) { const q = P[x.s]; if (q && q.at && r.open) by[r.market] = Math.max(by[r.market] || 0, q.at * 1000); }
      const ps = Object.entries(by).map(([m, t]) => `${esc(m)} 截至 ${bj(t)}${Date.now() - t > 30 * 60e3 ? "" : `，延迟约 ${Math.max(0, Math.round((Date.now() - t) / 60e3))} 分钟`}`);
      if (ps.length) as.push("价格 " + ps.join("；"));
    } else if (RD.live) as.push(`<span class="stale">实时价格取不到${LIVE_ERR ? "（" + esc(LIVE_ERR) + "）" : ""}，显示的是 15 分钟一次的状态</span>`);
    h += `<div class="tb2">${as.join(" · ")}</div>`;
    if (nb) h += `<div class="tb3"><a href="#v-zt" class="bad" data-view="zt" data-sec="z-flash">⚠ ${nb} 条路断了 ›</a></div>`;
    el.innerHTML = h;
  }
  (function narr() {
    const N = RD.narr, el = $("narr"); if (!N || !el) return;
    el.hidden = false;
    const B = N.baskets || [];
    const pairTxt = p => `${esc(p.name)} 20 日${p.bp ? (p.chg >= 0 ? "升了 " : "降了 ") + Math.abs(p.chg).toFixed(0) + " 个基点" : (p.chg >= 0 ? "涨了 " : "跌了 ") + Math.abs((Math.exp(p.chg) - 1) * 100).toFixed(1) + "%"}，历史上 ${Math.max(0.1, p.frac * 100).toFixed(p.frac < 0.1 ? 1 : 0)}% 的日子更极端`;
    let h = `<h2>市场在交易什么<small>截至 ${md(N.asof)} 收盘 · 规则算出来的，不是人定的</small></h2>`;
    if (N.main) h += `<div class="nr"><div class="nh">主线：${esc(N.main.name)} ↓</div><div>领跌，20 日按长期波动折算 ${zword(N.main.z)}；${pairTxt(N.main.pair)}</div><div class="ns">结束信号（登记时写好）：${esc(N.main.end)}</div></div>`;
    else { const L = B.find(b => b.id === N.lead); h += `<div class="nr"><div class="nh">没有认出主线</div><div>${L ? `领跌的是${esc(L.name)}（${zword(L.z)}），但配对的读数${L.pairs.length ? L.pairs.map(p => `${esc(p.name)}历史上 ${fr(p.frac)} 的日子更极端`).join("、") : "取不到"}，不够两样都满足。` : "数据不够。"}</div></div>`; }
    h += `<details><summary>哪个篮子在带着跌（20 日涨跌按各自长期波动折算，${B.length} 个篮子）</summary><table class="nbk">${B.map(b => `<tr><td>${esc(b.name)}<small>${Object.entries(b.members).map(([m, z]) => esc((b.names || {})[m] || m) + " " + zword(z)).join(" · ")}${b.n < b.of ? ` · 缺 ${b.of - b.n} 只` : ""}</small>${b.pairs.map(p => `<small>${pairTxt(p)}</small>`).join("")}</td><td class="z">${zword(b.z)}${b.same == null ? "" : `<small>${b.same ? "和" : "和"}${b.vs === "^SOX" ? "费城半导体" : "标普"}${b.same ? "同向" : "反向"}</small>`}</td></tr>`).join("")}</table></details>`;
    const H = N.heat || {};
    h += `<details><summary>主题热度（只作描述）</summary>${(H.rows || []).length ? `<table class="nbk">${H.rows.map(r => `<tr><td>${esc(r.topic)}<small>最近 5 天 ${r.n5} 条，前 60 天日均 ${r.base}${r.capped ? `，${r.capped} 天封顶不算` : ""}</small></td><td class="z">${r.ratio.toFixed(2)} 倍</td></tr>`).join("")}</table>` : `<p class="knote">${esc(H.note || "")}</p>`}<p class="knote">${esc(H.note && (H.rows || []).length ? H.note : "")}</p></details>`;
    el.innerHTML = h;
  })();
  // 各市场（新4）：每类一行，写这一类今天动得最不寻常的那个（qx/front.py page_mk()），类按"今天涨跌 ÷ 平常一天"排；露 3 行，其余收在按钮里
  // 每行 data-mk：类名（去空格）、属于哪几组（RAW.mkmap，推送的盘中涨跌按组）、这一类的全部代码；盘中现取价格到了只改数字
  function mkts() {
    const M = RD.mkts, el = $("mkts"); if (!M || !el) return;
    const P = (LIVE && LIVE.prices && LIVE.prices.p) || {};
    const chg = x => { const q = P[x.s]; return q && q.pc ? (x.bp ? (q.p - q.pc) * 100 : Math.log(q.p / q.pc)) : x.chg; };
    const txt = (x, ch) => ch == null || !isFinite(ch) ? "—" : x.bp ? (ch >= 0 ? "+" : "−") + Math.abs(ch).toFixed(0) + " 基点" : pctP((Math.exp(ch) - 1) * 100);
    if (el.dataset.done) {
      for (const b of el.querySelectorAll("[data-s]")) { const x = JSON.parse(b.dataset.x), ch = chg(x); b.textContent = txt(x, ch); b.className = ch == null ? "" : ch >= 0 ? "pos" : "neg"; }
      return;
    }
    const byCls = new Map(M.map(r => [r.cls, r])), MAP = RAW.mkmap || {};
    let top = (FR.mk || []).filter(x => byCls.has(x.cls));
    if (!top.length) top = M.map(r => { const it = r.items.find(x => x.z != null) || r.items[0]; return it ? Object.assign({ cls: r.cls }, it) : null; }).filter(Boolean)
      .sort((a, b) => Math.abs(b.z || 0) - Math.abs(a.z || 0));
    const SHOW = 3;
    const rowH = (x, i) => { const r = byCls.get(x.cls), grp = Object.keys(MAP).filter(g => (MAP[g] || []).includes(x.cls));
      const tok = [x.cls.replace(/\s+/g, ""), ...grp, ...r.items.map(y => y.s)].filter(Boolean).join(" ");
      const it = { s: x.s, bp: !!x.bp, chg: x.chg }, ch = chg(it);
      return `<div class="mr" data-mk="${esc(tok)}"${i >= SHOW ? " data-mr hidden" : ""}><span class="mc">${esc(x.cls)}</span><span class="mi">${esc(x.n || x.s || "")} <b data-s="${esc(x.s || "")}" data-x="${esc(JSON.stringify(it))}"${cP(ch)}>${txt(it, ch)}</b>${x.day && x.day !== RAW.asof ? `<small>${D2(x.day)}</small>` : ""}</span><span class="mx num">${x.z == null ? "—" : Math.abs(x.z).toFixed(1) + " 倍"}</span></div>`; };
    el.innerHTML = `<div class="bh"><h2>各市场</h2><span class="meta">按今天多不寻常排 · 倍数 = 比平常一天</span></div>` + top.map(rowH).join("") +
      `<button type="button" class="more" data-more="99" data-tpl="其余 N 类 ›" hidden></button>`;
    el.dataset.done = "1"; moreSync(el);
  }
  async function live() {
    if (!RD.live || document.hidden) return;
    try {
      const r = await fetch(RD.live.url.replace(/\/$/, "") + "/live", { headers: { authorization: "Bearer " + RD.live.token }, cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      LIVE = await r.json(); LIVE_ERR = null;
    } catch (e) { LIVE_ERR = String(e.message || e).slice(0, 40); }
    times(); mkts();
  }
  times(); mkts(); live();
  setInterval(() => { times(); }, 30e3);
  setInterval(live, 60e3);
  // 页面开着放久了，回到前台时整页重新载入（2026-10-29）：生成超过 20 分钟、在线、这台设备记住了钥匙（不用再输密码），5 分钟最多一次
  const stale = () => { try { return Date.now() - (RD.built || Date.now()) > 20 * 60e3 && navigator.onLine && window.QX_KEY && localStorage.getItem("qx-page-key")
    && Date.now() - (+sessionStorage.getItem("qx-reload") || 0) > 5 * 60e3; } catch (e) { return false; } };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    if (stale()) { try { sessionStorage.setItem("qx-reload", Date.now()); } catch (e) {} location.reload(); return; }
    live();
  });

  // ---------- 小信号和仓位（第四轮第 3 步，qx/smallsignal.py、qx/positioning.py；口径.md 第十一节）
  (function sig() {
    const S = RD.sig, P = RD.pos, el = $("sig"); if (!S || !el) return;
    el.hidden = false;
    const pc = f => f < 0.001 ? "不到 0.1%" : (f * 100).toFixed(f < 0.1 ? 1 : 0) + "%";
    const one = x => `<div class="fli"><div><span class="tg${x.level === "少见" ? " first" : ""}">历史上 ${pc(x.frac)} 的日子更极端</span><b>${esc(x.text)}</b></div>` +
      `<div class="fm">截至 ${md(x.asof)} · ${esc(plain(x.next))}</div>` +
      (x.asym ? `<div><span class="tg first">不对称：${esc(x.asym.market)}${esc(x.asym.word)}</span></div>` : "") + `</div>`;
    const sg = S.signals || [];
    let h = `<h2>小信号<small>截至 ${md(S.asof)} · 5 日变化到了自己全部历史最极端的 5% 以内的</small></h2>`;
    h += sg.length ? sg.slice(0, 3).map(one).join("") : `<p class="quiet">今天没有 5 日变化到历史最极端 5% 以内的小信号。</p>`;
    let more = sg.length > 3 ? `<h3 class="mh3">其余 ${sg.length - 3} 条小信号</h3>${sg.slice(3).map(one).join("")}` : "";
    const F = S.firsts || [];
    if (F.length) more += `<details><summary>一手来源第一次提到（${F.length} 条，最近 24 小时）</summary>${F.map(f => `<div class="fli">${f.watch ? `<span class="tg first">观察名单</span>` : ""}<b>${esc(f.ent)} × ${esc(f.line)}</b><div class="fm">${esc(f.src)} · ${esc(f.t)}</div></div>`).join("")}</details>`;
    more += `<details><summary>推演链走到哪一环</summary>${(S.chains || []).map(c => `<div class="fli"><b>${esc(plain(c.name))}</b> ${c.step ? `走到第 ${c.step} 环` : "还没走到第 1 环"}（共 ${c.of} 环）<div class="fm">${c.links.map((L, i) => `${i < c.step ? "●" : L.lit ? "◐" : "○"} ${esc(plain(L.name))}${L.lit ? "（" + md(L.lit) + "）" : ""}`).join(" → ")}</div>${c.next ? `<div class="fm">下一环看：${esc(plain(c.next.name))}——${esc(plain(c.next.check))}</div>` : ""}</div>`).join("")}<p class="knote">● 按顺序亮了；◐ 最近 20 个交易日亮过但顺序不对或隔太久。每一环"亮" = 这一环的读数出现小信号（5 日变化到了历史最极端的 5% 以内）、方向是事先登记的压力方向。</p></details>`;
    if ((S.mismatch || []).length) more += `<details><summary>数据动了价格没跟（只作描述）</summary>${S.mismatch.map(m => `<div class="fli">${esc(m.name)}：${esc(m.ym)} 营收同比 ${sgn(m.yoy, 0)}%，股价 20 日 ${sgn(m.r20, 1)}%</div>`).join("")}</details>`;
    if (P) {
      const cw = (P.crowd || []).filter(c => c.word !== "数据不够"), hot = cw.filter(c => c.word === "挤在多头" || c.word === "挤在空头");
      h += `<p style="margin:10px 0 2px;font-size:14px"><b>仓位挤在哪边：</b>${hot.length ? hot.map(c => `${esc(c.market)}<b style="color:var(--alert)">${esc(c.word)}</b>`).join("、") : "没有挤在一边的市场"}</p>` +
        "";
      more += `<details><summary>各市场仓位（${cw.length} 个市场，和自己全部历史比，10% 以外算挤）</summary><div class="mi" style="display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13.5px">${cw.map(c => `<span>${esc(c.market)} <b>${esc(c.word)}</b></span>`).join("")}</div></details>`;
      more += `<details><summary>每个仓位读数（${P.readings.length} 个）</summary><table class="nbk">${P.readings.map(r => `<tr><td>${esc(r.name)}<small>${esc(r.src)} · 截至 ${esc(r.asof)}，${esc(String(r.pub).slice(0, 10))} 公布${r.note ? " · " + esc(r.note) : ""}${r.pos == null && /空头回补/.test(r.name) && r.n ? `；攒到第 ${(RAW.front && RAW.front.min_obs || 104) + 1} 期才和历史比（现在 ${r.n} 期）` : ""}</small></td><td class="z">${r.value}${esc(r.unit)}<small>${r.pos == null ? "还不和历史比" : "位置 " + Math.round(r.pos * 100) + "%"}${r.side && r.side !== "中间" ? " · " + esc(r.side) : ""}</small></td></tr>`).join("")}</table></details>`;
      const T = P.trend || [];
      if (T.length) more += `<details><summary>趋势基金（估）：简化模型，不是真实持仓</summary><table class="nbk">${T.map(x => `<tr><td>${esc(x.name)}<small>翻转价：20 日 ${fmt(x.flip[20], 2)} · 60 日 ${fmt(x.flip[60], 2)} · 120 日 ${fmt(x.flip[120], 2)}</small></td><td class="z">${x.score > 0 ? "+" : ""}${x.score}<small>${x.score >= 2 ? "偏多" : x.score <= -2 ? "偏空" : "混"}</small></td></tr>`).join("")}</table><p class="knote">20、60、120 日涨跌各算 +1 / −1；价格跌破某个周期的翻转价，那个周期就翻成空。</p></details>`;
    }
    el.innerHTML = h + (more ? `<details><summary>更多：其余小信号、推演链、各市场仓位、趋势基金（估）</summary>${more}</details>` : "");
  })();

  // ---------- 机会和风险卡（第四轮第 4 步，qx/radar.py；口径.md 第十二节）
  (function cards() {
    const K = RD.cards, el = $("cards"); if (!K || !el || el.dataset.blk) return;      // 新4：cards4() 画（这段留着）
    el.hidden = false;
    const cs = K.cards || [];
    const pc = f => f == null ? "—" : f < 0.001 ? "不到 0.1%" : (f * 100).toFixed(f < 0.1 ? 1 : 0) + "%";
    const one = c => `<details class="cd" data-k="${esc("card:" + c.key)}"><summary><span class="ns">${esc(c.cls_name)} · ${md(c.date)} · 历史上同样极端的 ${pc(c.rank)}${c.replayed ? "" : " · 还没有回放"}</span><b>${esc(c.title)}</b></summary>` +
      `<dl><dt>为什么现在</dt><dd>${esc(c.why)}</dd><dt>哪里算错</dt><dd>${esc(c.wrong)}</dd><dt>空间</dt><dd>${esc(c.space || "—")}</dd><dt>用什么做</dt><dd>${esc(c.use)}</dd><dt>时间窗口</dt><dd>${esc(c.window)}</dd></dl>` +
      `<div class="ns">${esc(c.note)}</div></details>`;
    let h = `<h2>机会和风险<small>截至 ${md(K.asof)} · 满足条件的 ${cs.length} 张，历史上同样极端的越少越靠前，点开看五栏</small></h2>`;
    h += cs.length ? cs.slice(0, 3).map(one).join("") : `<p class="quiet">今天没有满足条件的卡。</p>`;
    let more = cs.length > 3 ? cs.slice(3).map(one).join("") : "";
    const R2 = (K.replay || {})[2] || [], R4 = (K.replay || {})[4] || [], T4 = (K.replay || {}).tally4 || {};
    more += `<details><summary>回放：第 2 类信用和股价背离（最近 2 年 ${R2.length} 次）</summary><table class="nbk">${R2.slice().reverse().map(x => `<tr><td>${esc(x.date)} ${esc(x.basket)}<small>篮子 ${x.b}，信用健康度 ${x.h}</small></td><td class="z">${x.ret20 == null ? "未满 20 天" : (x.ret20 > 0 ? "+" : "") + x.ret20 + "%"}<small>途中最深 ${x.mdd == null ? "—" : x.mdd + "%"}</small></td></tr>`).join("")}</table><p class="knote">20 天后按卡看好的方向算（信用变好、股价没跟 → 看涨；信用变差、股价没跟 → 看跌）。</p></details>`;
    more += `<details><summary>回放：第 4 类消息反应不对称（最近 4 个季度）</summary><table class="nbk">${Object.entries(T4).sort().reverse().map(([q, g]) => `<tr><td>${esc(q)}<small>${g["家数"]} 家发财报（市值 ≥ 200 亿美元）</small></td><td class="z">好消息不涨 ${g["好消息不涨"]}<small>坏消息不跌 ${g["坏消息不跌"]} · AI 链 ${g["AI 链"]}</small></td></tr>`).join("")}</table><p class="knote">最近的 ${Math.min(20, R4.length)} 家：${R4.slice(-20).reverse().map(x => esc(x.sym) + " " + esc(x.kind)).join("、")}</p></details>`;
    if (Object.keys(K.pending || {}).length) more += `<p class="vlink">还没回放的几类、哪天攒够：<a href="#v-zt" data-view="zt" data-sec="z-accrue">状态 ›</a></p>`;
    el.innerHTML = h + `<details><summary>更多：${cs.length > 3 ? `其余 ${cs.length - 3} 张卡、` : ""}回放清单</summary>${more}</details>`;
  })();

  // ---------- 机会和风险（新4）：每张一行（编号、标题），整行点开看五栏；露 3 张，其余 5 张收在按钮里，第 9 张以后不画（节点在，推送点开会露出来）
  (function cards4() {
    const K = RD.cards, el = $("cards"); if (!K || !el || !el.dataset.blk) return;
    const cs = K.cards || [], SHOW = 3, MORE = 5;
    const pc = f => f == null ? "—" : f < 0.001 ? "不到 0.1%" : (f * 100).toFixed(f < 0.1 ? 1 : 0) + "%";
    const one = (c, i) => `<div class="cw" data-k="${esc("card:" + c.key)}"${i >= SHOW + MORE ? " hidden" : i >= SHOW ? " data-mr hidden" : ""}>` +
      `<div class="cc" role="button" tabindex="0" aria-expanded="false" aria-controls="cx-${i}"><span class="ck num">${i + 1}</span><span class="ctx"><b class="kt">${esc(c.title)}</b><small>${esc(c.cls_name)} · ${esc(c.window || "")}</small></span><span class="go" aria-hidden="true">›</span></div>` +
      `<div class="xp" id="cx-${i}" hidden><dl class="cf"><dt>为什么现在</dt><dd>${esc(c.why)}</dd><dt>哪里算错</dt><dd>${esc(c.wrong)}</dd><dt>空间</dt><dd>${esc(c.space || "—")}</dd><dt>用什么做</dt><dd>${esc(c.use)}</dd><dt>时间窗口</dt><dd>${esc(c.window)}</dd></dl>` +
      `<p class="cnote">${esc(c.cls_name)} · ${md(c.date)} · 历史上同样极端的 ${pc(c.rank)}${c.replayed ? "" : " · 还没有回放"}${c.note ? " · " + esc(c.note) : ""}</p></div></div>`;
    el.innerHTML = `<div class="bh"><h2>机会和风险</h2><span class="meta">情景，不是买卖建议</span></div>` +
      (cs.length ? cs.map(one).join("") : `<p class="quiet">今天没有满足条件的卡。</p>`) +
      `<button type="button" class="more" data-more="99" data-tpl="其余 N 张 ›" hidden></button>`;
    moreSync(el);
  })();

  // ---------- 前瞻和 AI 账本（第四轮第 5 步，qx/forward.py、qx/timeline.py、qx/ledger.py；口径.md 第十三节）
  (function fwd() {
    const F = RD.fwd, el = $("fwd"); if (!F || !el) return;
    // 时间轴、"接下来的检验"用页面的改正版（qx/front.py tl_fix()，新3：纳斯达克宏观日历差一天的挪回来、漏了的非农从 BLS 发布日表补；推送读的那份不动）
    const TF = RAW.front && RAW.front.tlfix;
    el.hidden = false;
    // 前瞻那几行是推送也读的字，句尾带"（偏高）/（少见）"；页面上换成同一个读数"历史上同方向更极端的日子占多少"（小信号、配对读数里本来就有），字和推送都不动
    const SF = new Map(((RD.sig && RD.sig.signals) || []).map(x => [x.text, x.frac])), PF = [];
    for (const b of (RD.narr && RD.narr.baskets) || []) for (const p of b.pairs || []) PF.push([p.name + " 20 日", p.frac]);
    const lvn = s => { const m = /^(.*)（(?:偏高|少见)）$/.exec(String(s)); if (!m) return s;
      const f = SF.has(m[1]) ? SF.get(m[1]) : (PF.find(([k]) => m[1].startsWith(k)) || [])[1];
      return f == null ? s : `${m[1]}（历史上 ${fr(f)} 的日子更极端）`; };
    const gap = s => String(s).replace(/(\d 日)([+−-]\d)/g, "$1 $2");      // "20 日+60 个基点"补空格（只改显示）
    const li = xs => xs.length ? `<ul class="nw">${xs.map(x => `<li>${esc(gap(plain(lvn(x))))}</li>`).join("")}</ul>` : `<p class="knote">—</p>`;
    let h = `<h2>前瞻<small>截至 ${md(F.asof)} · 六条线，每条：先变的小信号、现在怎么样、接下来的检验</small></h2>`;
    h += F.lines.map(L => (TF && TF.next && TF.next[L.id] ? Object.assign({}, L, { next: TF.next[L.id] }) : L)).map(L => `<details class="cd"><summary><b>${esc(L.name)}</b><span class="ns">${L.signals.length ? L.signals.length + " 条小信号" : "没有小信号"} · 接下来 ${L.next.length} 件</span></summary>` +
      `<dl><dt>先变的小信号</dt><dd>${li(L.signals)}</dd><dt>现在怎么样</dt><dd>${li(L.now)}</dd><dt>接下来的检验（30 天内）</dt><dd>${li(L.next)}</dd></dl></details>`).join("");
    for (const S of F.scenarios || []) {
      h += `<h3 class="mh3">三种走向 · ${esc(S.name)}<small style="font-weight:500;color:var(--ink-3)">（${esc(S.since)} 登记；${S.lead ? "先出现的是：" + esc(S.lead) : "登记以后还没有哪条的信号先出现"}）</small></h3>` +
        S.ways.map(w => `<details class="cd"><summary><b>${esc(w.name)}</b><span class="ns">${esc(w.how)} · 规则信号亮了 ${w.lit} 个</span></summary><ul class="nw">${w.signals.map(x => `<li>${x.hit === null ? "◇" : x.hit ? "●" : "○"} ${esc(x.text)}<small>${esc(x.why)}${x.first ? " · " + esc(x.first) + " 第一次亮" : x.pre ? " · 登记时已亮" : ""}</small></li>`).join("")}</ul></details>`).join("") +
        `<p class="knote">● 亮 ○ 没亮 ◇ 写不成规则、要人看。${esc(S.note)} 情景，不是买卖建议。</p>`;
    }
    const T = TF ? Object.assign({}, F.timeline, { events: TF.events }, TF.missing ? { missing: TF.missing } : {}) : (F.timeline || {});   // "排不到的"也用改正版（新3 复查改正）
    h += `<details><summary>时间轴：未来 6 个月 ${(T.events || []).length} 件（北京时间）</summary><table class="nbk">${(T.events || []).map(e => `<tr><td>${esc(e.bj)}</td><td><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a><small>${esc(e.src)}</small></td></tr>`).join("")}</table>` +
      `<p class="knote"><b>排不到的：</b>${(T.missing || []).map(esc).join("；")}。选举、上市、大额融资这类没有固定日程的，要手动登记才有。</p></details>`;
    el.innerHTML = h;
    const lg = $("ledger");
    if (lg && (F.ledger || []).length) {
      lg.hidden = false;
      lg.innerHTML = `<h2>AI 账本<small>每个数带来源、时点、下次公布日</small></h2><table class="nbk">${F.ledger.filter(r => !/^(缺|没有免费)/.test(String(r.value || ""))).map(r => `<tr><td>${esc(r.name)}<small>${esc(plain(r.chain))} · ${esc(String(r.src || "").replace(/^财政部 Fiscal Data$/, "美国财政部"))}${r.asof ? " · " + esc(r.asof) : ""} · 下次 ${esc(r.next)}</small></td><td class="z" style="white-space:normal">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.value)}</a>` : esc(r.value)}</td></tr>`).join("")}</table>` +
        (F.ledger.some(r => /^(缺|没有免费)/.test(String(r.value || ""))) ? `<p class="vlink">缺的几行（没取到、要联系邮箱、没有免费的数）：<a href="#v-zt" data-view="zt" data-sec="z-miss">状态 ›</a></p>` : "");
    }
  })();

  // ---------- 快讯（第四轮第 1 步，qx/flash.py；口径.md 第九节）
  (function () {
    const F = RAW.flash, el = $("flash"); if (!F || !el || el.closest("[data-blk]")) return;      // 新4：flash4() 画（这段留着）
    el.hidden = false;
    const it = x => `<div class="fli" data-ks="${esc((x.k || []).join(" "))}"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.t)}</a>` +
      `<div class="fm">${x.src.map(esc).join("；")} · 发布 ${esc(x.pub)}，看到 ${esc(x.seen)}（北京）${x.n > 1 ? ` · ${x.n} 家` : ""}</div>` +
      `<div>${x.first.map(f => `<span class="tg first">第一次：${esc(f)}</span>`).join("")}${x.ents.map(e => `<span class="tg">${esc(e)}</span>`).join("")}${x.lines.map(l => `<span class="tg">${esc(l)}</span>`).join("")}</div></div>`;
    const top = F.items.slice(0, F.top), more = F.items.slice(F.top);
    el.innerHTML = `<h2>快讯<small>最近 ${F.hours} 小时，打上标签的 ${F.shown} 件（共看到 ${F.total} 条）</small></h2>` +
      (top.length ? top.map(it).join("") : `<p class="quiet">最近 ${F.hours} 小时没有打上标签的快讯。</p>`) +
      (more.length ? `<details><summary>再看 ${more.length} 件</summary>${more.map(it).join("")}</details>` : "") +
      `<p class="vlink">各条路的健康和延迟${broken().length ? `（<b style="color:var(--alert)">${broken().length} 条路断了</b>）` : ""}：<a href="#v-zt" data-view="zt" data-sec="z-flash">状态 ›</a></p>`;   // 健康表搬到 状态（第四轮后台精简第 2 步）
  })();

  // ---------- 发生了什么（新4）：快讯露最多 3 件（其余节点在、不画），要闻收在按钮里（happen()）
  (function flash4() {
    const F = RAW.flash, el = $("flash"); if (!F || !el || !el.closest("[data-blk]")) return;
    const its = F.items || [], top = Math.max(1, Math.min(F.top || 3, 3));
    el.innerHTML = its.map((x, i) => `<div class="fli" data-ks="${esc((x.k || []).join(" "))}"${i >= top ? " hidden" : ""}><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.t)}</a>` +
      `<div class="fm">${(x.src || []).map(esc).join("；")} · 看到 ${esc(x.seen)}（北京）${x.n > 1 ? ` · ${x.n} 家` : ""}</div>` +
      `${(x.first || []).length ? `<div>${x.first.map(f => `<span class="tg first">第一次：${esc(f)}</span>`).join("")}</div>` : ""}</div>`).join("");
    el.hidden = !its.length;
    const m = $("happen-m"); if (m) m.textContent = its.length ? `快讯 ${F.hours} 小时内 ${its.length} 件` : `快讯 ${F.hours} 小时内没有打上标签的`;
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
    const LS = "qx-kline-v2", LSD = "qx-draw-v1";          // v2（2026-10-29）：前台默认只画 200 日线、色带、恐慌热度副图
    const ld = (k, dflt) => { try { const v = JSON.parse(localStorage.getItem(k) || "null"); return v == null ? dflt : v; } catch (e) { return dflt; } };
    const sv = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
    const SYMS = (RAW.chart || []).filter(s => s.rows && s.rows.length > 30);
    const DEF_MA = [5, 10, 20, 50, 100, 200];
    const MA_COL = { 5: ["#c98a00", "#e8b23a"], 10: ["#c2457a", "#ed93b1"], 20: ["#6250d6", "#a49cf0"], 50: ["#2a78d6", "#5b9be6"], 100: ["#178f66", "#3cc794"], 200: ["#d9561f", "#f08a5d"] };
    const XCOL = [["#7a6f5c", "#b5a98f"], ["#4d7c8a", "#86b6c4"], ["#8a5a44", "#c9967e"], ["#5c6b2e", "#a3b56a"]];
    const SUBS = [["heat", "恐慌热度（四行色块）"], ["fomc", "下次议息会降息概率"], ["sell", "抛售恐慌"], ["price", "定价恐慌"], ["pos", "仓位恐慌"], ["credit", "信用压力"], ["rsi", "RSI"], ["vix", "VIX"], ["t3", "VIX 期限结构"], ["breadth", "成分股广度"], ["none", "不显示"]];
    const cfg = Object.assign({ sym: SYMS[0].k, n: 252, mas: DEF_MA.slice(), on: { 5: 0, 10: 0, 20: 0, 50: 0, 100: 0, 200: 1 }, sub: "heat", mk: false, smk: false, bg: true, sw: false, redUp: false }, ld(LS, {}));
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
      if (cfg.mk) for (const [d, t] of cur.judge || []) add(barDate(d), { t, side: "risk", col: "accent" });   // 判断日只在打开标签时画（判断卡和雷达分开）
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
      if (one) return { lo: 0, hi: 100, lines: [50, 70, 90], ser: [{ f: i => dv(i, one[1]), col: T.heat, w: 1.6 }], area: one[1], lab: one[0], dp: 0, fill: [[90, 100, T.heat]] };
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
      const W = Math.max(300, cv.parentElement.clientWidth || 700), H = W < 560 ? 420 : 560, dpr = window.devicePixelRatio || 1;
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
      const vFrac = hasVol ? 0.13 : 0, sFrac = sub ? (sub.heat ? Math.max(0.17, (24 + HEATROWS.length * 14) / plotH) : 0.22) : 0;   // 热度四行每行至少 14 px（手机上图矮了，行名会叠）
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
          const tw = g.measureText(nm).width + 8; g.fillStyle = DARK ? "rgba(27,31,34,.85)" : "rgba(255,255,255,.85)"; g.fillRect(G.L + 2, y0 + rh / 2 - Math.min(8, rh / 2), tw, Math.min(16, rh));
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
        if (cfg.sub === "heat") val = HEATROWS.map(([k, nm]) => `${nm} ${LVS(dv(i, k))}`).join(G.W < 560 ? " " : " · ");
        else if (["sell", "price", "pos", "credit"].includes(cfg.sub)) val = `分位 ${LVS(dv(i, cfg.sub))}${mw(cfg.sub) ? " · " + mw(cfg.sub) : ""}`;
        else if (cfg.sub === "rsi") val = fmt(b.rsi, 0);
        else if (cfg.sub === "fomc") { const x = FOMC[b.d]; val = x ? `${x[0] === b.d ? "当天" : "下次"} ${md(bjDay(x[0]))}（北京时间）：不变 ${Math.round(x[1] * 100)}% · 降 ${Math.round(x[2] * 100)}% · 加 ${Math.round(x[3] * 100)}%` : "这天没有数据"; }
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
        const mv = LN.map(([key, nm, mk]) => `${nm} <b>${LVW(r[key])}</b>${r[mk] == null ? "" : "，" + MW[r[mk]]}`).join(" · ");
        state = `<div class="big" style="color:${SINK(r.state)}">${NAMES[r.state]}${rg ? ` <span style="font-size:13px;color:var(--ink-3);font-weight:500">${rg}</span>` : ""}</div><p>${mv}</p><div class="three">` + ["在卖", "在怕", "投降"].map((nm, j) => `<div><p style="margin-top:6px"><b>${nm}</b></p>${factHTML(F3[j], j + 1)}</div>`).join("") + `</div>`; }
      const dn = (DAYNEWS[b.d] || []), fx = FOMC[b.d];
      const dayInfo = dn.length || fx ? `<div class="kpc" style="grid-column:1/-1"><h4>这一天存下的新闻和预测市场</h4>${fx ? `<p>${fx[0] === b.d ? "当天" : "下次"}议息会（北京时间 ${md(bjDay(fx[0]))}）：不变 ${Math.round(fx[1] * 100)}% · 降息 ${Math.round(fx[2] * 100)}% · 加息 ${Math.round(fx[3] * 100)}%</p>` : ""}${dn.length ? `<ul class="nw">${dn.map(([tp, t, src, url]) => `<li><a href="${esc(url)}" target="_blank" rel="noopener">${esc(t)}</a><small>${esc(tp)} · ${esc(src)}</small></li>`).join("")}</ul>` : ""}</div>` : "";
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
    function dayLine(i) {
      const el = $("kday"), b = B[i]; if (!el || !b) return;
      const pv = B[i - 1], ch = pv ? (b.c / pv.c - 1) * 100 : null, vr = hasVol && isFinite(V50[i]) && V50[i] > 0 ? b.v / V50[i] : null;
      el.innerHTML = `那一天：<b>${+b.d.slice(5, 7)}/${+b.d.slice(8, 10)} 周${"日一二三四五六"[new Date(b.d + "T12:00:00").getDay()]}</b> 收 <b class="num">${fmtP(b.c)}</b>${ch == null ? "" : `，<b${cP(ch)}>${sgn(ch, 1)}%</b>`}${vr == null ? "" : `，量是 50 日均量的 ${fmt(vr, 1)} 倍`}${i === B.length - 1 ? "<small>　点图上哪天，这一行就换成那天</small>" : ` <button type="button" class="jd" data-act="latest">回到最新一天</button>`}`;
    }
    function panel() {
      const el = $("kpanel"); let html;
      if (previewI != null && !(sel && sel.type === "draw")) { el.innerHTML = dayPanel(previewI); return; }
      if (sel && sel.type === "draw") { const dw = draws().find(x => x.id === sel.id); html = dw ? (dw.type === "h" ? hPanel(dw) : tPanel(dw)) : null; if (!dw) sel = null; }
      if (!html) html = dayPanel(sel && sel.type === "day" ? clampI(sel.i) : B.length - 1);
      el.innerHTML = html;
      dayLine(previewI != null ? previewI : sel && sel.type === "day" ? clampI(sel.i) : B.length - 1);
    }
    let toolsOpen = matchMedia("(min-width: 700px)").matches;     // 手机上默认收起（第四轮验收：工具栏 370 px 把图挤出两屏），宽屏默认展开
    function toolbar() {
      const on = c => c ? " on" : "";
      $("ktools").innerHTML = `
        <div class="kgrp ksyms" role="group" aria-label="品种"><b style="font-size:15px">${esc((SYMS.find(s => s.k === cfg.sym) || {}).n || "")}</b><select class="kmore" id="kmore" aria-label="换品种"><option value="">换品种 ›</option><optgroup label="常看">${SYMS.filter(s => !s.more).map(s => `<option value="${esc(s.k)}">${esc(s.n)}</option>`).join("")}</optgroup>${[...new Set((RAW.kmore || []).map(x => x.cls || "其他"))].map(c => `<optgroup label="${esc(c)}">${RAW.kmore.filter(x => (x.cls || "其他") === c).map(x => `<option value="${esc(x.k)}">${esc(x.n)}</option>`).join("")}</optgroup>`).join("")}</select></div>
        <details class="kmt" id="kmt"${toolsOpen ? " open" : ""}><summary>工具：时间范围、画线、均线、副图</summary><div class="ktools2">
        <div class="kgrp" role="group" aria-label="时间范围">${[[63, "3月"], [126, "6月"], [252, "1年"], [756, "3年"], [0, "全部"]].map(([n, t]) => `<button type="button" class="kbtn${on(cfg.n === n)}" data-rng="${n}">${t}</button>`).join("")}<button type="button" class="kbtn" data-zoom="0.8" aria-label="放大">＋</button><button type="button" class="kbtn" data-zoom="1.25" aria-label="缩小">－</button></div>
        <div class="kgrp" role="group" aria-label="画线工具"><span class="kl">画线</span>${[["pick", "点选"], ["h", "水平线"], ["t", "趋势线"]].map(([k, t]) => `<button type="button" class="kbtn${on(tool === k)}" data-tool="${k}">${t}</button>`).join("")}<button type="button" class="kbtn" data-act="clear">${clearArm ? "再点一次确认" : "清除画线"}</button></div>
        <div class="kgrp" role="group" aria-label="均线"><span class="kl">均线</span>${cfg.mas.map(p => `<button type="button" class="kbtn mach${cfg.on[p] ? "" : " off"}" data-ma="${p}"><i style="background:${maCol(p)}"></i>MA${p}${DEF_MA.includes(p) ? "" : ' <span data-rm="' + p + '" aria-label="删除">×</span>'}</button>`).join("")}<input id="k-maadd" type="number" min="2" max="400" step="1" placeholder="周期" aria-label="添加均线周期"><button type="button" class="kbtn" data-act="addma">添加</button></div>
        <div class="kgrp"><label for="k-sub" class="kl">副图</label><select id="k-sub">${SUBS.map(([id, t]) => `<option value="${id}"${cfg.sub === id ? " selected" : ""}>${t}</option>`).join("")}</select>
          <label><input type="checkbox" id="k-mk"${cfg.mk ? " checked" : ""}>阶段标签</label><label><input type="checkbox" id="k-smk"${cfg.smk ? " checked" : ""}>抛售 / 涨过头</label><label><input type="checkbox" id="k-bg"${cfg.bg ? " checked" : ""}>阶段色带</label><label><input type="checkbox" id="k-sw"${cfg.sw ? " checked" : ""}>摆动结构</label>
          <button type="button" class="kbtn" data-act="updown">${cfg.redUp ? "红涨绿跌" : "绿涨红跌"}</button></div></div></details>`;
      $("kmt").ontoggle = e => { toolsOpen = e.target.open; };
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
    // 点了才去取 k/<代码>.enc，用解锁时留下的钥匙（window.QX_KEY）解开；本机预览是明文 JSON
    async function loadMore(k) {
      const x = (RAW.kmore || []).find(y => y.k === k); if (!x) return null;
      const have = SYMS.find(s => s.k === k); if (have) return have;
      const txt = await fetchEnc("k/" + x.f + (x.v ? "?v=" + x.v : ""));     // 带上最后一根日线的日期，旧缓存不会冒充新图
      const s = Object.assign(JSON.parse(txt), { more: true }); SYMS.push(s); return s;
    }
    $("ktools").addEventListener("change", async e => {
      if (e.target.id !== "kmore" || !e.target.value) return;
      const k = e.target.value; e.target.disabled = true;
      try { await loadMore(k); cfg.sym = k; saveCfg(); sel = null; pend = null; build(); buildMarkers(); setRange(cfg.n); toolbar(); panel(); renderMA(); schedule(); }
      catch (err) { e.target.disabled = false; e.target.insertAdjacentHTML("afterend", `<small style="color:var(--alert)"> 没取到（${esc(String(err.message || err))}）</small>`); }
    });
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
    $("kday").addEventListener("click", e => { if (e.target.closest("[data-act=latest]")) { sel = null; previewI = null; setRange(cfg.n); panel(); schedule(); } });
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
  addEventListener("hashchange", () => { jumpK(); vhash(); });
  jumpK(); vhash();
})();
