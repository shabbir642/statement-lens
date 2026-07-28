"""Stage 2: approved CSV -> a single self-contained report.html.

Zero external references: no CDN, no web fonts, no analytics, no chart library.
Charts are hand-rolled inline SVG built in the browser from data embedded in
the page, so it renders identically with wifi off.  All aggregation happens in
JavaScript so the month-range filter and category filter drive everything live.

Deliberately contains no "http" substring anywhere (SVG is injected via
innerHTML, which the HTML5 parser namespaces on its own) so the offline check
`grep http report.html` comes back empty.
"""

import json

from analysis import load_transactions
from categorise import OUTFLOW_ONLY, INCOME_CATEGORY


def build_report(csv_path, categories, out_path="report.html",
                 reconcile=None, net_transfers=True):
    from analysis import NEUTRAL_CATEGORIES
    from alerts import spending_alerts
    txns = load_transactions(csv_path, categories, net_transfers=net_transfers)
    payload = {
        "txns": txns,
        "categories": list(categories.keys()),
        "outflowOnly": sorted(OUTFLOW_ONLY),
        "incomeCategory": INCOME_CATEGORY,
        "neutral": sorted(NEUTRAL_CATEGORIES),
        "alerts": spending_alerts(txns),
        "reconcile": reconcile or {},
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = _TEMPLATE.replace("/*__DATA__*/", "const DATA = " + data_json + ";")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path, len(txns)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Statement Lens</title>
<style>
  :root {
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2330; --border:#2a3240;
    --fg:#e6edf3; --muted:#8b949e; --accent:#58a6ff;
    --in:#3fb950; --out:#f85149; --net:#d29922; --low:#e3b341;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font-family:var(--mono); font-size:13px; line-height:1.5; }
  h1,h2 { font-weight:600; letter-spacing:.02em; }
  h1 { font-size:18px; margin:0; }
  h2 { font-size:14px; margin:0 0 12px; color:var(--muted);
       text-transform:uppercase; letter-spacing:.08em; }
  header { padding:16px 20px; border-bottom:1px solid var(--border);
           display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  .wrap { padding:20px; max-width:1100px; margin:0 auto; }
  .panel { background:var(--panel); border:1px solid var(--border);
           border-radius:8px; padding:16px; margin-bottom:20px; }
  .num { font-variant-numeric:tabular-nums; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
           gap:12px; }
  .stat { background:var(--panel2); border:1px solid var(--border);
          border-radius:8px; padding:14px; }
  .stat .k { color:var(--muted); font-size:11px; text-transform:uppercase;
             letter-spacing:.08em; }
  .stat .v { font-size:22px; margin-top:6px; font-variant-numeric:tabular-nums; }
  .pos { color:var(--in); } .neg { color:var(--out); }
  .chips { display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
           gap:10px; margin-bottom:12px; }
  .chip { background:var(--panel2); border:1px solid var(--border);
          border-radius:8px; padding:10px 12px; }
  .chip .k { color:var(--muted); font-size:10px; text-transform:uppercase;
             letter-spacing:.06em; }
  .chip .v { font-size:16px; margin-top:4px; font-variant-numeric:tabular-nums; }
  .chip .s { color:var(--muted); font-size:10px; margin-top:2px; }
  .wkbar { display:flex; gap:4px; align-items:flex-end; height:40px; margin-top:6px; }
  .wkcol { flex:1; display:flex; flex-direction:column; align-items:center; gap:2px; }
  .wkcol .bar { width:100%; background:var(--out); border-radius:2px 2px 0 0; min-height:2px; }
  .wkcol .lbl { font-size:9px; color:var(--muted); }
  .alert { display:flex; gap:8px; align-items:flex-start; padding:7px 10px;
           border-radius:6px; margin:5px 0; border:1px solid var(--border);
           background:var(--panel2); font-size:12px; }
  .alert .ic { flex:0 0 auto; font-weight:700; }
  .alert.high { border-color:#5a1d1a; background:#2a1210; }
  .alert.high .ic { color:var(--out); }
  .alert.warn { border-color:#5c4708; background:#241d08; }
  .alert.warn .ic { color:var(--low); }
  .alert.info .ic { color:var(--accent); }
  .reconcile { padding:8px 12px; border-radius:6px; font-size:12px;
               border:1px solid var(--border); }
  .reconcile.ok { color:var(--in); border-color:#1f512b; background:#0f2413; }
  .reconcile.bad { color:var(--out); border-color:#5a1d1a; background:#2a1210; }
  .reconcile.skip { color:var(--muted); }
  .controls { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
              margin-left:auto; }
  select, input[type=search], button {
    background:var(--panel2); color:var(--fg); border:1px solid var(--border);
    border-radius:6px; padding:6px 10px; font-family:var(--mono); font-size:12px; }
  button { cursor:pointer; }
  button:hover { border-color:var(--accent); }
  .catbar { display:flex; align-items:center; gap:10px; margin:4px 0;
            cursor:pointer; padding:3px 6px; border-radius:6px; }
  .catbar:hover { background:var(--panel2); }
  .catbar.active { background:var(--panel2); outline:1px solid var(--accent); }
  .catbar .name { width:150px; flex:0 0 150px; }
  .catbar .track { flex:1; height:16px; background:var(--panel2);
                   border-radius:4px; overflow:hidden; }
  .catbar .fill { height:100%; background:var(--out); }
  .catbar .amt { width:130px; text-align:right; flex:0 0 130px;
                 font-variant-numeric:tabular-nums; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th,td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--border);
          vertical-align:top; }
  th { color:var(--muted); text-transform:uppercase; font-size:10px;
       letter-spacing:.06em; position:sticky; top:0; background:var(--panel); }
  td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
  tr.low td { background:rgba(227,179,65,.08); }
  .tag { font-size:10px; padding:1px 6px; border-radius:10px;
         border:1px solid var(--border); color:var(--muted); }
  .tag.low { color:var(--low); border-color:var(--low); }
  .spark { display:flex; align-items:center; gap:10px; padding:4px 0;
           border-bottom:1px solid var(--border); }
  .spark .name { width:150px; flex:0 0 150px; }
  .spark .amt { width:130px; text-align:right; flex:0 0 130px;
                font-variant-numeric:tabular-nums; color:var(--muted); }
  .muted { color:var(--muted); }
  .scroll { max-height:520px; overflow:auto; }
  .stab { display:inline-block; min-width:48px; }
  .clearfilter { color:var(--accent); cursor:pointer; text-decoration:underline;
                 font-size:12px; }
  .merchrow { display:flex; align-items:center; gap:10px; padding:5px 0;
              border-bottom:1px solid var(--border); }
  .merchrow .m { flex:1; overflow:hidden; text-overflow:ellipsis;
                 white-space:nowrap; }
  .badge { font-size:10px; color:var(--muted); }
  code.j { display:block; white-space:pre; background:var(--panel2);
           border:1px solid var(--border); border-radius:6px; padding:10px;
           margin-top:10px; overflow:auto; font-size:11px; }
</style>
</head>
<body>
<header>
  <h1>Statement Lens</h1>
  <div id="reconcile"></div>
  <div class="controls">
    <label class="muted">from
      <select id="mfrom"></select></label>
    <label class="muted">to
      <select id="mto"></select></label>
    <span id="activefilter"></span>
  </div>
</header>
<div class="wrap">
  <div class="panel"><div class="stats" id="stats"></div></div>
  <div class="panel" id="alertspanel"><h2>Alerts</h2><div id="alerts"></div></div>
  <div class="panel"><h2>Monthly flow &mdash; income above, spending below, net line</h2>
    <div id="flow"></div></div>
  <div class="panel"><h2>Insights <span class="muted">(for the selected month range)</span></h2>
    <div id="insights"></div></div>
  <div class="panel"><h2>Category breakdown <span class="muted">(click to filter everything below)</span></h2>
    <div id="cats"></div></div>
  <div class="panel"><h2>Category trends</h2><div id="sparks"></div></div>
  <div class="panel"><h2>Recurring commitments</h2>
    <div class="muted" style="margin-bottom:8px">Stability = share of charges within 2% of the median. 100% is a real subscription; a low score is coincidence, shown not tuned away.</div>
    <div id="recurring"></div></div>
  <div class="panel"><h2>Outliers <span class="muted">(large relative to their own category: median + 4&times;MAD)</span></h2>
    <div id="outliers"></div></div>
  <div class="panel"><h2>Unrecognised merchants</h2>
    <div class="muted" style="margin-bottom:8px">Pick a category per merchant, then copy the rules to paste into categories.json.</div>
    <div id="unrecognised"></div>
    <button id="copyrules">Copy rules JSON</button>
    <code class="j" id="rulesout" style="display:none"></code></div>
  <div class="panel"><h2>Transactions</h2>
    <input type="search" id="search" placeholder="search description / category..."
           style="width:100%;margin-bottom:10px">
    <div class="scroll"><table id="txntable"></table></div></div>
</div>
<script>
/*__DATA__*/

// ---- formatting -----------------------------------------------------------
const inr = new Intl.NumberFormat('en-IN', {maximumFractionDigits:0});
const inr2 = new Intl.NumberFormat('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmt  = n => 'Rs ' + inr.format(Math.round(n));
const fmt2 = n => 'Rs ' + inr2.format(n);
const esc  = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ---- state ----------------------------------------------------------------
const T = DATA.txns;
const MONTHS = [...new Set(T.map(t => t.month).filter(Boolean))].sort();
const state = { from:0, to:MONTHS.length-1, category:null, search:'' };
const overrides = {};   // merchant -> chosen category (unrecognised panel)

// ---- helpers --------------------------------------------------------------
function inRange(t){ const i = MONTHS.indexOf(t.month);
  return i >= state.from && i <= state.to; }
function monthFiltered(){ return T.filter(inRange); }
// real() drops money-neutral internal transfers, so spend/income/flow/insights
// reflect actual money in and out, not shuffles between your own accounts.
function real(arr){ return arr.filter(t => !t.internal); }
function belowFiltered(){                 // month + category filter
  return monthFiltered().filter(t => !state.category || t.category === state.category);
}
function activeMonths(){ return MONTHS.slice(state.from, state.to+1); }
function nMonths(){ return Math.max(1, state.to - state.from + 1); }

// ---- header stats ---------------------------------------------------------
function renderStats(){
  const rows = real(monthFiltered());
  let income=0, spend=0;
  for(const t of rows){ if(t.amount>0) income+=t.amount; else spend+=t.amount; }
  const n = nMonths();
  const committed = recurringList().reduce((s,r)=>s+r.annualised, 0);
  const cards = [
    ['Spend / month', fmt(Math.abs(spend)/n), 'neg'],
    ['Income / month', fmt(income/n), 'pos'],
    ['Net / month', fmt((income+spend)/n), (income+spend)>=0?'pos':'neg'],
    ['Committed / year', fmt(committed), ''],
  ];
  document.getElementById('stats').innerHTML = cards.map(([k,v,c]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');
}

// ---- monthly flow chart (inline SVG via innerHTML) ------------------------
function renderFlow(){
  const months = activeMonths();
  const inc = {}, out = {}, net = {};
  for(const m of months){ inc[m]=0; out[m]=0; }
  for(const t of real(monthFiltered())){
    if(t.amount>0) inc[t.month]+=t.amount; else out[t.month]+=Math.abs(t.amount);
  }
  months.forEach(m => net[m] = inc[m]-out[m]);
  const W=Math.max(640, months.length*70), H=280, pad=40, mid=H/2;
  const maxV = Math.max(1, ...months.map(m=>Math.max(inc[m],out[m])));
  const bw = (W-pad*2)/months.length*0.5;
  const x = i => pad + (W-pad*2)*(i+0.5)/months.length;
  const yUp = v => mid - (v/maxV)*(mid-pad);
  const yDn = v => mid + (v/maxV)*(mid-pad);
  const netMax = Math.max(1, ...months.map(m=>Math.abs(net[m])));
  const yNet = v => mid - (v/netMax)*(mid-pad);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">`;
  s += `<line x1="${pad}" y1="${mid}" x2="${W-pad}" y2="${mid}" stroke="var(--border)"/>`;
  months.forEach((m,i)=>{
    const cx=x(i);
    s+=`<rect x="${cx-bw/2}" y="${yUp(inc[m])}" width="${bw}" height="${mid-yUp(inc[m])}" fill="var(--in)" opacity="0.85"><title>${m} in ${fmt(inc[m])}</title></rect>`;
    s+=`<rect x="${cx-bw/2}" y="${mid}" width="${bw}" height="${yDn(out[m])-mid}" fill="var(--out)" opacity="0.85"><title>${m} out ${fmt(out[m])}</title></rect>`;
    s+=`<text x="${cx}" y="${H-8}" fill="var(--muted)" font-size="10" text-anchor="middle">${m.slice(2)}</text>`;
  });
  const pts = months.map((m,i)=>`${x(i)},${yNet(net[m])}`).join(' ');
  s+=`<polyline points="${pts}" fill="none" stroke="var(--net)" stroke-width="2"/>`;
  months.forEach((m,i)=>{ s+=`<circle cx="${x(i)}" cy="${yNet(net[m])}" r="3" fill="var(--net)"><title>${m} net ${fmt(net[m])}</title></circle>`; });
  s+=`</svg>`;
  document.getElementById('flow').innerHTML = s;
}

// ---- alerts (rule-based, computed in Python, statement-level) --------------
function renderAlerts(){
  const a = DATA.alerts || [];
  const panel = document.getElementById('alertspanel');
  if(!a.length){ panel.style.display='none'; return; }
  const ic = {high:'!!', warn:'!', info:'i'};
  document.getElementById('alerts').innerHTML = a.map(x=>
    `<div class="alert ${x.level}"><span class="ic">${ic[x.level]||'i'}</span><span>${esc(x.msg)}</span></div>`).join('');
}

// ---- insights (second-order patterns) -------------------------------------
function renderInsights(){
  const rows = real(monthFiltered());
  const debits = rows.filter(t=>t.amount<0);
  const credits = rows.filter(t=>t.amount>0);
  const outs = debits.map(t=>Math.abs(t.amount)).sort((a,b)=>b-a);
  const grossOut = outs.reduce((s,a)=>s+a,0);
  const grossIn = credits.reduce((s,t)=>s+t.amount,0);
  const pareto = k => grossOut ? Math.round(outs.slice(0,k).reduce((s,a)=>s+a,0)/grossOut*100) : 0;
  // counterparties
  const payee = {};
  for(const t of debits){ (payee[t.merchant]=payee[t.merchant]||[]).push(Math.abs(t.amount)); }
  const distinct = Object.keys(payee).length;
  const repeat = Object.values(payee).filter(v=>v.length>=2).length;
  const topMerch = Object.entries(payee).map(([m,v])=>[m,v.reduce((s,a)=>s+a,0),v.length])
    .sort((a,b)=>b[1]-a[1]).slice(0,6);
  // weekday
  const wd = {Mon:0,Tue:0,Wed:0,Thu:0,Fri:0,Sat:0,Sun:0};
  const names=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const byday = {};
  for(const t of debits){ const d=new Date(t.date);
    wd[names[d.getDay()]] += Math.abs(t.amount);
    byday[t.date]=(byday[t.date]||0)+Math.abs(t.amount); }
  const bigDay = Object.entries(byday).sort((a,b)=>b[1]-a[1])[0];
  const round100 = outs.filter(a=>a>=100 && a%100===0);
  const pings = rows.filter(t=>Math.abs(t.amount)<=2).length;
  const wkMax = Math.max(1, ...Object.values(wd));
  const order=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  const internal = monthFiltered().filter(t=>t.internal && t.amount<0);
  const internalTot = internal.reduce((s,t)=>s+Math.abs(t.amount),0);
  const chips = [
    ['Throughput', fmt(grossIn+grossOut), `in ${fmt(grossIn)} / out ${fmt(grossOut)}`],
    ['Concentration', pareto(3)+'%', `top 3 debits of outflow · top 10 = ${pareto(10)}%`],
    ['Counterparties', String(distinct), `${repeat} seen more than once`],
    ['Biggest day', bigDay?fmt(bigDay[1]):'—', bigDay?bigDay[0]:''],
    ['Round-number debits', String(round100.length), `${fmt(round100.reduce((s,a)=>s+a,0))} · often person-to-person`],
    ['Autopay/verify pings', String(pings), '≤ Rs 2 · mandate checks'],
    ['Internal transfers', internal.length?fmt(internalTot):'—', `${internal.length} pairs netted out of spend/income`],
  ];
  let html = '<div class="chips">' + chips.map(([k,v,s])=>
    `<div class="chip"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join('') + '</div>';
  html += '<div class="chip" style="margin-bottom:12px"><div class="k">Spend by weekday</div><div class="wkbar">' +
    order.map(d=>`<div class="wkcol"><div class="bar" style="height:${wd[d]/wkMax*32}px" title="${d} ${fmt(wd[d])}"></div><div class="lbl">${d[0]}</div></div>`).join('') + '</div></div>';
  html += '<div class="k" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em;margin:4px 0">Top counterparties by outflow</div>';
  html += topMerch.map(([m,tot,n])=>
    `<div class="spark"><div class="name" style="flex:1">${esc(m)}</div><div class="amt">${fmt(tot)} <span class="muted">×${n}</span></div></div>`).join('');
  document.getElementById('insights').innerHTML = html;
}

// ---- category breakdown (clickable) ---------------------------------------
function categorySpend(){
  const map = {};
  for(const t of real(monthFiltered())) if(t.amount<0){
    map[t.category]=(map[t.category]||0)+Math.abs(t.amount); }
  return Object.entries(map).sort((a,b)=>b[1]-a[1]);
}
function renderCats(){
  const rows = categorySpend();
  const max = Math.max(1, ...rows.map(r=>r[1]));
  document.getElementById('cats').innerHTML = rows.map(([c,v])=>{
    const w = (v/max*100).toFixed(1);
    const active = state.category===c ? ' active':'';
    return `<div class="catbar${active}" data-cat="${esc(c)}">
      <div class="name">${esc(c)}</div>
      <div class="track"><div class="fill" style="width:${w}%"></div></div>
      <div class="amt">${fmt(v)}</div></div>`;
  }).join('') || '<div class="muted">No spending in range.</div>';
  document.querySelectorAll('.catbar').forEach(el=>{
    el.onclick = ()=>{ const c = el.dataset.cat;
      state.category = state.category===c ? null : c; renderAll(); };
  });
}

// ---- per-category sparklines ----------------------------------------------
function sparkFor(cat, months){
  const vals = months.map(m => {
    let s=0; for(const t of T) if(t.category===cat && t.month===m && t.amount<0 && !t.internal) s+=Math.abs(t.amount);
    return s; });
  const max = Math.max(1, ...vals);
  const W=160,H=28;
  const pts = vals.map((v,i)=>`${(i/(Math.max(1,vals.length-1)))*W},${H-(v/max)*(H-2)-1}`).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5"/></svg>`;
}
function renderSparks(){
  const months = activeMonths();
  const cats = categorySpend().filter(([c])=> !state.category || c===state.category);
  document.getElementById('sparks').innerHTML = cats.map(([c,v])=>
    `<div class="spark"><div class="name">${esc(c)}</div>${sparkFor(c,months)}<div class="amt">${fmt(v)}</div></div>`
  ).join('') || '<div class="muted">Nothing to chart.</div>';
}

// ---- recurring commitments ------------------------------------------------
function median(a){ if(!a.length) return 0; const s=[...a].sort((x,y)=>x-y);
  const m=Math.floor(s.length/2); return s.length%2?s[m]:(s[m-1]+s[m])/2; }
function daysBetween(a,b){ return (new Date(b)-new Date(a))/86400000; }
function cadence(gap){
  const b=[['weekly',7,52],['fortnightly',14,26],['monthly',30,12],
           ['quarterly',91,4],['half-yearly',182,2],['yearly',365,1]];
  let best=b[0]; for(const x of b) if(Math.abs(gap-x[1])<Math.abs(gap-best[1])) best=x;
  if(Math.abs(gap-best[1])<=0.35*best[1]) return {name:best[0],mult:best[2]};
  return null;
}
function recurringList(){
  const rows = belowFiltered().filter(t=>t.amount<0 && !t.internal);
  const g={}; for(const t of rows){ (g[t.merchant]=g[t.merchant]||[]).push(t); }
  const out=[];
  for(const [m,items] of Object.entries(g)){
    if(items.length<3) continue;
    const amts=items.map(t=>Math.abs(t.amount)); const med=median(amts);
    if(med===0) continue;
    const within=amts.filter(a=>Math.abs(a-med)<=0.02*med).length;
    const dates=items.map(t=>t.date).filter(Boolean).sort();
    if(dates.length<2) continue;
    const gaps=[]; for(let i=1;i<dates.length;i++) gaps.push(daysBetween(dates[i-1],dates[i]));
    const cad=cadence(median(gaps)); if(!cad) continue;
    out.push({merchant:m, category:items[0].category, occ:items.length,
      median:med, stability:within/items.length, cadence:cad.name,
      annualised:med*cad.mult});
  }
  return out.sort((a,b)=>b.annualised-a.annualised);
}
function renderRecurring(){
  const rows=recurringList();
  document.getElementById('recurring').innerHTML = rows.length ?
    `<table><tr><th>Merchant</th><th>Category</th><th>Cadence</th>
      <th class="n">Typical</th><th class="n">Same-amount</th>
      <th class="n">Count</th><th class="n">Annualised</th></tr>` +
    rows.map(r=>`<tr><td>${esc(r.merchant)}</td><td>${esc(r.category)}</td>
      <td>${r.cadence}</td><td class="n">${fmt2(r.median)}</td>
      <td class="n"><span class="stab">${(r.stability*100).toFixed(0)}%</span></td>
      <td class="n">${r.occ}</td><td class="n">${fmt(r.annualised)}</td></tr>`).join('') +
    `</table>` : '<div class="muted">No recurring commitments detected in range.</div>';
}

// ---- outliers -------------------------------------------------------------
function renderOutliers(){
  const rows=belowFiltered().filter(t=>t.amount<0 && !t.internal);
  const byCat={}; for(const t of rows) (byCat[t.category]=byCat[t.category]||[]).push(t);
  const flagged=[];
  for(const [c,items] of Object.entries(byCat)){
    const vals=items.map(t=>Math.abs(t.amount)); if(vals.length<4) continue;
    const med=median(vals); const mad=median(vals.map(v=>Math.abs(v-med)))||1e-9;
    const thr=med+4*mad;
    for(const t of items) if(Math.abs(t.amount)>thr) flagged.push({...t,thr,med});
  }
  flagged.sort((a,b)=>Math.abs(b.amount)-Math.abs(a.amount));
  document.getElementById('outliers').innerHTML = flagged.length ?
    `<table><tr><th>Date</th><th>Description</th><th>Category</th>
      <th class="n">Amount</th><th class="n">Cat median</th></tr>` +
    flagged.map(t=>`<tr><td class="num">${t.date}</td><td>${esc(t.description)}</td>
      <td>${esc(t.category)}</td><td class="n neg">${fmt2(Math.abs(t.amount))}</td>
      <td class="n muted">${fmt2(t.med)}</td></tr>`).join('')+`</table>`
    : '<div class="muted">No outliers in range.</div>';
}

// ---- unrecognised merchants -----------------------------------------------
function renderUnrecognised(){
  const rows=belowFiltered().filter(t=>t.category==='Uncategorised');
  const g={}; for(const t of rows){ const k=t.merchant;
    if(!g[k]) g[k]={count:0,total:0,sample:t.description}; g[k].count++; g[k].total+=Math.abs(t.amount); }
  const entries=Object.entries(g).sort((a,b)=>b[1].total-a[1].total);
  const opts=DATA.categories.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  document.getElementById('unrecognised').innerHTML = entries.length ?
    entries.map(([m,info])=>`<div class="merchrow">
      <div class="m">${esc(m)} <span class="badge">&times;${info.count} &middot; ${fmt(info.total)}</span></div>
      <select data-merch="${esc(m)}"><option value="">— assign —</option>${opts}</select>
    </div>`).join('') : '<div class="muted">Everything in range is categorised.</div>';
  document.querySelectorAll('#unrecognised select').forEach(sel=>{
    sel.onchange=()=>{ const m=sel.dataset.merch;
      if(sel.value) overrides[m]=sel.value; else delete overrides[m]; };
  });
}
function buildRulesJSON(){
  const byCat={};
  for(const [m,cat] of Object.entries(overrides)){
    (byCat[cat]=byCat[cat]||[]).push(m.toLowerCase());
  }
  return JSON.stringify(byCat, null, 2);
}

// ---- transaction table ----------------------------------------------------
function renderTable(){
  const q=state.search.toLowerCase();
  const rows=belowFiltered().filter(t=>!q ||
    (t.description+' '+t.category).toLowerCase().includes(q))
    .sort((a,b)=> a.date<b.date?1:-1);
  const body=rows.map(t=>{
    const low = t.confidence==='low';
    const cat = esc(t.category) + (t.internal?' <span class="tag">internal</span>':'');
    return `<tr class="${low?'low':''}"><td class="num">${t.date}</td>
      <td>${esc(t.description)}</td><td>${cat}</td>
      <td class="n ${t.amount<0?'neg':'pos'}">${fmt2(t.amount)}</td>
      <td><span class="tag ${low?'low':''}">${t.confidence||''}</span></td></tr>`;
  }).join('');
  document.getElementById('txntable').innerHTML =
    `<tr><th>Date</th><th>Description</th><th>Category</th>
      <th class="n">Amount</th><th>Conf</th></tr>` + body;
}

// ---- reconcile banner + month selectors -----------------------------------
function renderReconcile(){
  const r=DATA.reconcile||{}; const el=document.getElementById('reconcile');
  if(r.ok===true) el.innerHTML=`<span class="reconcile ok">${esc(r.message)}</span>`;
  else if(r.ok===false) el.innerHTML=`<span class="reconcile bad">${esc(r.message)}</span>`;
  else el.innerHTML=`<span class="reconcile skip">${esc(r.message||'')}</span>`;
}
function renderActiveFilter(){
  const el=document.getElementById('activefilter');
  el.innerHTML = state.category ?
    `<span class="clearfilter" id="clr">filtered: ${esc(state.category)} &times;</span>` : '';
  const c=document.getElementById('clr'); if(c) c.onclick=()=>{state.category=null; renderAll();};
}

function renderAll(){
  renderStats(); renderFlow(); renderInsights(); renderCats(); renderSparks();
  renderRecurring(); renderOutliers(); renderUnrecognised();
  renderTable(); renderActiveFilter();
}

// ---- init -----------------------------------------------------------------
function init(){
  const mf=document.getElementById('mfrom'), mt=document.getElementById('mto');
  MONTHS.forEach((m,i)=>{ mf.add(new Option(m,i)); mt.add(new Option(m,i)); });
  mf.value=state.from; mt.value=state.to;
  mf.onchange=()=>{ state.from=Math.min(+mf.value,state.to); mf.value=state.from; renderAll(); };
  mt.onchange=()=>{ state.to=Math.max(+mt.value,state.from); mt.value=state.to; renderAll(); };
  document.getElementById('search').oninput=e=>{ state.search=e.target.value; renderTable(); };
  document.getElementById('copyrules').onclick=()=>{
    const j=buildRulesJSON(); const out=document.getElementById('rulesout');
    out.style.display='block'; out.textContent=j;
    if(navigator.clipboard) navigator.clipboard.writeText(j).catch(()=>{});
  };
  renderReconcile(); renderAlerts(); renderAll();
}
init();
</script>
</body>
</html>
"""
