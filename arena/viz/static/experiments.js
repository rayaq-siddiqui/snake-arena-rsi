"use strict";

const LINEAGES = ["hunter", "survivor", "trapper", "predictor", "opportunist"];
const COLORS = ["#f7768e", "#9ece6a", "#e0af68", "#7aa2f7", "#bb9af7"];
const lineageColor = (name) => COLORS[Math.max(0, LINEAGES.indexOf(name)) % COLORS.length];
const $ = (id) => document.getElementById(id);
let current = null;
let timer = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

const num = (x, digits = 3) => (x === null || x === undefined ? "–" : Number(x).toFixed(digits));
const ci = (c) => (c ? `[${num(c[0])}, ${num(c[1])}]` : "–");

async function loadRuns() {
  const runs = await api("/api/runs");
  $("status").textContent = `${runs.length} run${runs.length === 1 ? "" : "s"}`;
  const head = "<tr><th>Run</th><th>Status</th><th>Profile</th><th>Gen</th>" +
    "<th>Accepted</th><th>Minutes</th><th>Stop reason</th></tr>";
  $("runs").innerHTML = head + runs.map((r) =>
    `<tr data-run="${esc(r.id)}" class="${r.id === current ? "selected" : ""}">` +
    `<td><button class="link">${esc(r.id)}</button></td>` +
    `<td class="st-${esc(r.status)}">${esc(r.status)}</td><td>${esc(r.profile)}` +
    `${r.proposer && r.proposer !== "mixed" ? ` (${esc(r.proposer)})` : ""}</td>` +
    `<td>${r.generation}</td><td>${r.accepted ?? "–"}</td>` +
    `<td>${(r.seconds / 60).toFixed(1)}</td><td>${esc(r.stop_reason ?? "")}</td></tr>`).join("");
  return runs;
}

function chartSvg(progress, order, generations) {
  const points = order.flatMap((n) => progress[n] || []);
  if (!points.length) return '<p class="muted">The report has no progress yet.</p>';
  const W = 640, H = 240, L = 44, R = 12, T = 12, B = 30;
  const maxGen = Math.max(1, generations, ...points.map((p) => p.generation));
  const ys = points.flatMap((p) => (p.ci ? [p.ci[0], p.ci[1]] : [p.mean]));
  let lo = Math.min(0, ...ys), hi = Math.max(0.1, ...ys);
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (g) => L + (g / maxGen) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const parts = [`<svg viewBox="0 0 ${W} ${H}" class="chart" role="img" aria-label="accepted versions">`];
  for (let i = 0; i <= 4; i++) {
    const v = lo + ((hi - lo) * i) / 4;
    parts.push(`<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gridline"/>` +
      `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(2)}</text>`);
  }
  parts.push(`<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">generation (0–${maxGen})</text>`);
  for (const name of order) {
    const ps = (progress[name] || []).slice().sort((a, b) => a.generation - b.generation);
    if (!ps.length) continue;
    const color = lineageColor(name);
    const steps = ps.map((p, i) => {
      const next = i + 1 < ps.length ? ps[i + 1].generation : maxGen;
      return `${i ? "L" : "M"}${x(p.generation)},${y(p.mean)} L${x(next)},${y(p.mean)}`;
    }).join(" ");
    parts.push(`<path d="${steps}" fill="none" stroke="${color}" stroke-width="2"/>`);
    for (const p of ps) {
      parts.push(`<circle cx="${x(p.generation)}" cy="${y(p.mean)}" r="4" fill="${color}" ` +
        `stroke="#131824" stroke-width="2"><title>${esc(name)} v${p.version} (gen ${p.generation}): ` +
        `${num(p.mean)} ${ci(p.ci)}</title></circle>`);
    }
  }
  parts.push("</svg>");
  const legend = order.map((n) =>
    `<span class="legend-item"><i style="background:${lineageColor(n)}"></i>${esc(n)}</span>`).join("");
  return `<div class="legend">${legend}</div>` + parts.join("");
}

function matrixTable(m) {
  if (!m) return '<tr><td class="muted">Written by the report at the end of a run.</td></tr>';
  const head = `<tr><th>killer \\ victim</th>${m.snakes.map((s) => `<th>${esc(s)}</th>`).join("")}</tr>`;
  return head + m.kills.map((row, i) =>
    `<tr><th>${esc(m.snakes[i])}</th>${row.map((k) => `<td>${k}</td>`).join("")}</tr>`).join("") +
    `<tr><td colspan="${m.snakes.length + 1}" class="muted">${m.episodes} episodes; rows killed columns.</td></tr>`;
}

function timelines(lineages, order) {
  return order.map((name) => {
    const lin = lineages[name];
    const rows = lin.timeline.map((r) =>
      `<tr class="${r.accept ? "accepted" : ""}"><td>${r.generation}</td>` +
      `<td>${r.accept ? "accepted" : "rejected"} (${esc(r.stage)})</td><td>${esc(r.proposer)}</td>` +
      `<td>${esc(r.change)}</td><td>${num(r.dev_diff)}</td><td>${num(r.holdout_diff)} ${ci(r.holdout_ci)}</td></tr>`
    ).join("");
    return `<details${lin.accepted ? " open" : ""}><summary><i class="swatch" ` +
      `style="background:${lineageColor(name)}"></i>${esc(name)}: v${lin.version}, ` +
      `${lin.accepted} accepted of ${lin.timeline.length}</summary><table class="table">` +
      "<tr><th>Gen</th><th>Decision</th><th>Proposer</th><th>Change</th><th>Dev diff</th>" +
      `<th>Holdout diff (95% CI)</th></tr>${rows}</table></details>`;
  }).join("");
}

async function showRun(id) {
  current = id;
  const d = await api(`/api/runs/${encodeURIComponent(id)}`);
  const order = d.identity.lineages;
  $("detail").classList.remove("hidden");
  $("detail-title").textContent = `${d.id}: ${d.status}`;
  const gens = d.timing.length ? d.timing[d.timing.length - 1].generation : 0;
  $("detail-meta").textContent = `profile ${d.identity.profile.name}, ` +
    `run seed ${d.identity.run_seed}, generation ${gens}` +
    (d.stop_reason ? `, stopped: ${d.stop_reason}` : "") + (d.stop_file ? ", STOP requested" : "");
  $("stop").disabled = !(d.status === "running");
  const dash = $("dashboard");
  dash.classList.toggle("hidden", !d.dashboard);
  dash.href = `/api/runs/${encodeURIComponent(id)}/dashboard`;
  $("chart").innerHTML = d.progress ? chartSvg(d.progress, order, gens)
    : '<p class="muted">The chart appears when the run writes its report.</p>';
  $("matrix").innerHTML = matrixTable(d.matrix);
  $("timelines").innerHTML = timelines(d.lineages, order);
  $("log").textContent = d.log.join("\n") || "(no log: the run was started outside the viewer)";
  for (const tr of $("runs").querySelectorAll("tr[data-run]")) {
    tr.classList.toggle("selected", tr.dataset.run === id);
  }
  return d;
}

async function refresh() {
  try {
    const runs = await loadRuns();
    if (current) await showRun(current);
    const live = runs.some((r) => ["running", "stopping", "starting"].includes(r.status));
    clearTimeout(timer);
    if (live) timer = setTimeout(refresh, 3000);
  } catch (err) {
    $("status").textContent = err.message;
  }
}

$("runs").addEventListener("click", (ev) => {
  const tr = ev.target.closest("tr[data-run]");
  if (tr) showRun(tr.dataset.run).catch((err) => { $("status").textContent = err.message; });
});

$("start-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = Object.fromEntries(new FormData(ev.target).entries());
  $("form-error").textContent = "";
  try {
    const started = await api("/api/runs", body);
    current = started.id;
    await refresh();
  } catch (err) {
    $("form-error").textContent = err.message;
  }
});

$("stop").addEventListener("click", async () => {
  if (!current) return;
  await api(`/api/runs/${encodeURIComponent(current)}/stop`, {});
  await refresh();
});

refresh();
