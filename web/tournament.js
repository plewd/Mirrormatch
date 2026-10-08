// Round-robin tournaments in the browser: pick bots, play every pair, show standings and
// a head-to-head grid. Same rules as `python -m arena.eval`: sides alternate, every bot
// gets the same difficulty, win % = wins / games played.
import { botKind, byStrength } from "./labels.js";

const $ = (id) => document.getElementById(id);
const GAMES = [10, 20, 50, 100];
const STORE_KEY = "mirrormatch.tournament";
let ctx = null;
let run = null;
let settings = { bots: null, games: 20, difficulty: "normal" };  // bots: picked values (null = defaults)

function loadSettings() {
  try { Object.assign(settings, JSON.parse(localStorage.getItem(STORE_KEY) || "{}")); } catch { /* defaults */ }
  if (!GAMES.includes(settings.games)) settings.games = 20;
  if (!ctx.info.difficulties.includes(settings.difficulty)) settings.difficulty = "normal";
}

function saveSettings() {
  settings.bots = picked().map((o) => o.value);
  try { localStorage.setItem(STORE_KEY, JSON.stringify(settings)); } catch { /* keep for this visit */ }
}

const kind = (value) => botKind(value, ctx.info.trained_bots);

function picked() {
  return [...$("tn-bots").querySelectorAll('.tn-bot[aria-pressed="true"]')].map((b) => ({ value: b.dataset.value, label: b.dataset.label }));
}

// ---- setup ---------------------------------------------------------------------------

function fillBotList() {
  const keep = new Set(settings.bots ?? []);
  const defaults = (o) => ["builtin:leader", "builtin:dodger", "starter:baiter"].includes(o.value) || o.value.startsWith("upload:");
  const chips = byStrength(ctx.botOptions()).map((o) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tn-bot";
    b.dataset.value = o.value;
    b.dataset.label = o.label.replace(/ \(yours\)$/, "");
    b.setAttribute("aria-pressed", String(settings.bots ? keep.has(o.value) : defaults(o)));
    b.append(document.createElement("i"), b.dataset.label);
    const tag = kind(o.value);
    if (tag) {
      const small = document.createElement("small");
      small.textContent = tag;
      b.append(small);
    }
    b.addEventListener("click", () => {
      if (run) return;
      b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
      saveSettings();
      updateRunButton();
    });
    return b;
  });
  $("tn-bots").replaceChildren(...chips);
  updateRunButton();
}

function quickSelect(which) {
  if (run) return;
  for (const b of $("tn-bots").children) {
    const k = kind(b.dataset.value);
    const on = which === "all" || (which === "builtin" && k !== "yours") || (which === "yours" && k === "yours");
    b.setAttribute("aria-pressed", String(on));
  }
  saveSettings();
  updateRunButton();
}

function chipGroup(el, values, current, onPick) {
  el.replaceChildren(...values.map((v) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = v;
    b.setAttribute("aria-pressed", String(v === current));
    b.addEventListener("click", () => {
      if (run) return;
      for (const c of el.children) c.setAttribute("aria-pressed", String(c === b));
      onPick(v);
    });
    return b;
  }));
}

function updateRunButton() {
  const btn = $("tn-run");
  if (run) { btn.textContent = "Stop"; btn.disabled = false; return; }
  const n = picked().length;
  const games = (n * (n - 1) / 2) * settings.games;
  btn.disabled = n < 2;
  btn.textContent = n < 2 ? "Pick at least 2 bots" : `Run ${n} bots · ${games} games ▶`;
}

// ---- results -------------------------------------------------------------------------

/** A background tint for a score in [0, 1] (draws count half): red below even, green above. */
function heat(score) {
  const k = Math.min(1, Math.abs(score - 0.5) * 2) * 0.32;
  return score >= 0.5 ? `rgba(111, 207, 143, ${k})` : `rgba(240, 90, 80, ${k})`;
}

function cellOf(results, a, b) {
  const r = results[`${a}|${b}`];
  if (r) return r;
  const s = results[`${b}|${a}`];
  return s ? { w: s.l, l: s.w, d: s.d, n: s.n } : null;
}

function standings(bots, results) {
  return bots.map((a) => {
    const t = { w: 0, l: 0, d: 0, n: 0 };
    for (const b of bots) {
      const c = a === b ? null : cellOf(results, a.value, b.value);
      if (c) { t.w += c.w; t.l += c.l; t.d += c.d; t.n += c.n; }
    }
    return { bot: a, ...t, rate: t.n ? (100 * t.w) / t.n : -1 };
  }).sort((x, y) => y.rate - x.rate || x.bot.label.localeCompare(y.bot.label));
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

function renderResults(state) {
  const { bots, results, done, difficulty } = state;
  const table = standings(bots, results);

  const head = el("div", "tn-label", done ? "Standings" : "Standings (provisional)");
  const list = el("div", "tn-standings");
  table.forEach((row, k) => {
    const item = el("div", "tn-standing");
    item.append(el("span", `tn-rank${k < 3 && row.n ? ` r${k + 1}` : ""}`, String(k + 1)), el("b", "", row.bot.label));
    const bar = el("span", "tn-winbar");
    bar.style.setProperty("--win", `${Math.max(0, row.rate)}%`);
    item.append(bar, el("span", "tn-pct", row.rate < 0 ? "…" : `${row.rate.toFixed(1)}%`),
      el("span", "tn-wld", row.n ? `${row.w}-${row.l}-${row.d}` : ""));
    list.append(item);
  });

  const grid = el("table", "tn-grid");
  const hr = grid.createTHead().insertRow();
  hr.insertCell();
  for (const { bot } of table) hr.insertCell().textContent = bot.label;
  const body = grid.createTBody();
  for (const { bot: a } of table) {
    const tr = body.insertRow();
    tr.insertCell().textContent = a.label;
    for (const { bot: b } of table) {
      const td = tr.insertCell();
      if (a === b) { td.className = "self"; continue; }
      const c = cellOf(results, a.value, b.value);
      if (!c || !c.n) { td.textContent = "…"; td.className = "pending"; continue; }
      td.textContent = c.d ? `${c.w}-${c.l}-${c.d}` : `${c.w}-${c.l}`;
      td.style.background = heat((c.w + c.d / 2) / c.n);
      td.title = `${a.label} vs ${b.label}: ${c.w} won, ${c.l} lost, ${c.d} drawn (${c.n} games). Click to watch.`;
      td.className = "played";
      td.addEventListener("click", () => ctx.watch(a.value, b.value, difficulty));
    }
  }
  const wrap = el("div", "table-wrap");
  wrap.append(grid);
  const note = el("p", "hint", "Rows and columns in standings order. Hover a cell for the full score; click it to watch that matchup.");
  $("tn-results").replaceChildren(head, list, el("div", "tn-label", "Head to head"), wrap, note);
}

// ---- running ---------------------------------------------------------------------------

function setProgress(state) {
  const { played, total, startedAt, now, done, stopped } = state;
  $("tn-progress").hidden = false;
  $("tn-bar").style.width = `${total ? (100 * played) / total : 0}%`;
  $("tn-phase").textContent = done ? (stopped ? "Stopped" : "Done") : "Running…";
  $("tn-status").textContent = done
    ? `${played} of ${total} games`
    : `${played} / ${total} games${now ? ` · now: ${now}` : ""}`;
  const perGame = played ? (performance.now() - startedAt) / played : 0;
  const left = (total - played) * perGame / 1000;
  $("tn-eta").textContent = done || !played ? "" : left < 2 ? "almost done" : `about ${Math.round(left)} s left`;
}

function start() {
  if (run) { run.cancel = true; return; }
  const bots = picked().map((o) => ({ ...o, ...ctx.resolveBot(o.value), label: o.label }));
  if (bots.length < 2) return;
  const { games, difficulty } = settings;
  const pairs = [];
  for (let i = 0; i < bots.length; i++) for (let j = i + 1; j < bots.length; j++) pairs.push([bots[i], bots[j]]);
  const state = {
    bots, results: {}, difficulty, games, done: false, stopped: false,
    played: 0, total: pairs.length * games, startedAt: performance.now(), now: "",
  };
  const seed0 = Math.floor(Math.random() * 2 ** 30);
  run = { cancel: false, pair: 0, g: 0 };
  const me = run;
  updateRunButton();
  document.querySelector("#tournament").classList.add("running");
  const finish = () => {
    run = null;
    state.done = true;
    state.stopped = me.cancel;
    document.querySelector("#tournament").classList.remove("running");
    updateRunButton();
    setProgress(state);
    renderResults(state);
  };
  const step = () => {
    if (me.cancel || me.pair >= pairs.length) { finish(); return; }
    const [a, b] = pairs[me.pair];
    state.now = `${a.label} vs ${b.label}`;
    const r = (state.results[`${a.value}|${b.value}`] ||= { w: 0, l: 0, d: 0, n: 0 });
    const res = ctx.api.play_game(a.spec, b.spec, seed0 + me.g, me.g % 2 === 0, difficulty);
    r[res[0]] += 1;
    r.n += 1;
    state.played += 1;
    me.g += 1;
    if (me.g >= games) { me.pair += 1; me.g = 0; }
    setProgress(state);
    if (me.g === 0 || state.played % 5 === 0) renderResults(state);
    setTimeout(step, 0);
  };
  setProgress(state);
  renderResults(state);
  step();
}

export function initTournament(context) {
  ctx = context;
  loadSettings();
  chipGroup($("tn-games"), GAMES, settings.games, (v) => { settings.games = v; saveSettings(); updateRunButton(); });
  chipGroup($("tn-difficulty"), ctx.info.difficulties, settings.difficulty, (v) => { settings.difficulty = v; saveSettings(); });
  for (const link of document.querySelectorAll("[data-tn-select]")) {
    link.addEventListener("click", () => quickSelect(link.dataset.tnSelect));
  }
  $("tn-run").addEventListener("click", start);
  fillBotList();
}

export function onTournamentShown() {
  if (ctx && !run) fillBotList();
}
