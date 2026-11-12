"use strict";

// Snake Arena viewer. The server computes ticks only when asked; this page decides how
// fast to ask and how to draw. Pause and speed therefore never change a match's result.

const COLORS = ["#f7768e", "#9ece6a", "#e0af68", "#7aa2f7", "#bb9af7", "#7dcfff", "#ff9e64", "#f5a8d4"];
const BASE_TPS = 10;
const MAX_TICKS_PER_FRAME = 400;
const FEED_LIMIT = 150;

const $ = (sel) => document.querySelector(sel);
const canvas = $("#board");
const ctx = canvas.getContext("2d");
const form = $("#settings");

const view = {
  gen: 0,
  meta: null,
  queue: [],
  prev: null,
  cur: null,
  nextTick: 1,
  serverDone: false,
  fetching: false,
  playing: true,
  speed: "5",
  lastTickAt: 0,
  effects: [],
  summary: null,
  lastBoardUpdate: 0,
};

const fmt = (n) => n.toLocaleString("en-US");
const seatColor = (id) => COLORS[Number(id.slice(1)) % COLORS.length];
const snakeMeta = (id) => (view.meta && view.meta.snakes.find((s) => s.id === id)) || null;
const colorOf = (id) => (snakeMeta(id) && snakeMeta(id).color) || seatColor(id);

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

function showError(message) {
  $("#form-error").textContent = message || "";
}

// ---------- match lifecycle ----------

function formSettings() {
  const data = new FormData(form);
  const config = {};
  for (const key of ["width", "height", "num_snakes", "snake_length", "score_target", "respawn_delay", "max_ticks"]) {
    config[key] = Number(data.get(key));
  }
  return { seed: Number(data.get("seed")), policy: data.get("policy"), config };
}

function fillForm(seed, config, policy) {
  form.elements.seed.value = seed;
  for (const [key, value] of Object.entries(config)) {
    if (form.elements[key]) form.elements[key].value = value;
  }
  if (policy && [...form.elements.policy.options].some((o) => o.value === policy)) {
    form.elements.policy.value = policy;
  }
}

async function start(body) {
  showError("");
  let meta;
  try {
    meta = await api("/api/match", body);
  } catch (err) {
    showError(err.message);
    return;
  }
  view.gen += 1;
  Object.assign(view, {
    meta,
    queue: [],
    prev: null,
    cur: meta.frame,
    nextTick: 1,
    serverDone: false,
    fetching: false,
    effects: [],
    summary: null,
    lastTickAt: performance.now(),
  });
  fillForm(meta.seed, meta.config, meta.lineup);
  $("#feed").innerHTML = "";
  $("#banner").classList.add("hidden");
  $("#download").disabled = meta.mode !== "live";
  resize();
  updateBoard(true);
  setPlaying(true);
}

async function fill() {
  if (view.fetching || view.serverDone || !view.meta) return;
  const want = view.speed === "max" ? 4000 : Math.max(60, BASE_TPS * Number(view.speed) * 3);
  if (view.queue.length >= want / 2) return;
  view.fetching = true;
  const gen = view.gen;
  const count = Math.min(5000, want);
  try {
    const data = await api(`/api/match/${view.meta.id}/frames?from=${view.nextTick}&count=${count}`);
    if (gen !== view.gen) return;
    if (data.frames.length) {
      view.queue.push(...data.frames);
      view.nextTick = data.frames[data.frames.length - 1].t + 1;
    }
    if (data.finished && data.frames.length < count) {
      view.serverDone = true;
      view.summary = data.summary;
    }
  } catch (err) {
    if (gen === view.gen) {
      showError(err.message);
      view.serverDone = true;
    }
  } finally {
    if (gen === view.gen) view.fetching = false;
  }
}

async function finishNow() {
  if (!view.meta) return;
  const gen = view.gen;
  try {
    const data = await api(`/api/match/${view.meta.id}/finish`, {});
    if (gen !== view.gen) return;
    view.queue = [];
    view.prev = null;
    view.cur = data.frame;
    view.serverDone = true;
    view.summary = data.summary;
    handleEvents(data.frame);
    updateBoard(true);
    showEnd();
  } catch (err) {
    showError(err.message);
  }
}

// ---------- playback ----------

function advance() {
  const next = view.queue.shift();
  if (!next) return false;
  view.prev = view.cur;
  view.cur = next;
  handleEvents(next);
  return true;
}

function atEnd() {
  return view.serverDone && view.queue.length === 0;
}

function tick(now) {
  if (view.meta && view.playing && !atEnd()) {
    if (view.speed === "max") {
      let n = 0;
      while (n < MAX_TICKS_PER_FRAME && advance()) n += 1;
      view.lastTickAt = now;
    } else {
      const rate = BASE_TPS * Number(view.speed);
      let due = Math.floor(((now - view.lastTickAt) * rate) / 1000);
      if (due > 0) {
        let moved = 0;
        while (moved < due && advance()) moved += 1;
        view.lastTickAt = moved < due ? now : view.lastTickAt + (due * 1000) / rate;
      }
    }
  }
  if (view.meta && atEnd() && view.summary && $("#banner").classList.contains("hidden")) showEnd();
  fill();
  draw(now);
  updateBoard(false);
  requestAnimationFrame(tick);
}

function setPlaying(on) {
  view.playing = on;
  view.lastTickAt = performance.now();
  $("#play").textContent = on ? "Pause" : "Play";
}

// ---------- events, feed and effects ----------

function handleEvents(frame) {
  const deaths = frame.ev.filter((e) => e.type === "death");
  const lines = [];
  const grouped = new Set();
  for (const d of deaths) {
    if (grouped.has(d.victim)) continue;
    if (d.killer) {
      lines.push(`<b style="color:${colorOf(d.killer)}">${label(d.killer)}</b> eliminated <b style="color:${colorOf(d.victim)}">${label(d.victim)}</b>`);
    } else if (d.cause === "head_on" || d.cause === "head_swap") {
      const group = d.cause === "head_on"
        ? deaths.filter((o) => o.cause === "head_on" && o.cell[0] === d.cell[0] && o.cell[1] === d.cell[1])
        : deaths.filter((o) => o.cause === "head_swap" && (o.victim === d.victim || isSwapPartner(o, d, frame)));
      group.forEach((o) => grouped.add(o.victim));
      const names = group.map((o) => `<b style="color:${colorOf(o.victim)}">${label(o.victim)}</b>`);
      lines.push(`${names.join(d.cause === "head_on" ? " × " : " ⇄ ")} — ${d.cause === "head_on" ? "head-on" : "head-swap"}, no killer`);
    } else {
      const what = d.cause === "wall" ? "hit the wall" : "ran into itself";
      lines.push(`<b style="color:${colorOf(d.victim)}">${label(d.victim)}</b> ${what}`);
    }
    view.effects.push({ cell: d.cell, color: colorOf(d.victim), born: performance.now() });
  }
  if (view.effects.length > 64) view.effects.splice(0, view.effects.length - 64);
  const feed = $("#feed");
  for (const text of lines) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="tick">${fmt(frame.t)}</span>${text}`;
    feed.prepend(li);
  }
  while (feed.children.length > FEED_LIMIT) feed.lastChild.remove();
}

function isSwapPartner(o, d, frame) {
  const prevSnakes = view.prev ? view.prev.snakes : [];
  const head = (id) => {
    const s = prevSnakes.find((p) => p.id === id);
    return s && s.b.length ? s.b[0] : null;
  };
  const ho = head(o.victim);
  const hd = head(d.victim);
  return ho && hd && o.cell[0] === hd[0] && o.cell[1] === hd[1] && d.cell[0] === ho[0] && d.cell[1] === ho[1];
}

function label(id) {
  const m = snakeMeta(id);
  return (m && m.label) || id;
}

function showEnd() {
  const s = view.summary;
  if (!s) return;
  const banner = $("#banner");
  const top = s.standings.filter((x) => x.rank === 1);
  let text;
  if (s.end_reason === "score_target") {
    text = top.length === 1 ? `${top[0].snake} wins with ${top[0].kills} kills` : `Tie for first at ${top[0].kills} kills`;
  } else if (s.end_reason === "tick_cap") {
    text = top.length === 1
      ? `Tick cap reached — ${top[0].snake} leads with ${top[0].kills} kills`
      : `Tick cap reached — tied at ${top[0].kills} kills`;
  } else {
    text = `Replay ended at tick ${fmt(s.tick)}`;
  }
  banner.textContent = text;
  banner.classList.remove("hidden");
}

// ---------- drawing ----------

function resize() {
  const dpr = window.devicePixelRatio || 1;
  const size = Math.max(100, Math.round(canvas.clientWidth * dpr));
  if (canvas.width !== size) {
    canvas.width = size;
    canvas.height = size;
  }
}

function draw(now) {
  if (!view.meta || !view.cur) return;
  resize();
  const { width: W, height: H } = view.meta.config;
  const cell = Math.min(canvas.width / W, canvas.height / H);
  const ox = (canvas.width - cell * W) / 2;
  const oy = (canvas.height - cell * H) / 2;
  ctx.fillStyle = "#0b0e14";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#0f1320";
  ctx.fillRect(ox, oy, cell * W, cell * H);

  if ($("#grid").checked && cell >= 5) {
    ctx.strokeStyle = "#1b2233";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x <= W; x++) { ctx.moveTo(ox + x * cell, oy); ctx.lineTo(ox + x * cell, oy + H * cell); }
    for (let y = 0; y <= H; y++) { ctx.moveTo(ox, oy + y * cell); ctx.lineTo(ox + W * cell, oy + y * cell); }
    ctx.stroke();
  }

  const rate = view.speed === "max" ? Infinity : BASE_TPS * Number(view.speed);
  const smooth = $("#smooth").checked && view.playing && rate <= 50 && view.prev;
  const alpha = smooth ? Math.min(1, ((now - view.lastTickAt) * rate) / 1000) : 1;

  for (const s of view.cur.snakes) {
    if (!s.b.length) continue;
    const before = view.prev && view.prev.snakes.find((p) => p.id === s.id);
    const lerp = smooth && before && before.life === s.life && before.b.length === s.b.length;
    const points = s.b.map((c, i) => lerp
      ? [before.b[i][0] + (c[0] - before.b[i][0]) * alpha, before.b[i][1] + (c[1] - before.b[i][1]) * alpha]
      : c);
    const color = colorOf(s.id);
    const pad = Math.max(0.5, cell * 0.08);
    for (let i = points.length - 1; i >= 0; i--) {
      const [x, y] = points[i];
      ctx.globalAlpha = i === 0 ? 1 : 0.55 + 0.4 * (1 - i / points.length);
      ctx.fillStyle = color;
      roundRect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad, cell * 0.25);
    }
    ctx.globalAlpha = 1;
    drawHead(points, ox, oy, cell);
  }

  for (const fx of view.effects) {
    const age = (now - fx.born) / 700;
    if (age >= 1) continue;
    ctx.strokeStyle = fx.color;
    ctx.globalAlpha = 1 - age;
    ctx.lineWidth = Math.max(1, cell * 0.15);
    ctx.beginPath();
    ctx.arc(ox + (fx.cell[0] + 0.5) * cell, oy + (fx.cell[1] + 0.5) * cell, cell * (0.5 + age * 1.8), 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  view.effects = view.effects.filter((fx) => now - fx.born < 700);
}

function drawHead(points, ox, oy, cell) {
  const [hx, hy] = points[0];
  const [nx, ny] = points[1] || points[0];
  const dx = Math.sign(Math.round((hx - nx) * 10));
  const dy = Math.sign(Math.round((hy - ny) * 10));
  const cx = ox + (hx + 0.5) * cell;
  const cy = oy + (hy + 0.5) * cell;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = Math.max(1, cell * 0.08);
  ctx.strokeRect(ox + hx * cell + cell * 0.1, oy + hy * cell + cell * 0.1, cell * 0.8, cell * 0.8);
  if (cell < 6) return;
  ctx.fillStyle = "#0b0e14";
  const r = cell * 0.09;
  const side = 0.2 * cell;
  const fwd = 0.15 * cell;
  for (const sgn of [-1, 1]) {
    const ex = cx + dx * fwd + (dy !== 0 ? sgn * side : 0);
    const ey = cy + dy * fwd + (dx !== 0 ? sgn * side : 0);
    ctx.beginPath();
    ctx.arc(ex, ey, r, 0, Math.PI * 2);
    ctx.fill();
  }
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2));
  ctx.fill();
}

// ---------- side panel ----------

function updateBoard(force) {
  const now = performance.now();
  if (!force && now - view.lastBoardUpdate < 100) return;
  view.lastBoardUpdate = now;
  if (!view.meta || !view.cur) return;
  const policies = Object.fromEntries(view.meta.snakes.map((s) => [s.id, s.policy]));
  const rows = [...view.cur.snakes].sort((a, b) => b.k - a.k || a.d - b.d || b.at - a.at || a.id.localeCompare(b.id));
  const body = $("#leaderboard tbody");
  body.innerHTML = rows.map((s) => {
    const alive = s.b.length > 0;
    const kd = s.d ? (s.k / s.d).toFixed(2) : s.k.toFixed(2);
    const life = alive ? `${fmt(s.lt)} t` : s.r > 0 ? `respawn ${s.r}` : "waiting";
    return `<tr class="${alive ? "" : "dead"}"><td><span class="swatch" style="background:${colorOf(s.id)}"></span></td>`
      + `<td>${label(s.id)}<span class="policy">${label(s.id) === s.id ? policies[s.id] || "" : s.id}</span></td>`
      + `<td>${s.k}</td><td>${s.d}</td><td>${kd}</td><td>${life}</td></tr>`;
  }).join("");
  const c = view.meta.config;
  const mode = view.meta.mode === "replay" ? "replay" : "live";
  const state = atEnd() ? "finished" : view.playing ? `${view.speed === "max" ? "max" : BASE_TPS * Number(view.speed) + " ticks/s"}` : "paused";
  $("#status").textContent = `tick ${fmt(view.cur.t)} / cap ${fmt(c.max_ticks)} · first to ${c.score_target} · ${c.width}×${c.height} · seed ${view.meta.seed} · ${mode} · ${state}`;
}

// ---------- controls ----------

$("#play").addEventListener("click", () => setPlaying(!view.playing));
$("#step").addEventListener("click", async () => {
  setPlaying(false);
  if (!view.queue.length) await fill();
  advance();
  updateBoard(true);
});
$("#speed").addEventListener("change", (e) => {
  view.speed = e.target.value;
  view.lastTickAt = performance.now();
});
$("#finish").addEventListener("click", finishNow);
form.addEventListener("submit", (e) => {
  e.preventDefault();
  start(formSettings());
});
$("#new-seed").addEventListener("click", () => {
  form.elements.seed.value = Math.floor(Math.random() * 1_000_000);
  start(formSettings());
});
$("#download").addEventListener("click", async () => {
  if (!view.meta || view.meta.mode !== "live") return;
  try {
    const replay = await api(`/api/match/${view.meta.id}/replay`);
    const blob = new Blob([JSON.stringify(replay)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `snake-arena-seed-${view.meta.seed}-tick-${replay.actions.length}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (err) {
    showError(err.message);
  }
});
$("#load").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    start({ mode: "replay", replay: JSON.parse(await file.text()) });
  } catch (err) {
    showError(`could not read replay: ${err.message}`);
  }
});
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select")) return;
  if (e.code === "Space") { e.preventDefault(); setPlaying(!view.playing); }
  if (e.key === ".") $("#step").click();
});
window.addEventListener("resize", resize);

// ---------- boot ----------

(async function boot() {
  try {
    const info = await api("/api/info");
    form.elements.policy.innerHTML = info.policies.map((p) => `<option>${p}</option>`).join("");
    fillForm(info.seed, info.defaults, info.policy);
    view.speed = $("#speed").value;
    await start(info.startup_replay ? { mode: "startup_replay" } : formSettings());
  } catch (err) {
    showError(err.message);
  }
  requestAnimationFrame(tick);
})();
