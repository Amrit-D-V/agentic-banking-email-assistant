DASHBOARD_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Email Operations</title>
<style>
  :root {
    color-scheme: light;
    --brand: #004c8f; --brand-dark: #002f6c; --brand-accent: #ed1c24;
    --bg: #f3f5f8; --surface: #fcfcfb; --surface-2: #f1f3f6; --border: #dde2e9;
    --text: #0b0b0b; --text-2: #52514e; --text-3: #7a7974; --grid: #e6e8ec; --series-1: #2a78d6;
    --good: #0ca30c; --warning: #fab219; --critical: #d03b3b; --neutral: #9a9a95;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --bg: #111110; --surface: #1a1a19; --surface-2: #232321; --border: #33332f;
      --text: #f0efec; --text-2: #c3c2b7; --text-3: #8f8e86; --grid: #2a2a27; --series-1: #3987e5; --neutral: #7d7d77;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); font-size: 13px; line-height: 1.45; }
  header { background: linear-gradient(135deg, var(--brand-dark), var(--brand)); color: #fff; padding: 12px 20px;
           display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand .mark { background: var(--brand-accent); font-weight: 800; padding: 3px 8px; border-radius: 4px; }
  .brand h1 { font-size: 15px; font-weight: 700; }
  .nav { display: flex; align-items: center; gap: 16px; font-size: 12px; }
  .nav a { color: #fff; text-decoration: none; font-weight: 600; opacity: .9; }
  .nav a:hover { opacity: 1; text-decoration: underline; }
  #status { opacity: .85; }

  main { padding: 16px 20px 40px; max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
  .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .kpi .l { color: var(--text-2); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .4px; }
  .kpi .v { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .kpi .s { color: var(--text-3); font-size: 11px; }

  .grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr); gap: 14px; align-items: start; }
  @media (max-width: 1000px) { .grid { grid-template-columns: 1fr; } }
  .stack { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; min-width: 0; }
  .card > h2 { font-size: 13px; font-weight: 700; padding: 11px 14px; border-bottom: 1px solid var(--border); }
  .body { padding: 12px 14px; }

  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 11px; color: var(--text-2); margin-bottom: 6px; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  .chart { position: relative; }
  .chart svg { display: block; width: 100%; height: auto; }
  .tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
         padding: 6px 9px; font-size: 11px; box-shadow: 0 4px 12px rgba(0,0,0,.12); white-space: nowrap; display: none; }

  .tbl { max-height: 460px; overflow: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { position: sticky; top: 0; text-align: left; color: var(--text-2); font-weight: 600; font-size: 11px; text-transform: uppercase;
       padding: 7px 10px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
  td { padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  #feed tr[data-id] { cursor: pointer; } #feed tr[data-id]:hover td { background: var(--surface-2); }
  code { font-family: ui-monospace, Menlo, monospace; font-size: 11px; }
  .muted { color: var(--text-3); }
  .empty { color: var(--text-3); text-align: center; padding: 18px 0; }

  .pill { display: inline-flex; align-items: center; gap: 5px; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;
          border: 1px solid var(--border); background: var(--surface-2); white-space: nowrap; }
  .pill::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--neutral); }
  .pill.good::before { background: var(--good); } .pill.warning::before { background: var(--warning); }
  .pill.critical::before { background: var(--critical); } .pill.blue::before { background: var(--series-1); }
  .tag { display: inline-block; padding: 0 6px; border-radius: 4px; background: var(--surface-2); border: 1px solid var(--border); font-size: 11px; margin: 1px 2px 1px 0; }

  .field { margin-bottom: 14px; }
  .field:last-child { margin-bottom: 0; }
  .field > .lbl { display: block; font-size: 11px; font-weight: 700; color: var(--text-2); text-transform: uppercase; letter-spacing: .4px; margin-bottom: 6px; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .seg button { background: var(--surface); color: var(--text-2); border: 0; border-right: 1px solid var(--border); padding: 5px 11px; font-size: 12px; cursor: pointer; }
  .seg button:last-child { border-right: 0; }
  .seg button.on { background: var(--brand); color: #fff; font-weight: 600; }
  select { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 12px; flex: 1; min-width: 0; }
  .btn { background: var(--brand); color: #fff; border: 0; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
  .btn:disabled { opacity: .5; cursor: default; }
  .btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
  .btn.ok { background: var(--good); }
  .linkbtn { background: none; border: 0; color: var(--critical); font-size: 12px; cursor: pointer; padding: 0; }
  .check { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 12px; }
  .check input { accent-color: var(--brand); width: 16px; height: 16px; }
  .progress { height: 6px; background: var(--surface-2); border-radius: 4px; overflow: hidden; margin-top: 6px; }
  .progress > div { height: 100%; background: var(--series-1); transition: width .3s; }

  .hrow { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--border); }
  .hrow:last-child { border-bottom: 0; }
  .review { border: 1px solid var(--border); border-radius: 6px; padding: 10px; margin-bottom: 8px; }
  pre { white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, Menlo, monospace; font-size: 11px;
        background: var(--surface-2); border-radius: 4px; padding: 8px; margin: 6px 0; max-height: 320px; overflow: auto; }

  .toast { position: fixed; bottom: 18px; right: 18px; background: var(--text); color: var(--surface); padding: 10px 14px; border-radius: 6px;
           font-size: 12px; opacity: 0; transition: .25s; z-index: 50; max-width: 360px; pointer-events: none; }
  .toast.show { opacity: 1; }
  .scrim { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: none; z-index: 30; }
  .drawer { position: fixed; top: 0; right: 0; height: 100%; width: min(640px, 100%); background: var(--surface); z-index: 31;
            transform: translateX(100%); transition: transform .25s; overflow-y: auto; border-left: 1px solid var(--border); }
  .drawer.open { transform: none; } .scrim.open { display: block; }
  .drawer .head { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 14px 18px; border-bottom: 1px solid var(--border); }
  .drawer .sec { padding: 12px 18px; border-bottom: 1px solid var(--border); }
  .drawer h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .4px; color: var(--text-2); margin-bottom: 6px; }
  .kv { display: grid; grid-template-columns: 110px 1fr; gap: 4px 10px; font-size: 12px; }
  .kv > div:nth-child(odd) { color: var(--text-3); }
  .tl { display: grid; grid-template-columns: 150px 1fr 60px; gap: 4px 8px; align-items: center; font-size: 11px; }
  .tl .track { position: relative; height: 10px; background: var(--surface-2); border-radius: 3px; }
  .tl .bar { position: absolute; top: 0; height: 100%; background: var(--series-1); border-radius: 3px; min-width: 2px; }
  @media (max-width: 600px) { main { padding: 12px 16px 30px; } }
</style>
</head>
<body>
<header>
  <div class="brand"><span class="mark">HDFC</span><h1>Email Automation Dashboard</h1></div>
  <nav class="nav">
    <span id="status">Connecting...</span>
    <a href="/docs" target="_blank" rel="noopener">API Docs</a>
  </nav>
</header>

<main>
  <section class="kpis" id="kpis"></section>

  <div class="grid">
    <div class="stack">
      <div class="card">
        <h2>Emails by outcome (last 30 minutes)</h2>
        <div class="body"><div class="legend" id="legend"></div><div class="chart" id="chart"></div></div>
      </div>
      <div class="card">
        <h2>Recent emails</h2>
        <div class="tbl"><table>
          <thead><tr><th>Time</th><th>Sender</th><th>Request</th><th>Outcome</th><th class="num">Time taken</th></tr></thead>
          <tbody id="feed"></tbody>
        </table></div>
      </div>
    </div>

    <div class="stack">
      <div class="card">
        <h2>Controls</h2>
        <div class="body">
          <div class="field">
            <span class="lbl">Run a test email</span>
            <div class="row"><select id="scenario" aria-label="Scenario"></select><button class="btn" id="runOne" type="button">Run</button></div>
            <div class="row" style="margin-top:8px"><button class="btn ghost" id="runAll" type="button">Run all scenarios</button></div>
            <div id="job"></div>
          </div>
          <div class="field">
            <span class="lbl">Core banking connection</span>
            <div class="seg" id="transport"><button type="button" data-v="inprocess">Direct</button><button type="button" data-v="http">REST</button><button type="button" data-v="mcp">MCP</button></div>
          </div>
          <div class="field">
            <label class="check"><input type="checkbox" id="hitl"> Hold flagged replies for human approval</label>
          </div>
          <div class="field">
            <span class="lbl">Gmail worker</span>
            <div class="row"><span id="wpill" class="pill">-</span>
              <button class="btn ok" id="wstart" type="button">Start</button><button class="btn ghost" id="wstop" type="button">Stop</button></div>
            <div class="muted" id="wstats" style="margin-top:6px;font-size:11px"></div>
          </div>
          <div class="field"><button class="linkbtn" id="reset" type="button">Clear all data</button></div>
        </div>
      </div>

      <div class="card" id="failedCard" style="display:none">
        <h2 id="failedTitle">Failed emails</h2>
        <div class="body" id="failed"></div>
      </div>

      <div class="card">
        <h2 id="reviewTitle">Waiting for approval</h2>
        <div class="body" id="reviews"></div>
      </div>

      <div class="card">
        <h2>System health</h2>
        <div class="body" id="health"></div>
      </div>
    </div>
  </div>
</main>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" aria-label="Email details"></aside>
<div class="toast" id="toast" role="status"></div>

<script>
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (n, d = 0) => Number(n || 0).toLocaleString("en-IN", {maximumFractionDigits: d, minimumFractionDigits: d});
const dur = (ms) => ms >= 1000 ? fmt(ms / 1000, 1) + " s" : fmt(ms) + " ms";
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
let lastOk = 0;

async function api(path, opts = {}) {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 3000); }
const pill = (cls, text) => `<span class="pill ${cls}">${esc(text)}</span>`;

const OUTCOMES = {
  RESOLVED: ["good", "Resolved", "--good"], PARTIAL: ["warning", "Partial", "--warning"],
  NEEDS_INFO: ["", "Needs customer info", "--neutral"], ROUTED: ["blue", "Sent to officer", "--series-1"],
  FAILED: ["critical", "System failure", "--critical"],
};
const INTENTS = { BALANCE_ENQUIRY: "Balance", CARD_TRANSACTIONS: "Card transactions", STATEMENT_REQUEST: "Statement",
                  POLICY_INQUIRY: "Policy question", GENERAL_INQUIRY: "Other" };

function renderKpis(m) {
  const o = m.outcomes;
  const tiles = [
    ["Emails processed", fmt(m.total_processed), `${fmt(m.throughput_per_min_5m, 1)} per minute recently`],
    ["Answered automatically", fmt(m.automation_rate_pct, 1) + "%", `${fmt(o.RESOLVED)} fully, ${fmt(o.PARTIAL)} partly`],
    ["Average response time", dur(m.avg_latency_ms), "from email in to reply out"],
    ["Waiting for approval", fmt(m.review_pending), "flagged replies on hold"],
    ["System failures", fmt(o.FAILED), `${fmt(o.NEEDS_INFO)} asked customer for details`],
  ];
  $("kpis").innerHTML = tiles.map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
}

function renderChart(tl, totals) {
  const keys = Object.keys(OUTCOMES);
  $("legend").innerHTML = keys.map(k => `<span><i style="background:${css(OUTCOMES[k][2])}"></i>${OUTCOMES[k][1]} <b>${fmt(totals[k])}</b></span>`).join("");
  const W = 760, H = 200, pad = {l: 30, r: 6, t: 8, b: 22};
  const sums = tl.map(b => keys.reduce((s, k) => s + b[k], 0));
  const peak = Math.max(...sums, 0), max = peak <= 4 ? 4 : Math.ceil(peak / 4) * 4;
  const bw = (W - pad.l - pad.r) / tl.length, barW = Math.max(4, bw - 6), ih = H - pad.t - pad.b;
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const y = H - pad.b - ih * i / 4;
    g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="${css("--grid")}"/>`;
    g += `<text x="${pad.l - 6}" y="${y + 3}" text-anchor="end" font-size="10" fill="${css("--text-3")}">${fmt(max * i / 4)}</text>`;
  }
  tl.forEach((b, i) => {
    const x = pad.l + i * bw + (bw - barW) / 2;
    let y = H - pad.b;
    const segs = keys.filter(k => b[k] > 0);
    segs.forEach((k, j) => {
      const h = ih * b[k] / max, top = j === segs.length - 1, gap = j ? 2 : 0, r = top ? Math.min(4, barW / 2, h) : 0, y0 = y - h;
      g += top
        ? `<path d="M${x},${y - gap} L${x},${y0 + r} Q${x},${y0} ${x + r},${y0} L${x + barW - r},${y0} Q${x + barW},${y0} ${x + barW},${y0 + r} L${x + barW},${y - gap} Z" fill="${css(OUTCOMES[k][2])}"/>`
        : `<rect x="${x}" y="${y0}" width="${barW}" height="${Math.max(0, h - gap)}" fill="${css(OUTCOMES[k][2])}"/>`;
      y = y0;
    });
    if (i % 5 === 4) g += `<text x="${x + barW / 2}" y="${H - 6}" text-anchor="middle" font-size="10" fill="${css("--text-3")}">${esc(b.t)}</text>`;
    g += `<rect data-i="${i}" x="${pad.l + i * bw}" y="${pad.t}" width="${bw}" height="${ih}" fill="transparent"/>`;
  });
  const el = $("chart");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Emails per minute by outcome">${g}</svg><div class="tip"></div>`;
  const tip = el.querySelector(".tip");
  el.querySelectorAll("[data-i]").forEach(r => {
    r.onmousemove = (e) => {
      const i = +r.dataset.i, b = tl[i], box = el.getBoundingClientRect();
      tip.innerHTML = `<b>${esc(b.t)}</b> · ${fmt(sums[i])} emails` + keys.filter(k => b[k]).map(k => `<div>${OUTCOMES[k][1]}: <b>${b[k]}</b></div>`).join("");
      tip.style.display = "block";
      tip.style.left = Math.max(0, Math.min(e.clientX - box.left + 12, box.width - tip.offsetWidth)) + "px";
      tip.style.top = (e.clientY - box.top - tip.offsetHeight - 8) + "px";
    };
    r.onmouseleave = () => tip.style.display = "none";
  });
}

function renderFeed(rows) {
  $("feed").innerHTML = rows.length ? rows.map(r => {
    const [cls, label] = OUTCOMES[r.outcome] || ["", r.outcome];
    const urgent = r.sentiment === "NEGATIVE_URGENT" ? ' <span class="tag">urgent</span>' : "";
    return `<tr data-id="${esc(r.email_id)}" tabindex="0">
      <td><code>${esc((r.timestamp || "").slice(11, 19))}</code></td>
      <td><code>${esc(r.sender_masked)}</code></td>
      <td>${r.intents.map(i => `<span class="tag">${esc(INTENTS[i] || i)}</span>`).join("")}${urgent}</td>
      <td>${pill(cls, label)}</td>
      <td class="num">${dur(r.latency_ms)}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">No emails yet. Use "Run a test email" or start the Gmail worker.</td></tr>`;
  document.querySelectorAll("#feed tr[data-id]").forEach(tr => {
    tr.onclick = () => openEmail(tr.dataset.id);
    tr.onkeydown = (e) => { if (e.key === "Enter") openEmail(tr.dataset.id); };
  });
}

function renderReviews(items, hitlOn) {
  const pending = items.filter(i => i.status === "PENDING_APPROVAL");
  $("reviewTitle").textContent = `Waiting for approval (${pending.length})`;
  $("reviews").innerHTML = pending.length ? pending.slice(0, 6).map(i => `<div class="review">
      <div><code>${esc(i.sender_masked)}</code></div>
      <div class="muted" style="margin:2px 0 4px">${esc(i.subject)}</div>
      ${i.reasons.map(r => `<span class="tag">${esc(r)}</span>`).join("")}
      <details><summary class="muted" style="cursor:pointer;margin-top:4px">Show reply</summary><pre>${esc(i.draft)}</pre></details>
      <div class="row" style="margin-top:6px">
        <button class="btn ok" type="button" data-approve="${esc(i.email_id)}">Approve</button>
        <button class="btn ghost" type="button" data-reject="${esc(i.email_id)}">Reject</button></div></div>`).join("")
    : `<div class="muted">${hitlOn ? "Nothing waiting." : "Approval is off: flagged replies are sent automatically."}</div>`;
  document.querySelectorAll("[data-approve]").forEach(b => b.onclick = () => decide(b.dataset.approve, "approve"));
  document.querySelectorAll("[data-reject]").forEach(b => b.onclick = () => decide(b.dataset.reject, "reject"));
}

const HEALTH = { ONLINE: "good", DEGRADED: "warning", OFFLINE: "critical" };
function renderHealth(h) {
  $("health").innerHTML = Object.entries(h.components).map(([name, c]) =>
    `<div class="hrow"><div><div>${esc(name)}</div><div class="muted" style="font-size:11px">${esc(c.detail)}</div></div>${pill(HEALTH[c.status] || "", c.status)}</div>`).join("");
}

function renderWorker(w) {
  $("wpill").outerHTML = `<span id="wpill" class="pill ${w.running ? "good" : ""}">${w.running ? "Running" : w.configured ? "Stopped" : "Not configured"}</span>`;
  $("wstart").disabled = w.running || !w.configured;
  $("wstop").disabled = !w.running;
  $("wstats").innerHTML = !w.configured ? "Add EMAIL_USER and EMAIL_PASS to .env to enable."
    : `${esc(w.mailbox)} · ${fmt(w.processed)} processed · ${fmt(w.replied)} replied · queue ${fmt(w.queue_depth)}`
      + (w.skipped_duplicates ? ` · ${fmt(w.skipped_duplicates)} duplicates skipped` : "")
      + (w.failed ? ` · ${fmt(w.failed)} failed` : "") + (w.last_error ? `<br><span style="color:var(--critical)">${esc(w.last_error)}</span>` : "");
}

function renderConfig(c) {
  document.querySelectorAll("#transport button").forEach(b => b.classList.toggle("on", b.dataset.v === c.BANKING_API_TRANSPORT));
  $("hitl").checked = c.HITL_ENABLED;
}

async function openEmail(id) {
  try {
    const r = await api(`/api/v1/ops/records/${encodeURIComponent(id)}`);
    const vals = (r.validations || []).map(v =>
      `<div>${esc(v.entity.replace(/_/g, " "))}</div><div><code>${esc(v.value || "not given")}</code> ${pill(v.status === "VALID" ? "good" : "critical", v.status)} <span class="muted">${esc(v.reason || "")}</span></div>`).join("");
    const calls = (r.api_calls || []).map(c => `<tr><td>${esc(c.api)}</td><td>${pill(c.status === "SUCCESS" ? "good" : "critical", c.status)}</td><td class="num">${fmt(c.ms, 1)} ms</td><td>${esc(c.transport)}</td></tr>`).join("");
    $("drawer").innerHTML = `
      <div class="head"><div><b>${esc(r.subject)}</b><div class="muted">${esc(r.sender_masked)} · ${esc((r.timestamp || "").replace("T", " ").slice(0, 19))}</div></div>
        <button class="btn ghost" type="button" id="close">Close</button></div>
      <div class="sec"><h3>What the agents understood</h3><div class="kv">
        <div>Requests</div><div>${(r.detected_intents || []).map(i => `<span class="tag">${esc(INTENTS[i] || i)} ${fmt((r.intent_confidences || {})[i] * 100)}%</span>`).join("")}</div>
        <div>Tone</div><div>${esc(r.sentiment)} <span class="muted">${esc(r.sentiment_reason)}</span></div>
        ${vals}
        <div>Review</div><div>${r.requires_human_review ? esc(r.review_reasons.join(", ")) : "Not needed"}</div>
        <div>Time taken</div><div>${dur(r.total_execution_ms)}</div></div></div>
      ${timeline(r)}
      <div class="sec"><h3>Bank API calls</h3>${calls ? `<table><tbody>${calls}</tbody></table>` : '<span class="muted">None needed</span>'}</div>
      <div class="sec"><h3>Reply sent to the customer</h3><pre>${esc(r.response_masked)}</pre></div>
      <div class="sec"><details><summary class="muted" style="cursor:pointer">Agent step-by-step trace</summary><pre>${esc((r.execution_trace || []).join("\n"))}</pre></details></div>`;
    $("drawer").classList.add("open"); $("scrim").classList.add("open");
    $("close").onclick = closeEmail;
    history.replaceState(null, "", "#email=" + encodeURIComponent(id));
  } catch (e) { toast("Could not load email: " + e.message); }
}
function timeline(r) {
  const t = r.agent_timings || [];
  if (!t.length) return "";
  const total = Math.max(r.total_execution_ms || 0, ...t.map(x => x.start_ms + x.ms), 1);
  const name = (a) => a.replace(/Agent$/, "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  return `<div class="sec"><h3>Agent timeline</h3><div class="tl">` + t.map(x =>
    `<div>${esc(name(x.agent))}</div><div class="track"><div class="bar" style="left:${100 * x.start_ms / total}%;width:${100 * x.ms / total}%"></div></div><div style="text-align:right">${dur(x.ms)}</div>`
  ).join("") + `</div></div>`;
}

function renderFailed(items) {
  $("failedCard").style.display = items.length ? "" : "none";
  $("failedTitle").textContent = `Failed emails (${items.length})`;
  $("failed").innerHTML = items.slice(0, 6).map(i => `<div class="review">
      <div><code>${esc(i.sender)}</code> <span class="muted">· ${esc(i.failed_at.replace("T", " "))}</span></div>
      <div class="muted" style="margin:2px 0 4px">${esc(i.subject)}</div>
      <div style="color:var(--critical);font-size:11px">${esc(i.error)}</div>
      <div class="row" style="margin-top:6px"><button class="btn" type="button" data-retry="${i.id}">Retry</button></div></div>`).join("");
  document.querySelectorAll("[data-retry]").forEach(b => b.onclick = () => busy(b, async () => {
    const r = await api(`/api/v1/ops/failed/${b.dataset.retry}/retry`, {method: "POST"});
    toast(`Retried: ${r.delivery}`); refresh();
  }));
}

function closeEmail() { $("drawer").classList.remove("open"); $("scrim").classList.remove("open"); history.replaceState(null, "", location.pathname); }
$("scrim").onclick = closeEmail;
document.addEventListener("keydown", e => { if (e.key === "Escape") closeEmail(); });

async function setConfig(patch, msg) {
  try { renderConfig(await api("/api/v1/ops/config", {method: "POST", body: JSON.stringify(patch)})); toast(msg); loadHealth(); }
  catch (e) { toast(e.message); }
}
document.querySelectorAll("#transport button").forEach(b => b.onclick = () => setConfig({BANKING_API_TRANSPORT: b.dataset.v}, `Core banking via ${b.textContent}`));
$("hitl").onchange = (e) => setConfig({HITL_ENABLED: e.target.checked}, e.target.checked ? "Flagged replies will wait for approval" : "Flagged replies are sent automatically");

async function busy(btn, fn) { btn.disabled = true; try { await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; } }
$("runOne").onclick = () => busy($("runOne"), async () => {
  const r = await api(`/api/v1/ops/scenarios/${$("scenario").value}/run`, {method: "POST"});
  await refresh(); openEmail(r.email_id);
});
$("runAll").onclick = () => busy($("runAll"), async () => { await api("/api/v1/ops/run-all", {method: "POST"}); refresh(); });
$("wstart").onclick = () => busy($("wstart"), async () => { renderWorker(await api("/api/v1/ops/worker/start", {method: "POST"})); toast("Gmail worker started"); loadHealth(); });
$("wstop").onclick = () => busy($("wstop"), async () => { renderWorker(await api("/api/v1/ops/worker/stop", {method: "POST"})); toast("Gmail worker stopping"); loadHealth(); });
$("reset").onclick = async () => { if (confirm("Clear all processed emails and the approval queue?")) { await api("/api/v1/ops/reset", {method: "POST"}); toast("Cleared"); refresh(); } };
async function decide(id, action) {
  try { const r = await api(`/api/v1/ops/reviews/${encodeURIComponent(id)}/${action}`, {method: "POST", body: "{}"}); toast(`${r.status.toLowerCase()}: ${r.delivery}`); refresh(); }
  catch (e) { toast(e.message); }
}

function renderJob(jobs) {
  const j = jobs.find(x => x.status === "RUNNING");
  $("job").innerHTML = j ? `<div class="muted" style="margin-top:8px;font-size:11px">Running ${fmt(j.done)} of ${fmt(j.total)}...</div><div class="progress"><div style="width:${100 * j.done / j.total}%"></div></div>` : "";
}

async function refresh() {
  try {
    const [m, rv, w, cfg, jobs, failed] = await Promise.all([
      api("/api/v1/ops/metrics"), api("/api/v1/ops/reviews"), api("/api/v1/ops/worker"), api("/api/v1/ops/config"),
      api("/api/v1/ops/jobs"), api("/api/v1/ops/failed")]);
    renderKpis(m); renderChart(m.timeline, m.outcomes); renderFeed(m.recent);
    renderReviews(rv, cfg.HITL_ENABLED); renderWorker(w); renderConfig(cfg); renderJob(jobs); renderFailed(failed);
    lastOk = Date.now();
  } catch (e) { $("status").textContent = "Disconnected"; }
}
async function loadHealth() { try { renderHealth(await api("/api/v1/ops/health")); } catch (e) {} }
setInterval(() => { if (lastOk) $("status").textContent = `Updated ${Math.round((Date.now() - lastOk) / 1000)}s ago`; }, 1000);

(async () => {
  try {
    const sc = await api("/api/v1/ops/scenarios");
    $("scenario").innerHTML = sc.map(s => `<option value="${esc(s.key)}">${esc(s.title)}</option>`).join("");
  } catch (e) { toast("Backend unavailable"); }
  await refresh(); loadHealth();
  if (location.hash.startsWith("#email=")) openEmail(decodeURIComponent(location.hash.slice(7)));
  setInterval(refresh, 3000); setInterval(loadHealth, 15000);
})();
</script>
</body>
</html>
"""
