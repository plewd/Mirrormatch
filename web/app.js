// Mirrormatch in the browser: boots Pyodide, runs the real Python sim, draws it.
import { loadPyodide } from "./vendor/pyodide/pyodide.mjs";
import { Renderer } from "./render.js";
import { initEditor, onEditorShown, editorDebug, openInEditor } from "./editor.js";
import { copyShareLink, sharedFromUrl, toast, unpack } from "./share.js";
import { initTournament, onTournamentShown } from "./tournament.js";
import { initGuide } from "./guide.js";
import { RulePanel } from "./rulepanel.js";
import { Sound } from "./audio.js";
import { Lobby } from "./lobby.js";
import { botKind, explainDifficulty } from "./labels.js";
import { actionForKey, initSettings, settings } from "./settings.js";

const sound = new Sound();

const $ = (id) => document.getElementById(id);
const STORAGE_KEY = "mirrormatch.bots";

let api = null;       // the arena.webapi module (a Pyodide proxy)
let info = null;      // static arena numbers
let renderer = null;
let starters = {};    // rule bots shipped in bots/*.json
let vocab = null;     // the rule vocabulary, for building editor blocks
let uploaded = {};    // label -> rule-bot JSON text, kept in localStorage
let shared = null;    // {label, spec} of a bot opened from a share link (this visit only)
let shareError = null; // why a share link couldn't be used (shown once booted)
let session = null;   // the running arena.webapi.Session
let snap = null;      // latest snapshot
let view = null;      // how to draw it (names, human or spectating, speed)
let lastSetup = null; // to restart with R
let pending = null;   // human command waiting for the next tick
let acc = 0, last = performance.now();
let booted = false;   // true once everything is wired up and usable
let mouse = [600, 400], rightDown = false;
let timeline = null;  // {length, paused, seekTo} for spectated matches; null in live play
let panels = null;    // RulePanel per side, for "Show rules"
let lobby = null;     // the Play tab's opponent picker
let currentTab = "play";
let playOnScreen = false;  // your own match is showing on the Play tab (else the lobby is)

function setStatus(text, error = false) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("error", error);
  const splash = $("splash-status");
  if (splash) {
    splash.textContent = text;
    splash.classList.toggle("error", error);
  }
}

// ---- loading splash ------------------------------------------------------------
// The logo animation (style.css, #splash) plays once; the splash fades out when both it
// and booting are done. If loading outlasts the animation, a progress line appears under
// the logo; on failure the error stays there.

const splashDrawn = (() => {
  const splash = $("splash");
  const anims = splash && splash.getAnimations ? splash.getAnimations({ subtree: true }) : [];
  return Promise.all(anims.map((a) => a.finished)).catch(() => {});
})();
splashDrawn.then(() => setTimeout(() => $("splash-status")?.classList.add("shown"), 300));

async function hideSplash() {
  const splash = $("splash");
  if (!splash) return;
  await splashDrawn;
  splash.classList.add("done");
  splash.addEventListener("transitionend", () => splash.remove(), { once: true });
  setTimeout(() => splash.remove(), 800);  // in case transitionend never fires
}

// ---- bots ---------------------------------------------------------------------

function loadUploaded() {
  try { uploaded = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch { uploaded = {}; }
}

function saveUploaded() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(uploaded)); } catch { /* private mode: keep in memory */ }
}

function botOptions() {
  const opts = [];
  if (shared) opts.push({ value: `shared:${shared.label}`, label: shared.label });
  for (const name of info.builtin_bots) opts.push({ value: `builtin:${name}`, label: name });
  for (const [key, spec] of Object.entries(starters)) opts.push({ value: `starter:${key}`, label: spec.name || key });
  for (const label of Object.keys(uploaded)) opts.push({ value: `upload:${label}`, label: `${label} (yours)` });
  return opts;
}

function fillBotSelects() {
  for (const sel of document.querySelectorAll(".bot-select")) {
    const keep = sel.value;
    sel.innerHTML = "";
    for (const o of botOptions()) sel.add(new Option(o.label, o.value));
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  }
  if (!$("watch-left").dataset.init) { $("watch-left").value = "builtin:dodger"; $("watch-left").dataset.init = 1; }
  if (!$("watch-right").dataset.init) { $("watch-right").value = "starter:leader"; $("watch-right").dataset.init = 1; }
  updateSideTags();
  if (lobby) lobby.render();
}

function resolveBot(value) {
  const [kind, ...rest] = value.split(":");
  const key = rest.join(":");
  if (kind === "builtin") return { spec: key, label: key };
  if (kind === "starter") return { spec: JSON.stringify(starters[key]), label: starters[key].name || key };
  if (kind === "shared") return { spec: shared.spec, label: shared.label };
  return { spec: uploaded[key], label: key };
}

async function onBotFiles(files) {
  const msgs = [];
  for (const file of files) {
    const text = await file.text();
    const errors = JSON.parse(api.check_bot(text));
    if (errors.length) { msgs.push(`${file.name}: ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`); continue; }
    const label = (JSON.parse(text).name || file.name.replace(/\.json$/, "")).trim();
    uploaded[label] = text;
    msgs.push(`loaded "${label}"`);
  }
  saveUploaded();
  fillBotSelects();
  $("bot-file-msg").textContent = msgs.join(" · ");
}

// ---- matches ------------------------------------------------------------------

function start(setup, replayText = null) {
  if (session) { session.destroy(); session = null; }
  lastSetup = replayText ? null : setup;
  const seed = Math.floor(Math.random() * 2 ** 31);
  try {
    session = replayText ? api.Session.from_replay(replayText) : api.Session(setup.left.spec, setup.right.spec, setup.difficulty, seed);
  } catch (err) {
    setStatus(`Couldn't start: ${err.message.split("\n").slice(-2).join(" ")}`, true);
    return;
  }
  view = {
    leftSpec: setup.left.spec,
    rightSpec: setup.right.spec,
    names: [setup.left.label, setup.right.label],
    human: setup.left.spec === "human",
    aimLineFor: setup.left.spec === "human" ? 0 : -1,
    moveMarker: null,
    speed: setup.speed,
  };
  pending = null;
  acc = 0;
  renderer.resetEffects();
  sound.reset();
  snap = JSON.parse(session.snapshot());
  timeline = null;
  $("timeline").hidden = true;
  if (!view.human || replayText) {  // spectating: precompute the match so the timeline can scrub
    try {
      timeline = { length: session.prepare_timeline(), paused: false, seekTo: null };
      $("tl-range").max = timeline.length;
      $("timeline").hidden = false;
      $("tl-play").textContent = "⏸";
    } catch (err) {
      console.warn("timeline unavailable", err);
    }
  }
  if (replayText) {
    view.human = false;  // spectating, even if a human played it
    setStatus(`Replay: ${setup.left.label} vs ${setup.right.label} (${setup.difficulty})`);
  } else {
    setStatus(view.human ? `Playing ${setup.right.label} (${setup.difficulty}) · seed ${seed}` :
      `${setup.left.label} vs ${setup.right.label} (${setup.difficulty}) · seed ${seed}`);
  }
  $("replay-save").disabled = false;
  $("replay-link").disabled = false;
  panels[0].show(setup.left.spec, setup.left.label, "#50a0ff");
  panels[1].show(setup.right.spec, setup.right.label, "#f05a50");
  layoutRulePanels(setup);
  playOnScreen = setup.left.spec === "human" && !replayText;
  updatePlayView();
  $("arena").focus();
}

function startPlay(opponent, difficulty) {
  window.scrollTo(0, 0);
  start({ left: { spec: "human", label: "You" }, right: resolveBot(opponent), difficulty, speed: 1 });
}

/** Leave your match (finished or not) and show the opponent lobby again. */
function backToLobby() {
  session = snap = view = timeline = null;
  $("timeline").hidden = true;
  $("replay-save").disabled = true;
  $("replay-link").disabled = true;
  playOnScreen = false;
  setStatus("Ready");
  layoutRulePanels();
  updatePlayView();
  document.querySelector('#lobby .bot-card[aria-pressed="true"]')?.focus();
}

/** On the Play tab, show the lobby unless your own match is on screen. */
function updatePlayView() {
  const lobbyShown = currentTab === "play" && !playOnScreen;
  $("lobby").hidden = !lobbyShown;
  if (currentTab === "play") {
    $("stage").hidden = lobbyShown;
    $("controls").hidden = lobbyShown;
  }
  fitArena();
}

/** Fit the stage to the window: cap the arena's width so its height fits below whatever sits
 *  above it, and the rule panels' height likewise, so the page ends at the window's bottom. */
function fitArena() {
  if ($("stage").hidden) return;
  const below = (parseFloat(getComputedStyle(document.querySelector("main")).paddingBottom) || 0) + 2;
  const room = (el) => window.innerHeight - (el.getBoundingClientRect().top + window.scrollY) - below;
  const c = $("arena");
  c.style.maxWidth = "";
  c.style.maxWidth = `${Math.max(360, Math.floor(room(c) * c.width / c.height))}px`;
  for (const panel of [$("rules-0"), $("rules-1")]) {
    panel.style.maxHeight = "";
    if (!panel.hidden && getComputedStyle(panel).position === "sticky") panel.style.maxHeight = `${Math.max(200, room(panel))}px`;
  }
}

/** A row of chip buttons holding one value (in el.dataset.value), like a compact select. */
function chipGroup(el, options, initial, onPick = () => {}) {
  el.replaceChildren(...options.map(([value, label]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = label;
    b.dataset.value = value;
    b.addEventListener("click", () => { setChip(el, value); onPick(value); });
    return b;
  }));
  setChip(el, initial);
}

function setChip(el, value) {
  el.dataset.value = String(value);
  for (const b of el.children) b.setAttribute("aria-pressed", String(b.dataset.value === String(value)));
}

/** The small "rules / trained / yours" tag beside each Watch side's bot picker. */
function updateSideTags() {
  for (const id of ["watch-left", "watch-right"]) {
    $(id).parentElement.querySelector(".side-tag").textContent = botKind($(id).value, info.trained_bots);
  }
}

/** Open Watch with this pair (dropdown values like "builtin:dodger") and start it. */
function watchMatch(left, right, difficulty) {
  showTab("watch");
  $("watch-left").value = left;
  $("watch-right").value = right;
  if (difficulty) setChip($("watch-difficulty"), difficulty);
  updateSideTags();
  startWatch();
}

function startWatch() {
  $("watch-menu").open = false;
  start({
    left: resolveBot($("watch-left").value),
    right: resolveBot($("watch-right").value),
    difficulty: $("watch-difficulty").dataset.value,
    speed: Number($("watch-speed").dataset.value),
  });
}

function saveReplay() {
  if (!session) return;
  const text = session.replay(view.names[0], view.names[1]);
  const blob = new Blob([text], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `replay_${view.names[0]}_vs_${view.names[1]}.json`.replace(/[^\w.-]+/g, "_");
  a.click();
  URL.revokeObjectURL(a.href);
}

async function loadReplay(file) {
  const text = await file.text();
  let rep;
  try { rep = JSON.parse(text); } catch { setStatus(`${file.name} is not a replay file`, true); return; }
  if (!rep.mirrormatch_replay) { setStatus(`${file.name} is not a replay file`, true); return; }
  showTab("watch");
  start({ left: rep.left, right: rep.right, difficulty: rep.difficulty, speed: Number($("watch-speed").dataset.value) }, text);
}

// ---- sound ---------------------------------------------------------------------------

function setupSound() {
  let volume = 0.6, muted = false;
  try {
    volume = Number(localStorage.getItem("mirrormatch.volume") ?? 0.6);
    muted = localStorage.getItem("mirrormatch.muted") === "1";
  } catch { /* storage unavailable */ }
  const show = () => {  // the icon's waves follow the volume: none (muted), one (quiet), two
    const level = sound.muted || sound.volume === 0 ? 0 : sound.volume < 0.5 ? 1 : 2;
    const btn = $("sound-toggle");
    btn.dataset.level = level;
    btn.setAttribute("aria-pressed", String(sound.muted));
    btn.setAttribute("aria-label", sound.muted ? "Unmute" : "Mute");
  };
  sound.setVolume(volume);
  sound.setMuted(muted);
  $("volume").value = volume;
  show();
  const save = () => {
    try {
      localStorage.setItem("mirrormatch.volume", String(sound.volume));
      localStorage.setItem("mirrormatch.muted", sound.muted ? "1" : "0");
    } catch { /* keep for this visit */ }
  };
  $("sound-toggle").addEventListener("click", () => { sound.unlock(); sound.setMuted(!sound.muted); show(); save(); });
  $("volume").addEventListener("input", (e) => {
    sound.unlock();
    sound.setVolume(Number(e.target.value));
    if (sound.muted && sound.volume > 0) sound.setMuted(false);
    show();
    save();
  });
  // Browsers only start audio after a user gesture.
  for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, () => sound.unlock());
  window.__mirrormatchSound = sound;
}

// ---- rule panels -------------------------------------------------------------------

const isRuleSpec = (spec) => typeof spec === "string" && spec.trim().startsWith("{");

/** Show the side panels only when watching at least one rule bot and "Show rules" is on. */
function layoutRulePanels(setup = lastSetup) {
  const wanted = $("show-rules").checked && !!session && !!view &&
    [view.leftSpec, view.rightSpec].some(isRuleSpec);
  $("stage").classList.toggle("with-rules", wanted);
  // A side without rules only needs room for its short note.
  const col = (spec) => (isRuleSpec(spec) ? "minmax(200px, 250px)" : "150px");
  $("stage").style.gridTemplateColumns = wanted && view ? `${col(view.leftSpec)} minmax(0, 1fr) ${col(view.rightSpec)}` : "";
  document.querySelector("main").classList.toggle("wide", wanted);
  $("rules-0").hidden = !wanted;
  $("rules-1").hidden = !wanted;
  fitArena();
}

// ---- timeline -------------------------------------------------------------------

function seek(tick) {
  if (!timeline) return;
  snap = JSON.parse(session.seek(Math.max(0, Math.min(timeline.length, tick))));
  renderer.resetEffects();  // a jump isn't a real hit/heal/etc.
  sound.reset();
  acc = 0;
}

function togglePause() {
  if (!timeline) return;
  if (timeline.paused && snap.done) seek(0);  // at the end: play it again from the start
  timeline.paused = !timeline.paused;
  $("tl-play").textContent = timeline.paused ? "▶" : "⏸";
}

function setupTimeline() {
  $("tl-play").addEventListener("click", togglePause);
  $("tl-step").addEventListener("click", () => { if (timeline) { timeline.paused = true; $("tl-play").textContent = "▶"; seek(snap.tick + 1); } });
  $("tl-back").addEventListener("click", () => { if (timeline) { timeline.paused = true; $("tl-play").textContent = "▶"; seek(snap.tick - 1); } });
  $("tl-range").addEventListener("input", (e) => { if (timeline) timeline.seekTo = Number(e.target.value); });
}

function command(part) {
  pending = { ...(pending || {}), ...part };
}

// ---- input --------------------------------------------------------------------

function setupInput() {
  const canvas = $("arena");
  canvas.tabIndex = 0;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("mousedown", (e) => {
    mouse = renderer.toWorld(e.clientX, e.clientY);
    if (e.button === settings.moveButton && view?.human) {
      rightDown = true;
      command({ move: mouse });
      view.moveMarker = mouse;
    }
  });
  window.addEventListener("mouseup", (e) => { if (e.button === settings.moveButton) rightDown = false; });
  canvas.addEventListener("mousemove", (e) => {
    mouse = renderer.toWorld(e.clientX, e.clientY);
    if (rightDown && view?.human) { command({ move: mouse }); view.moveMarker = mouse; }
  });
  window.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLSelectElement || e.target instanceof HTMLInputElement) return;
    if (lobby && lobby.visible && lobby.key(e)) { e.preventDefault(); return; }
    const key = e.key.toLowerCase();
    if (e.key === "Escape" && currentTab === "play" && playOnScreen) { backToLobby(); return; }
    const action = actionForKey(e.key);  // rebindable in Settings
    if (action === "restart" && lastSetup && snap?.done) { start(lastSetup); return; }
    if (timeline && !$("stage").hidden) {  // spectating: playback keys
      if (key === " ") { togglePause(); e.preventDefault(); return; }
      if (e.key === "ArrowRight") { $("tl-step").click(); e.preventDefault(); return; }
      if (e.key === "ArrowLeft") { $("tl-back").click(); e.preventDefault(); return; }
    }
    if (!session || !view?.human || snap?.done) return;
    if (["bolt", "dash", "item"].includes(action)) { command({ cast: action, aim: mouse }); e.preventDefault(); }
  });
}

function showTab(name) {
  currentTab = name;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("active", b.dataset.tab === name);
  for (const p of document.querySelectorAll("[data-panel]")) p.hidden = !p.dataset.panel.split(" ").includes(name);
  const page = ["build", "tournament", "guide"].includes(name) ? name : "arena";
  $("controls").hidden = page !== "arena";
  $("stage").hidden = page !== "arena";
  $("builder").hidden = page !== "build";
  $("tournament").hidden = page !== "tournament";
  $("guide").hidden = page !== "guide";
  document.querySelector("main").classList.toggle("wide", page === "arena" && $("stage").classList.contains("with-rules"));
  document.querySelector("main").classList.toggle("full", page === "build");
  if (page === "build") onEditorShown();
  if (page === "tournament") onTournamentShown();
  updatePlayView();
}

/** Read a share link the page was opened with. A bot becomes `shared` (validated first);
 *  a replay's text is returned so boot can play it once everything is ready. */
async function readShareLink() {
  const link = sharedFromUrl();
  if (!link) return null;
  let text;
  try { text = await unpack(link.data); } catch { shareError = "That share link is damaged or incomplete."; return null; }
  if (link.kind === "replay") return text;
  let spec;
  try { spec = JSON.parse(text); } catch { shareError = "That share link doesn't contain a bot."; return null; }
  const errors = JSON.parse(api.check_bot(text));
  if (errors.length) { shareError = `The shared bot has problems: ${errors[0]}`; return null; }
  shared = { label: String(spec.name || "shared bot").slice(0, 60), spec: text };
  return null;
}

function saveShared() {
  if (!shared) return;
  let label = shared.label;
  for (let k = 2; uploaded[label] && uploaded[label] !== shared.spec; k++) label = `${shared.label} (${k})`;
  saveBot(label, shared.spec);
  shared = null;  // it's an ordinary saved bot now: one card, not two
  fillBotSelects();
  lobby.select(`upload:${label}`);
  toast(`Saved "${label}" to your bots.`);
}

function saveBot(label, text) {
  uploaded[label] = text;
  saveUploaded();
  fillBotSelects();
}

function setupTabs() {
  for (const btn of document.querySelectorAll("#tabs button")) {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  }
  // "? Guide" links and the guide's table of contents jump to a section.
  document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-goto]");
    if (!link) return;
    e.preventDefault();
    showTab("guide");
    document.getElementById(link.dataset.goto)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// ---- loop ---------------------------------------------------------------------

function drawIdle() {
  const g = renderer.ctx;
  g.fillStyle = "#12141a";
  g.fillRect(0, 0, g.canvas.width, g.canvas.height);
  g.fillStyle = "#8a90a0";
  g.font = "18px system-ui, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(api ? "Pick two bots above and press Watch ▶" : "Loading…", g.canvas.width / 2, g.canvas.height / 2);
}

function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.25);  // don't fast-forward after a stall
  last = now;
  if (window.__mirrormatchFreeze) { requestAnimationFrame(frame); return; }  // testing: draw a scene by hand
  if (session && snap) {
    // Watch-only overlays (their toggles live on Watch): never drawn over your own match.
    view.showDecisions = !view.human && $("show-decisions").checked;
    view.showSeen = !view.human && $("show-seen").checked;
    if (timeline && timeline.seekTo !== null) { seek(timeline.seekTo); timeline.seekTo = null; }
    view.speed = timeline ? Number($("watch-speed").dataset.value) : view.speed;
    acc += timeline && timeline.paused ? 0 : dt * view.speed;
    const tickDt = 1 / info.tick_rate;
    const n = Math.floor(acc / tickDt);
    if (n > 0 && !snap.done) {
      acc -= n * tickDt;
      if (pending) { session.command(JSON.stringify(pending)); pending = null; }
      snap = JSON.parse(session.advance(n));
      sound.handle(snap, view, info.width);
    }
    renderer.draw(snap, view);
    if (snap.debug && !$("rules-0").hidden) {
      panels[0].update(snap.debug[0]);
      panels[1].update(snap.debug[1]);
    }
    if (timeline) {
      if (document.activeElement !== $("tl-range")) $("tl-range").value = snap.tick;
      const sec = (t) => (t / info.tick_rate).toFixed(1);
      $("tl-time").textContent = `${sec(snap.tick)}s / ${sec(timeline.length)}s`;
    }
  } else if (renderer) {
    drawIdle();
  }
  const live = !!(session && view?.human && !snap?.done && playOnScreen && currentTab === "play");
  document.documentElement.classList.toggle("locked", live);
  window.__mirrormatch = { ready: booted, tick: snap?.tick ?? -1, done: snap?.done ?? false, snap };
  requestAnimationFrame(frame);
}

// ---- boot ---------------------------------------------------------------------

async function boot() {
  renderer = new Renderer($("arena"), { width: 1200, height: 800, champion_radius: 30, champion_hp: 3, pickup_radius: 20, loadout: ["bolt", "dash"] });
  setupTabs();
  setupInput();
  setupTimeline();
  panels = [new RulePanel($("rules-0")), new RulePanel($("rules-1"))];
  setupSound();
  $("show-rules").addEventListener("change", () => layoutRulePanels());
  let style = "polished";
  try { style = localStorage.getItem("mirrormatch.graphics") || style; } catch { /* storage unavailable */ }
  renderer.style = style;
  initSettings({
    get: () => renderer.style,
    set: (value) => {
      renderer.style = value;
      renderer.resetEffects();
      try { localStorage.setItem("mirrormatch.graphics", value); } catch { /* keep for this visit */ }
    },
  });
  for (const link of document.querySelectorAll("[data-open-settings]")) {
    link.addEventListener("click", (e) => { e.stopPropagation(); $("settings-btn").click(); });
  }
  requestAnimationFrame(frame);

  const pyodide = await loadPyodide({ indexURL: new URL("vendor/pyodide/", location.href).href });
  setStatus("Loading numpy…");
  await pyodide.loadPackage("numpy");
  setStatus("Loading the game…");
  const bundle = await (await fetch("build/arena.zip")).arrayBuffer();
  pyodide.unpackArchive(bundle, "zip", { extractDir: "/home/pyodide" });
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
  api = pyodide.pyimport("arena.webapi");
  info = JSON.parse(api.arena_info());
  renderer.info = info;
  initGuide(info);
  starters = await (await fetch("build/bots.json")).json();
  vocab = await (await fetch("build/vocab.json")).json();

  loadUploaded();
  const sharedReplay = await readShareLink();
  fillBotSelects();
  chipGroup($("watch-difficulty"), info.difficulties.map((d) => [d, d]), "normal");
  chipGroup($("watch-speed"), [["0.25", "¼×"], ["0.5", "½×"], ["1", "1×"], ["2", "2×"], ["4", "4×"], ["8", "8×"]], "1");
  for (const id of ["watch-left", "watch-right"]) $(id).addEventListener("change", updateSideTags);
  // The Replays & files menu closes on a click outside it, and after loading a file.
  document.addEventListener("click", (e) => { if (!$("watch-menu").contains(e.target)) $("watch-menu").open = false; });
  for (const id of ["replay-file", "bot-file"]) $(id).addEventListener("change", () => { $("watch-menu").open = false; });
  $("replay-save").addEventListener("click", () => { $("watch-menu").open = false; });
  $("replay-link").addEventListener("click", () => {
    $("watch-menu").open = false;
    if (session) copyShareLink("replay", session.replay(view.names[0], view.names[1]), "this replay");
  });
  lobby = new Lobby({
    botOptions,
    difficulties: info.difficulties,
    onPlay: (opponent, difficulty) => startPlay(opponent, difficulty),
    onBuild: () => showTab("build"),
    onBuildShared: () => { showTab("build"); openInEditor(JSON.parse(shared.spec)); },
    onSaveShared: saveShared,
  });
  $("play-back").addEventListener("click", backToLobby);
  for (const id of ["lobby-difficulty", "watch-difficulty", "tn-difficulty"]) explainDifficulty($(id), $(`${id}-note`), info);
  window.addEventListener("resize", fitArena);
  $("watch-start").addEventListener("click", startWatch);
  $("bot-file").addEventListener("change", (e) => onBotFiles([...e.target.files]));
  $("replay-save").addEventListener("click", saveReplay);
  $("replay-file").addEventListener("change", (e) => { if (e.target.files[0]) loadReplay(e.target.files[0]); e.target.value = ""; });
  for (const b of document.querySelectorAll("button.primary")) b.disabled = false;
  initEditor({
    api, vocab, starters, info, uploaded: () => uploaded, saveBot, resolveBot, botOptions,
    graphicsStyle: () => renderer.style,
    watch: watchMatch,
  });
  initTournament({ api, info, botOptions, resolveBot, watch: watchMatch });
  window.__mirrormatchEditor = editorDebug;
  window.__mirrormatchRenderer = renderer;
  window.__mirrormatchReplay = { save: () => session && session.replay(view.names[0], view.names[1]), load: (text) => start({ ...JSON.parse(text), speed: 8 }, text) };
  setStatus("Ready");
  booted = true;
  hideSplash();

  // ?auto=watch&left=builtin:dodger&right=starter:leader&speed=4 starts a match by itself (used for testing).
  const q = new URLSearchParams(location.search);
  if (q.get("auto") === "watch") {
    showTab("watch");
    if (q.get("left")) $("watch-left").value = q.get("left");
    if (q.get("right")) $("watch-right").value = q.get("right");
    if (q.get("speed")) setChip($("watch-speed"), q.get("speed"));
    updateSideTags();
    startWatch();
  } else if (q.get("auto") === "build") {
    showTab("build");
  } else if (q.get("auto") === "tournament") {
    showTab("tournament");
  } else if (q.get("auto") === "guide") {
    showTab("guide");
  } else if (q.get("auto") === "play") {
    startPlay(q.get("opponent") || lobby.selected, q.get("difficulty") || lobby.difficulty);
  } else if (sharedReplay) {
    let rep = null;
    try { rep = JSON.parse(sharedReplay); } catch { /* reported below */ }
    if (rep && rep.mirrormatch_replay) {
      showTab("watch");
      start({ left: rep.left, right: rep.right, difficulty: rep.difficulty, speed: 1 }, sharedReplay);
    } else {
      shareError = "That share link doesn't contain a replay.";
      updatePlayView();
    }
  } else {
    updatePlayView();
  }
  if (shareError) { setStatus(shareError, true); toast(shareError); }
}

boot().catch((err) => {
  console.error(err);
  setStatus(`Failed to start: ${err.message}`, true);
});
