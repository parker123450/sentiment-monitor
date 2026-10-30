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
      const parts = [`信用 ETF 跑输国债${r.etfp == null ? "" : `，分位 ${Math.round(r.etfp)}`}`];
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
    $("ice").innerHTML = `<tr><th>评级</th><th class="r">现在（基点）</th><th class="r">5 日</th><th class="r">一个月里</th><th>三年里的位置</th></tr>` +
      Object.entries(RAW.ice).map(([k, v]) => { const p = (v.now - v.lo) / ((v.hi - v.lo) || 1) * 100, ch = v.now - v.m1;
        return `<tr><td>${esc(k)}<small>截至 ${md(v.date)}</small></td><td class="r num">${v.now}</td><td class="r num">${sgn(v.c5, 0)}${v.lvl5 && v.f5 != null ? `<small style="color:var(--alert)">历史上 ${fr(v.f5)} 的日子更极端</small>` : ""}</td><td class="r num">${sgn(ch, 0)}</td><td><div class="bar" title="三年最低 ${v.lo}，最高 ${v.hi}"><i style="width:${Math.max(3, p).toFixed(0)}%"></i></div></td></tr>`; }).join("");
  })();

  // ---------- 前台五样（第四轮五样方案，qx/front.py；口径十四）：每样一句结论、两三个数、只在有新东西时出的触发行
  (function front() {
    const FR = RAW.front; if (!FR || FR.err) return;
    const d2 = s => s ? `${+s.slice(5, 7)}/${+s.slice(8, 10)}` : "";
    const n0 = x => x == null ? "—" : Math.round(x).toLocaleString("en-US");
    const s1 = x => x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(1);
    const s0 = x => x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(Math.round(x));
    const head = (id, no, nm) => `<div class="ph"><h2>${no} ${nm}</h2><a href="#b-${id}" data-back="b-${id}">全部 ›</a></div>`;
    const dk = x => x.key && x.date ? ` data-ks="${esc(x.key + "|" + x.date)}"` : "";      // 带日期的推送编号（今天变了什么、判断）：只跳那一天的这一行
    const tr1 = x => `<div class="trg"${x.key ? ` data-k="${esc(x.key)}"` : ""}${dk(x)}>${esc(rwd(x.title))}${x.why ? `<small>${esc(x.why)}</small>` : ""}</div>`;
    const TRG = 2;                                    // 五样方案第 7 步：每块的触发行最多露 2 行，其余折起来（只是显示上限）
    const trg = xs => (xs = xs || []).slice(0, TRG).map(tr1).join("") + (xs.length > TRG ? `<details class="trgm"><summary>再看 ${xs.length - TRG} 条</summary>${xs.slice(TRG).map(tr1).join("")}</details>` : "");
    const put = (id, html) => { const el = $("p-" + id); if (el) el.innerHTML = html; };
    const T = FR.trig || {};
    // 顶上：判断卡（只在错的条件第一次出现、要人看的事两个交易日内）
    const tl = $("tline"), J = FR.judge || [];
    if (tl && J.length) { tl.hidden = false; tl.innerHTML = J.map(x => `<a class="tg2" href="#b-more" data-back="b-more" data-k="${esc(x.key)}"${dk(x)}>${esc(x.title)} → 我的判断</a>`).join(""); }
    // ① 情绪
    { const E = FR.emo; let h = head("emo", "①", "情绪");
      if (E) {
        const reg = E.regime === 2 ? `，板块自己跌（这一段 VIX 最高 ${E.vixmax}，没到 30）` : E.regime === 1 ? `，宏观冲击（这一段 VIX 最高到过 ${E.vixmax}）` : "";
        h += `<p class="hl">${E.stage ? `费城半导体${esc(E.name)}（${d2(E.since)} 起第 ${E.ndays} 个交易日）${reg}` : "费城半导体平稳：没在跌"}${E.changed ? "　<b style=\"color:var(--alert)\">今天变的</b>" : ""}<small>　阶段没有前瞻检验</small></p>`;
        const r = E.read || {}, b = v => v == null ? "—" : v >= 90 ? `<b>${Math.round(v)}</b>` : Math.round(v);
        h += `<div class="rw">恐慌读数（分位，100 = 历史上最恐慌）：抛售 ${b(r.sell)} · 定价 ${b(r.price)} · 仓位 ${b(r.pos)} · 信用 ${b(r.credit)}</div>`;
        h += `<div class="rw">大盘保险：VIX ${E.vix}（历史第 ${E.vix_pct} 分位）· 1 个月 ÷ 3 个月 ${E.t3}（≥1 是倒挂）</div>`;
      }
      put("emo", h + trg(T.emo)); }
    // ② 价格位置
    { let h = head("price", "②", "价格位置"); const P = FR.pos || [], S = P.find(x => x.k === "^SOX");
      if (S) h += `<p class="hl">费城半导体离一年高点 ${s1(S.dd)}%（${d2(S.hi_date)} 收盘 ${n0(S.hi)}${FR.ddv_pct != null ? `；按长期波动折算，历史上约 ${Math.round(FR.ddv_pct)}% 的日子比这更深` : ""}）；收盘 ${n0(S.close)}，在 200 日线${S.d200 >= 0 ? "上方" : "下方"} ${Math.abs(S.d200).toFixed(1)}%${S.d200 < 0 ? "；在线下时，60 天内再跌一大段的比例历来高 7–8 个百分点（只说风险，不说方向）" : ""}</p>`;
      if (P.length) h += `<table class="ptab"><tr><th></th><th>离一年高点</th><th>离 200 日线</th></tr>${P.map(x => `<tr><td>${esc(x.name)}</td><td class="num">${s1(x.dd)}%</td><td class="num">${s1(x.d200)}%${x.below_since ? `<small>（${d2(x.below_since)} 跌破，第 ${x.below_days} 天）</small>` : ""}</td></tr>`).join("")}</table>`;
      const N = FR.ends;
      if (N) { const m = xs => xs.map(([n, z]) => `${esc(n)} ${s1(z)}`).join("、");
        h += `<div class="rw">${N.main ? `<b>主线：${esc(N.main.name)}</b>（领跌，配的${esc(N.main.pair.name)} 20 日变化历史上 ${fr(N.main.pair.frac)} 的日子更极端）；` : ""}最弱：<b>${esc(N.lo.name)}</b>（20 日跌了平常波动的 ${Math.abs(N.lo.z).toFixed(1)} 倍：${m(N.lo.members)}）· 最强：<b>${esc(N.hi.name)}</b>（${s1(N.hi.z)}）</div>`; }
      put("price", h + trg(T.price)); }
    // ③ 买卖方结构和变化
    { let h = head("flow", "③", "买卖方结构和变化"); const F = FR.flow;
      if (F) {
        const ch = (F.changed || []).map(x => x.runs ? `${esc(x.market)}${esc(x.word)}（之前连挤 ${x.runs} 期）` : `${esc(x.market)}新${esc(x.word)}`);
        const byWord = {}; for (const x of F.still || []) (byWord[x.word] = byWord[x.word] || []).push(x);
        const st = Object.entries(byWord).map(([w, xs]) => `${xs.map(x => `${esc(x.market)}（第 ${x.runs} 期）`).join("、")}还${esc(w)}${xs.every(x => x.dir === xs[0].dir) && xs[0].dir ? "，这一期都在" + xs[0].dir : ""}`);
        const calm = (F.calm || []).map(x => `${esc(x.market)}${esc(x.word)}`);
        h += `<p class="hl">期货仓位（CFTC ${d2(F.asof)} 那期，${d2(F.pub)} 公布）：${[...ch, ...st, ...calm].join("；") || "没有挤在一边的市场"}</p>`;
        const ns = F.nums || [];
        if (ns.length) h += `<div class="rw">${ns.map(x => `${esc(x.lab || x.market)} ${x.prev == null ? "" : x.prev + "% → "}<b>${x.now}%</b>${x.pos == null ? "" : `（历史位置 ${Math.round(x.pos * 100)}%）`}`).join(" · ")}<small>　净多 ÷ 总持仓</small></div>`;
        const TF = F.tff || [];
        if (TF.length) { const vb = x => x.chg == null || x.chg === 0 ? "没变" : x.now >= 0 ? (x.chg > 0 ? "加多 " : "减多 ") + Math.abs(x.chg).toFixed(1) : (x.chg > 0 ? "空头回补 " : "加空 ") + Math.abs(x.chg).toFixed(1);
          const by = {}; for (const x of TF) (by[x.name] = by[x.name] || []).push(x);
          h += `<div class="rw">美股期指谁在场上：${Object.entries(by).map(([n, xs]) => `${esc(n)} ${xs.map(x => `${esc(x.who)} <b>${String(x.now).replace("-", "−")}%</b>（${x.pos == null ? "—" : Math.round(x.pos * 100) + "%"}，${vb(x)}）`).join(" · ")}`).join("；")}<small>　TFF 分类的净多 ÷ 总持仓，括号里是历史位置、这一期变化${F.tff_on ? "" : "；10-29 起股指、美债看它判断挤不挤"}</small></div>`; }
        const L = F.letf;
        if (L) h += `<div class="rw">SOXL / SOXS ${d2(L.day)} 净申赎：${["soxl", "soxs"].map(k => `${k.toUpperCase()} ${L[k] == null ? "不算" : `<b>${s1(L[k])}</b> 亿美元`}`).join("、")}${L.net == null ? "" : `；合起来钱往${L.net >= 0 ? "做多" : "做空"}那边 ${Math.abs(L.net).toFixed(1)} 亿${L.pos == null ? "" : `（历史位置 ${Math.round(L.pos * 100)}%）`}`}<small>　份额差 × 收盘价${L.split ? `；${esc(L.split)} 份额一天变了 1.8 倍以上，按合股或拆股处理，这天不算` : ""}${L.pos == null ? `；满 104 天才和历史比（${L.n} 天）` : ""}</small></div>`;
      }
      put("flow", h + trg(T.flow)); }
    // ④ 预期
    { let h = head("expect", "④", "预期"); const M = FR.m1 || [], S = M.find(x => x.name === "费城半导体");
      if (S) h += `<p class="hl">期权给费城半导体接下来一个月定价上下各约 ${S.m}%（约 ${n0(S.lo)}–${n0(S.hi)}）${M.filter(x => x !== S).map(x => `，${esc(x.name.replace(" 500", "").replace(" 100", ""))} ${x.m}%`).join("")}<small>　检验过：能衡量幅度，只说幅度，不说方向</small></p>`;
      const F = FR.fomc || [];
      if (F.length) {                                 // 下一次、下下次，按数据那天算（qx/front.py fomc()），日子是北京时间；概率是后台取好的整数百分比，原样写
        const none = F.every(x => x.why === "nosave"), pr = x => x.hold != null ? ` 不变 ${x.hold}%、降息 ${x.cut}%、加息 ${x.hike}%${x.stale ? "（上次取到的）" : x.asof ? `（${d2(x.asof)} 存的）` : ""}`
          : x.why === "nomkt" ? "，预测市场还没有盘口" : x.why === "fail" ? "，这次没取到预测市场的概率" : none ? "" : " 没存概率";
        h += `<div class="rw">议息会：${F.map((x, i) => `${i ? "下下次" : "下次"} ${d2(x.bj)}${pr(x)}`).join(none ? "、" : "；")}${none ? "（这天没存预测市场的概率）" : ""}<small>　北京时间${F.some(x => x.hold != null) ? " · Polymarket" : ""}</small></div>`; }
      const H = FR.h48 || [];
      if (H.length) h += `<div class="rw"><b>接下来 48 小时</b>（北京时间${FR.cal_late ? `，日历 ${d2(FR.cal_late)} 取的` : ""}）${H.map(d => `<div class="h48"><span class="d">${esc(d.day)}</span> ${d.items.map(x => `${esc(x.at)} ${esc(x.text)}`).join("；")}</div>`).join("")}</div>`;
      const R = FR.react;
      const s2 = x => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2);
      if (R) h += `<div class="rw">财报反应：${esc(R.word)}已报 ${R.n} 家，好消息不涨 ${R.bad}、坏消息不跌 ${R.good}（好消息不涨占 ${R.share}%${R.past_n ? `，以往 ${R.past_n} 季 ${R.past_lo}–${R.past_hi}%` : ""}）${R.beat_med != null ? `；超预期的 ${R.beat_n} 家反应中位数 ${s2(R.beat_med)} 个日度波动${R.beat_past_n ? `（以往 ${R.beat_past_n} 季 ${s2(R.beat_lo)} 到 ${s2(R.beat_hi)}）` : ""}` : ""}</div>`;
      put("expect", h + trg(T.expect)); }
    // ⑤ 基本面
    { let h = head("fund", "⑤", "基本面"); const E = FR.season, W = FR.tw, C = FR.credit || [], Y = FR.y10;
      const w20 = x => x.lvl20 && x.c20 > 0, w5 = x => x.lvl5 && x.up5, ex = f => `历史上 ${fr(f)} 的日子更极端`;
      const hot = C.filter(x => w20(x) || w5(x)).map(x => ({ x, f: Math.min(w20(x) ? x.f20 : 1, w5(x) ? x.f5 : 1) })).sort((a, b) => a.f - b.f).slice(0, 2).map(o => o.x);
      // 结论句写哪一段（20 日优先），下一行同一档同一段的"历史上…"就不再写；日子见下一行"融资环境（基点，FRED 几月几日）"，这里不重复
      const said = x => hot.includes(x) ? (w20(x) ? 20 : 5) : 0;
      const cw = hot.length ? `信用利差在走阔：${hot.map(x => said(x) === 20 ? `${esc(x.name)} 20 日 ${s0(x.c20)} 基点（${ex(x.f20)}）` : `${esc(x.name)} 5 日 ${s0(x.c5)} 基点（${ex(x.f5)}）`).join("、")}` : "利差五档都没走阔到历史最极端的 5%";
      h += `<p class="hl">${E ? `${esc(E.word)}已报 ${E.n} 家（市值 ≥200 亿美元），${E.beat} 家超预期` : ""}${W ? `；台积电 ${+W.ym.slice(5)} 月营收同比 ${s1(W.yoy)}%` : ""}；${cw}</p>`;
      const nm = x => `${esc(x.name)} ${n0(x.now)}${x.lvl20 ? `（20 日 ${s0(x.c20)}${said(x) === 20 ? "" : `，${ex(x.f20)}`}）` : x.lvl5 ? `（5 日 ${s0(x.c5)}${said(x) === 5 ? "" : `，${ex(x.f5)}`}）` : x.c20 != null ? `（20 日 ${s0(x.c20)}）` : `（5 日 ${s0(x.c5)}）`}`;
      const lowq = C.filter(x => ["单 B", "BB", "CCC"].includes(x.name)), ig = C.find(x => x.name === "投资级");
      if (C.length) h += `<div class="rw">融资环境（基点，FRED ${d2(C[0].date)}）：${lowq.map(nm).join(" · ")}<br>${ig ? nm(ig) : ""}${Y ? ` · 10 年美债 ${Number(Y.now).toFixed(2)}%（${esc(Y.src || "")}${Y.date !== FR.asof ? " " + d2(Y.date) : ""}，20 日 ${s0(Y.c20)} 基点）` : ""}</div>`;
      if (E && E.med != null) h += `<div class="rw">超预期幅度：中位 ${s1(E.med)}%${E.ai_n ? `；AI 链 ${E.ai_n} 家里 ${E.ai_beat} 家超预期` : ""}</div>`;
      put("fund", h + trg(T.fund)); }
  })();
  // 全部（后台）：点"全部 ›"或最下面的按钮打开，跳到那一组
  function openBack(id) {
    const bk = $("back"); if (!bk) return;
    if (bk.hidden) { bk.hidden = false; $("backbtn").hidden = true; dispatchEvent(new Event("resize")); }
    const el = id && $(id); if (el) el.scrollIntoView({ block: "start" });
  }
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("[data-back]"); if (a) { e.preventDefault(); openBack(a.dataset.back); } });
  if ($("backbtn")) $("backbtn").addEventListener("click", () => openBack("b-emo"));
  if (/^#b-/.test(location.hash)) openBack(location.hash.slice(1));

  // ---------- 今天要知道的（规则在 口径.md 第三节；文字在 qx/watch.py 写好，这里只排版）
  (function today() {
    const T = RAW.today, el = $("today"); if (!T || !el) return;
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
      html += `<details><summary>所有品种的趋势状态（日 / 周 / 月）</summary><p>上行 = 收盘在均线上方、均线在升；下行反过来；其他是震荡。日线 20 日均线，周线 10 周，月线 10 个月；数字是这个状态持续了多久。</p><table class="tbl tr"><tr><th>品种</th><th>日线</th><th>周线</th><th>月线</th></tr>${T.trends.map(r => `<tr><td>${esc(r.name)}</td>${c(r.d, r.dn, "天")}${c(r.w, r.wn, "周")}${c(r.m, r.mn, "个月")}</tr>`).join("")}</table></details>`;
    }
    el.innerHTML = html;
  })();

  // ---------- 期权：五个问题（规则在 口径.md 第四节；白话在 qx/options.py 写好）
  (function opt() {
    const O = RAW.options, el = $("opt"); if (!O || !el || !(O.rows || []).length) return;
    const Q = [["保险贵不贵", "q1"], ["更怕跌还是更想涨", "q2"], ["大家押在哪个价位", "q3"], ["做市商对冲会放大还是压住波动", "q4"], ["定价了多大的涨跌", "q5"]];
    // 大盘那一行：数从 qx/front.py opt_market() 来（和 options.py 同一个 10 年分位），写"10 年分位 N"，不写"偏高 / 少见"
    // 数在后台已经按要写的位数取过整（只取一次），这里不再取整；VIX 补齐一位小数（20 写成 20.0，和 market() 那句一样，不改数）
    // 拿不到时用 options.py market() 那句，但把没登记的 95 / 70 / 30 那几个词（少见地高 / 偏高 / 偏低 / 平常）去掉，只留数
    const M = RAW.front && RAW.front.optmkt, p10 = x => `10 年分位 ${x.p}`;
    const nowd = String(O.market || "").replace(/（(?:10 年里少见地高|偏高|偏低|平常)）/g, "").replace(/，(?:10 年里少见地高|偏高|偏低|平常)）/g, "）");
    const mk = M && M.vix ? [`VIX ${Number(M.vix.now).toFixed(1)}（${p10(M.vix)}）`, M.r9 != null ? `9 天保险是 30 天的 ${M.r9}%${M.r9_ge1 ? "：眼前几天有事" : ""}` : "",
      M.skew ? `SKEW ${M.skew.now}（买极端下跌保护的程度，${p10(M.skew)}）` : "", M.vvix ? `VVIX ${M.vvix.now}（保险本身的波动，${p10(M.vvix)}）` : ""].filter(Boolean).join("；") + "。" : nowd;
    el.innerHTML = `<summary>期权：五个问题<small>${esc((O.summary || "").replace(/、一个月定价 ±\d+%/g, ""))}</small></summary>
      <p>大盘：${esc(mk)}</p>
      <div class="oq">${O.rows.map(r => `<div class="oc"><h4>${esc(r.name)}<small>${r.live ? "盘中 · 延迟 15 分钟" : md(r.date || RAW.asof) + " 收盘"}</small></h4>${r.ans.map(a => `<div class="oa${a.warn ? " w" : ""}"><b>${esc(a.q)}</b>：${esc(a.a)}</div>`).join("")}</div>`).join("")}</div>
      <details><summary>这五个问题是什么意思</summary><dl class="ox">${Q.map(([q, k]) => `<dt>${q}</dt><dd>${esc(O.explain[k])}</dd>`).join("")}</dl></details>
      <p class="knote">期权链是 CBOE 延迟 15 分钟的报价，从 2026-10-19 起每天攒，现在 ${O.days} 天；攒满 250 个交易日以后才和历史比。K 线上 SMH、英伟达、美光、台积电标了做市商 gamma 转负 / 转正的日子。</p>`;
  })();

  // ---------- 我的判断（第 3 块；规则在 口径.md 第六节，卡片原文加密存放）
  (function judge() {
    const J = RAW.judge || [], el = $("judge"); if (!el) return;
    if (!J.length) { el.innerHTML = ""; return; }
    const cls = s => s === "支持" ? "s-for" : s === "反对" ? "s-against" : "s-mid";
    el.innerHTML = `<h2>我的判断</h2>` + J.map(e => `<div class="jc">
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
    const N = H.news || {}, C = H.calendar || [];
    const li = n => `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.t)}</a><small>${esc(n.topic ? n.topic + " · " : "")}${esc(n.src)} · ${esc(n.ago)}${n.k > 1 ? ` · ${n.k} 家报道` : ""}</small></li>`;
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
      `<p class="knote">新闻只从路透、彭博、华尔街日报、金融时报、CNBC、日经亚洲、美联储、韩联社、CoinDesk 和华尔街见闻"重要"快讯里取。期权：财报是反应日（时间未定的是当天加下一天）的涨跌，拆掉了别的日子平常的波动，写一半机会超过多少；议息会是到期以前的总幅度，包含到期前的正常波动，偏大一点。</p>`;
  })();

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
    const el = findK(x.key), t = el && (el.matches(".trg") ? el.firstChild : el.querySelector(".it-t, summary b, a") || el);
    if (t && t.textContent.trim()) return t.textContent.trim().slice(0, 80);
    return pushCat(x.key);
  }
  // 推送点开跳到那一条（#k=编号）：触发行、今天变了什么、机会和风险卡、快讯带 data-k / data-ks。按 原编号 → 加 card: 找，
  // 同一个编号前台有的先跳前台；不去掉日期找（会跳到后来另一天同一类的那一条）
  function findK(k) {
    const q = x => `[data-k="${CSS.escape(x)}"],[data-ks~="${CSS.escape(x)}"]`;
    for (const x of [k, "card:" + k]) {
      const els = [...document.querySelectorAll(q(x))];
      if (els.length) return els.find(e => !e.closest("#back")) || els[0];
    }
    return null;
  }
  function jumpK() {
    const m = /^#k=(.+)$/.exec(location.hash); if (!m) return;
    let k; try { k = decodeURIComponent(m[1]); } catch (e) { return; }
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}   // 刷新不再跳
    const el = findK(k) || $({ first: "flash", spread: "flash" }[k.split(":")[0]] || (/^move:[^|]*:live\|/.test(k) ? "mkts" : ""));
    if (!el || el.hidden) return;
    if (el.closest("#back")) openBack(null);
    for (let d = el.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
    el.classList.add("hit"); setTimeout(() => el.classList.remove("hit"), 6000);
    requestAnimationFrame(() => el.scrollIntoView({ block: "center" }));
  }
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("[data-pushl]"); if (!a) return; e.preventDefault();
    const el = $("pushl"); if (!el) return;
    el.hidden = !el.hidden; if (el.hidden) return;
    el.innerHTML = pushed().map(x => `<a href="#k=${encodeURIComponent(x.key)}">${bj(x.at)} · ${esc(pushTitle(x))}</a>`).join("") +
      `<p class="knote">北京时间。点一条跳到页面上那一条；合并成一条推的（"今天要知道的 N 件""新卡 N 张"）跳到第一件。</p>`; });
  function zword(z) { const a = Math.abs(z); return z == null ? "—" : (z < 0 ? "−" : "+") + a.toFixed(1); }
  function times() {
    const el = $("times"), ck = $("clock"); if (!el) return;
    if (ck) ck.textContent = "北京 " + bjd(Date.now());
    const FR = RAW.front || {}, age = Math.max(0, Math.round((Date.now() - (RD.built || Date.now())) / 60e3));
    const ago = age < 1 ? "刚刚" : age < 60 ? age + " 分钟前" : age < 1440 ? Math.floor(age / 60) + " 小时前" : Math.floor(age / 1440) + " 天前";
    const d2 = s => s ? `${+s.slice(5, 7)}/${+s.slice(8, 10)}` : "";
    const parts = [`<span class="${age > 40 ? "stale" : ""}">状态 ${ago}（${bjd(RD.built || Date.now())}）</span>`];
    if (LIVE && LIVE.prices) {
      const P = LIVE.prices.p || {}, by = {};
      for (const r of RD.mkts || []) for (const x of r.items) { const q = P[x.s]; if (q && q.at && r.open) by[r.market] = Math.max(by[r.market] || 0, q.at * 1000); }
      const ps = Object.entries(by).map(([m, t]) => `${esc(m)} 截至 ${bj(t)}${Date.now() - t > 30 * 60e3 ? "" : `，延迟约 ${Math.max(0, Math.round((Date.now() - t) / 60e3))} 分钟`}`);
      if (ps.length) parts.push("价格 " + ps.join("；"));
    } else if (RD.live) parts.push(`<span class="stale">实时价格取不到${LIVE_ERR ? "（" + esc(LIVE_ERR) + "）" : ""}，显示的是 15 分钟一次的状态</span>`);
    const asof = [`美股截至 ${d2(RAW.asof)} 收盘`];
    if ((FR.credit || []).length) asof.push(`信用利差截至 ${d2(FR.credit[0].date)}`);
    if (FR.flow) asof.push(`CFTC ${d2(FR.flow.asof)} 那期`);
    const pu = pushed();
    if (pu.length) asof.push(`<a href="#" class="pu" data-pushl>24 小时内推过 ${pu.length} 条 ›</a>`);
    el.innerHTML = parts.join(" · ") + "<br>" + asof.join(" · ");
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
  function mkts() {
    const M = RD.mkts, el = $("mkts"); if (!M || !el) return;
    el.hidden = false;
    const P = (LIVE && LIVE.prices && LIVE.prices.p) || {};
    el.innerHTML = M.map(r => `<div class="mr"><div class="mh"><span>${esc(r.cls)}</span><small>${r.open ? "开盘中" : r.today === false ? "今天休市" : r.note ? esc(r.note) : "已收盘"}</small></div><div class="mi">${r.items.slice(0, 8).map(x => {
        const q = P[x.s], ch = q && q.pc ? (x.bp ? (q.p - q.pc) * 100 : Math.log(q.p / q.pc)) : x.chg;
        const txt = ch == null ? "—" : x.bp ? (ch >= 0 ? "+" : "−") + Math.abs(ch).toFixed(0) + "bp" : pctP((Math.exp(ch) - 1) * 100);
        return `<span class="${Math.abs(x.z || 0) >= 2 ? "big" : ""}">${esc(x.n)} <b${cP(ch)}>${txt}</b></span>`; }).join("")}${r.items.length > 8 ? `<span>…共 ${r.items.length} 个</span>` : ""}${(r.miss || []).length ? `<span class="miss">缺：${r.miss.map(esc).join("、")}</span>` : ""}</div></div>`).join("") +
      `<p class="knote">每行按"今天涨跌 ÷ 长期日波动"从大到小排，加粗的是 2 倍以上。${Object.keys(P).length ? "盘中价格是打开页面时现取的（Yahoo）。" : "没有现取价格时是最近一个收盘。"}</p>`;
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
    const K = RD.cards, el = $("cards"); if (!K || !el) return;
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
    more += `<p class="knote">${Object.entries(K.pending || {}).map(([k, v]) => `第 ${k} 类：${esc(v)}`).join("；")}。</p>`;
    el.innerHTML = h + `<details><summary>更多：${cs.length > 3 ? `其余 ${cs.length - 3} 张卡、` : ""}回放清单</summary>${more}</details>`;
  })();

  // ---------- 前瞻和 AI 账本（第四轮第 5 步，qx/forward.py、qx/timeline.py、qx/ledger.py；口径.md 第十三节）
  (function fwd() {
    const F = RD.fwd, el = $("fwd"); if (!F || !el) return;
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
    h += F.lines.map(L => `<details class="cd"><summary><b>${esc(L.name)}</b><span class="ns">${L.signals.length ? L.signals.length + " 条小信号" : "没有小信号"} · 接下来 ${L.next.length} 件</span></summary>` +
      `<dl><dt>先变的小信号</dt><dd>${li(L.signals)}</dd><dt>现在怎么样</dt><dd>${li(L.now)}</dd><dt>接下来的检验（30 天内）</dt><dd>${li(L.next)}</dd></dl></details>`).join("");
    for (const S of F.scenarios || []) {
      h += `<h3 class="mh3">三种走向 · ${esc(S.name)}<small style="font-weight:500;color:var(--ink-3)">（${esc(S.since)} 登记；${S.lead ? "先出现的是：" + esc(S.lead) : "登记以后还没有哪条的信号先出现"}）</small></h3>` +
        S.ways.map(w => `<details class="cd"><summary><b>${esc(w.name)}</b><span class="ns">${esc(w.how)} · 规则信号亮了 ${w.lit} 个</span></summary><ul class="nw">${w.signals.map(x => `<li>${x.hit === null ? "◇" : x.hit ? "●" : "○"} ${esc(x.text)}<small>${esc(x.why)}${x.first ? " · " + esc(x.first) + " 第一次亮" : x.pre ? " · 登记时已亮" : ""}</small></li>`).join("")}</ul></details>`).join("") +
        `<p class="knote">● 亮 ○ 没亮 ◇ 写不成规则、要人看。${esc(S.note)} 情景，不是买卖建议。</p>`;
    }
    const T = F.timeline || {};
    h += `<details><summary>时间轴：未来 6 个月 ${(T.events || []).length} 件（北京时间）</summary><table class="nbk">${(T.events || []).map(e => `<tr><td>${esc(e.bj)}</td><td><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a><small>${esc(e.src)}</small></td></tr>`).join("")}</table>` +
      `<p class="knote"><b>排不到的：</b>${(T.missing || []).map(esc).join("；")}。选举、上市、大额融资这类没有固定日程的，要手动登记才有。</p></details>`;
    el.innerHTML = h;
    const lg = $("ledger");
    if (lg && (F.ledger || []).length) {
      lg.hidden = false;
      lg.innerHTML = `<h2>AI 账本<small>每个数带来源、时点、下次公布日</small></h2><table class="nbk">${F.ledger.map(r => `<tr><td>${esc(r.name)}<small>${esc(plain(r.chain))} · ${esc(r.src)}${r.asof ? " · " + esc(r.asof) : ""} · 下次 ${esc(r.next)}</small></td><td class="z" style="white-space:normal">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.value)}</a>` : esc(r.value)}</td></tr>`).join("")}</table>`;
    }
  })();

  // ---------- 快讯（第四轮第 1 步，qx/flash.py；口径.md 第九节）
  (function () {
    const F = RAW.flash, el = $("flash"); if (!F || !el) return;
    el.hidden = false;
    const it = x => `<div class="fli" data-ks="${esc((x.k || []).join(" "))}"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.t)}</a>` +
      `<div class="fm">${x.src.map(esc).join("；")} · 发布 ${esc(x.pub)}，看到 ${esc(x.seen)}（北京）${x.n > 1 ? ` · ${x.n} 家` : ""}</div>` +
      `<div>${x.first.map(f => `<span class="tg first">第一次：${esc(f)}</span>`).join("")}${x.ents.map(e => `<span class="tg">${esc(e)}</span>`).join("")}${x.lines.map(l => `<span class="tg">${esc(l)}</span>`).join("")}</div></div>`;
    const top = F.items.slice(0, F.top), more = F.items.slice(F.top);
    const lag = h => h.lag ? `中位 ${h.lag.med} 分钟（90% ${h.lag.p90}，${h.lag.n} 条）` : "还没攒够";
    const hr = F.health.map(h => `<tr><td>${esc(h.src)}${h.via ? " · 经" + esc(h.via) : ""}${h.sec ? `<small>（${esc(h.sec)} 栏目）</small>` : ""}</td><td class="${h.ok ? "" : "bad"}">${h.cloud ? "云端每 5 分钟取" : h.ok ? (h.ago == null ? "—" : h.ago + " 分钟前取到") : "停了 / 没取到"}</td><td>${lag(h)}</td></tr>`).join("");
    el.innerHTML = `<h2>快讯<small>最近 ${F.hours} 小时，打上标签的 ${F.shown} 件（共看到 ${F.total} 条）</small></h2>` +
      (top.length ? top.map(it).join("") : `<p class="quiet">最近 ${F.hours} 小时没有打上标签的快讯。</p>`) +
      (more.length ? `<details><summary>再看 ${more.length} 件</summary>${more.map(it).join("")}</details>` : "") +
      `<details><summary>各条路的健康和延迟</summary><table class="fh">${hr}</table>` +
      `<p class="knote">延迟 = 我们看到的时间 − 发布时间，只算每条路开始取以后新出现的条目；云端每 15 分钟取一次，所以含最多 15 分钟的等待。` +
      `${F.backfill_done ? "" : "过去 30 天还没回补完，\"第一次\"只标不推。"}路透经 TradingView、谷歌新闻取，是你 10-27 定的。</p></details>`;
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
      const r = await fetch("k/" + x.f + (x.v ? "?v=" + x.v : ""), { cache: "force-cache" }); if (!r.ok) throw new Error("HTTP " + r.status);   // 带上最后一根日线的日期，旧缓存不会冒充新图
      let txt;
      if (window.QX_KEY) {
        const b = new Uint8Array(await r.arrayBuffer()), key = await crypto.subtle.importKey("raw", window.QX_KEY, "AES-GCM", false, ["decrypt"]);
        const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b.slice(0, 12) }, key, b.slice(12));
        txt = await new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
      } else txt = await r.text();
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
  addEventListener("hashchange", jumpK);
  jumpK();
})();
