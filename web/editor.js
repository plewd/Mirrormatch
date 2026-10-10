// Block editor for rule bots. Blocks are generated from the rule vocabulary that
// arena/bots/rules.py exports, and the workspace converts to and from the same
// bot JSON the Python interpreter runs, so blocks are only a view of that file.
/* global Blockly */
import { copyShareLink, toast } from "./share.js";
import { setupBuildPanels } from "./panels.js";
import { renderExplain } from "./explain.js";
import { ACTION_TEXT, SENSOR_TEXT, pretty } from "./labels.js";
import { Renderer } from "./render.js";

const NUMBER_DEFAULTS = {
  enemy_distance: 400, threat_time: 0.3, my_hp: 2, enemy_hp: 2, time_left: 10, pickup_distance: 300,
  enemy_cooldown: 1, since_enemy_used: 2, since_i_used: 2, since_i_was_hit: 2, since_i_hit_enemy: 2, time_in_mode: 3,
  heal_in: 2, heal_distance: 300,
};
// Which toolbox drawer each sensor lives in. Anything new and unlisted lands in "More".
const SENSOR_GROUPS = [
  ["Situation", ["enemy_distance", "threatened", "threat_time", "can_sidestep", "in_range", "time_left"]],
  ["Me", ["my_hp", "ready", "holding", "i_am_rooted", "since_i_used", "since_i_was_hit"]],
  ["Enemy", ["enemy_hp", "enemy_ready", "enemy_cooldown", "since_enemy_used", "enemy_holding", "enemy_casting",
             "enemy_rooted", "enemy_shielded", "enemy_dashing", "since_i_hit_enemy"]],
  ["Pickups & heal", ["pickup_distance", "closer_to_pickup", "heal_up", "heal_in", "heal_distance", "closer_to_heal"]],
  ["Modes & chance", ["in_mode", "time_in_mode", "chance"]],
];
const COLOURS = { bot: "#3a4a6a", condition: "#7a5fa8", move: "#3f8f5f", ability: "#c06a2b", mode: "#2c7f99" };
const CHANNEL_NAME = { move: "Move", ability: "Ability", mode: "Mode" };

let ws = null;
let ctx = null;
let vocab = null;
let changeTimer = null;
let testRun = null;
let preview = null;          // the running preview match (see startPreview)
let previewRenderer = null;
let lit = new Set();         // block ids currently glowing

// ---- block definitions ----------------------------------------------------------

function defineBlocks() {
  Blockly.Blocks.mm_bot = {
    init() {
      this.appendDummyInput().appendField("bot").appendField(new Blockly.FieldTextInput("my bot"), "NAME");
      this.appendStatementInput("RULES").setCheck("Rule").appendField("actions, highest priority first");
      this.setColour(COLOURS.bot);
      this.setDeletable(false);
      this.setTooltip("Each decision, the bot runs the first matching move rule and the first matching ability rule.");
    },
  };
  for (const [name, s] of Object.entries(vocab.sensors)) {
    Blockly.Blocks[`mm_s_${name}`] = {
      init() {
        const row = this.appendDummyInput()
          .appendField(new Blockly.FieldDropdown([["if", "is"], ["unless", "not"]]), "NEG")
          .appendField(SENSOR_TEXT[name] || pretty(name));
        for (const [key, choices] of Object.entries(s.params)) {
          row.appendField(new Blockly.FieldDropdown(choices.map((c) => [pretty(c), c])), `P_${key}`);
        }
        if (s.kind === "number") {
          row.appendField(new Blockly.FieldDropdown([["<", "<"], [">", ">"]]), "OP")
            .appendField(new Blockly.FieldNumber(NUMBER_DEFAULTS[name] ?? 0, -1e6, 1e6, 0.05), "VALUE");
        } else if (s.kind === "percent") {
          row.appendField(new Blockly.FieldNumber(25, 0, 100, 1), "VALUE");
        }
        this.setPreviousStatement(true, "Condition");
        this.setNextStatement(true, "Condition");
        this.setColour(COLOURS.condition);
        this.setTooltip(s.help);
      },
    };
  }
  for (const [name, a] of Object.entries(vocab.actions)) {
    Blockly.Blocks[`mm_a_${name}`] = {
      init() {
        const row = this.appendDummyInput().appendField(ACTION_TEXT[name] || pretty(name));
        for (const [key, choices] of Object.entries(a.params)) {
          row.appendField(new Blockly.FieldDropdown(choices.map((c) => [pretty(c), c])), `P_${key}`);
        }
        // Each action is a whole rule: it runs when every condition in its slot holds.
        this.appendStatementInput("WHEN").setCheck("Condition").appendField("when");
        this.setPreviousStatement(true, "Rule");
        this.setNextStatement(true, "Rule");
        this.setColour(COLOURS[a.channel]);
        this.setTooltip(`${CHANNEL_NAME[a.channel]} action. ${a.help} ` +
          "Runs when every condition under it holds; leave 'when' empty to always try it.");
      },
    };
  }
}

function toolbox() {
  const actions = (channel) => Object.entries(vocab.actions)
    .filter(([, a]) => a.channel === channel).map(([n]) => ({ kind: "block", type: `mm_a_${n}` }));
  const grouped = new Set(SENSOR_GROUPS.flatMap(([, names]) => names));
  const groups = SENSOR_GROUPS.map(([label, names]) => [label, names.filter((n) => vocab.sensors[n])]);
  const extra = Object.keys(vocab.sensors).filter((n) => !grouped.has(n));
  if (extra.length) groups.push(["More", extra]);
  return {
    kind: "categoryToolbox",
    contents: [
      { kind: "category", name: "Move", colour: COLOURS.move, contents: actions("move") },
      { kind: "category", name: "Abilities", colour: COLOURS.ability, contents: actions("ability") },
      { kind: "category", name: "Modes", colour: COLOURS.mode, contents: actions("mode") },
      { kind: "sep" },
      ...groups.map(([label, names]) => ({
        kind: "category", name: label, colour: COLOURS.condition,
        contents: names.map((n) => ({ kind: "block", type: `mm_s_${n}` })),
      })),
    ],
  };
}

// ---- workspace <-> bot JSON ------------------------------------------------------

function chain(block) {
  const out = [];
  for (let b = block; b; b = b.getNextBlock()) out.push(b);
  return out;
}

function params(block, defs) {
  const out = {};
  for (const key of Object.keys(defs)) out[key] = block.getFieldValue(`P_${key}`);
  return out;
}

/** The bot JSON for the workspace, plus problems the JSON itself can't show. */
export function workspaceToSpec() {
  const problems = [];
  const bot = ws.getTopBlocks(true).find((b) => b.type === "mm_bot");
  const loose = ws.getTopBlocks(true).filter((b) => b.type !== "mm_bot").length;
  if (loose) problems.push(`${loose} block group${loose > 1 ? "s are" : " is"} not attached to the bot and will be ignored`);
  const spec = { name: bot.getFieldValue("NAME").trim() || "my bot", version: vocab.version, rules: [] };
  const ruleBlocks = [];  // block id of each rule, by index, for highlighting what fired
  for (const act of chain(bot.getInputTargetBlock("RULES"))) {
    const conds = chain(act.getInputTargetBlock("WHEN")).map((c) => {
      const name = c.type.slice("mm_s_".length);
      const s = vocab.sensors[name];
      let cond = { sensor: name, ...params(c, s.params) };
      if (s.kind === "number") cond = { ...cond, op: c.getFieldValue("OP"), value: Number(c.getFieldValue("VALUE")) };
      if (s.kind === "percent") cond = { ...cond, value: Number(c.getFieldValue("VALUE")) };
      return c.getFieldValue("NEG") === "not" ? { not: cond } : cond;
    });
    const name = act.type.slice("mm_a_".length);
    spec.rules.push({ if: conds, then: { action: name, ...params(act, vocab.actions[name].params) } });
    ruleBlocks.push(act.id);
  }
  return { spec, problems, ruleBlocks };
}

function addBlock(type) {
  const b = ws.newBlock(type);
  b.initSvg();
  b.render();
  return b;
}

/** Replace the workspace with blocks for a bot spec. Throws on vocabulary it doesn't know. */
export function specToWorkspace(spec) {
  Blockly.Events.disable();
  try {
    ws.clear();
    const bot = addBlock("mm_bot");
    bot.setFieldValue(spec.name || "my bot", "NAME");
    bot.moveBy(20, 20);
    let prev = null;
    for (const rule of spec.rules) {
      const act = rule.then;
      if (!vocab.actions[act.action]) throw new Error(`unknown action "${act.action}"`);
      const r = addBlock(`mm_a_${act.action}`);
      for (const key of Object.keys(vocab.actions[act.action].params)) r.setFieldValue(act[key], `P_${key}`);
      (prev ? prev.nextConnection : bot.getInput("RULES").connection).connect(r.previousConnection);
      prev = r;
      let prevCond = null;
      for (const raw of rule.if || []) {
        const neg = "not" in raw;
        const cond = neg ? raw.not : raw;
        if (!vocab.sensors[cond.sensor]) throw new Error(`unknown sensor "${cond.sensor}"`);
        const c = addBlock(`mm_s_${cond.sensor}`);
        c.setFieldValue(neg ? "not" : "is", "NEG");
        for (const key of Object.keys(vocab.sensors[cond.sensor].params)) c.setFieldValue(cond[key], `P_${key}`);
        if (vocab.sensors[cond.sensor].kind === "number") c.setFieldValue(cond.op, "OP");
        if (vocab.sensors[cond.sensor].kind !== "bool") c.setFieldValue(String(cond.value), "VALUE");
        (prevCond ? prevCond.nextConnection : r.getInput("WHEN").connection).connect(c.previousConnection);
        prevCond = c;
      }
    }
  } finally {
    Blockly.Events.enable();
  }
  onChange();
}

/** Load a bot into blocks; on failure, report it and keep the workspace usable. */
function loadSafely(spec, quiet = false) {
  try {
    specToWorkspace(spec);
    return true;
  } catch (err) {
    Blockly.Events.enable();
    if (!quiet) {
      showProblems([`Couldn't show "${spec.name || "this bot"}" as blocks: ${err.message}`]);
      clearTimeout(changeTimer);  // keep the error visible instead of "ready"
    }
    return false;
  }
}

// ---- side panel ------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

function showProblems(list) {
  const el = $("ed-problems");
  const chip = $("ed-check");
  el.innerHTML = "";
  for (const p of list) { const li = document.createElement("li"); li.textContent = p; el.appendChild(li); }
  chip.classList.toggle("ok", !list.length);
  chip.classList.toggle("bad", !!list.length);
  chip.textContent = list.length ? `⚠ ${list.length} problem${list.length > 1 ? "s" : ""}` : "✓ Ready";
  el.hidden = !list.length;  // the list only takes space when there's something to fix
}

/** Show a bot (spec object) in the workspace, e.g. one opened from a share link. */
export function openInEditor(spec) {
  if (ws) loadSafely(spec);
}

function closeMenu() {
  $("ed-menu").open = false;
}

function onChange() {
  if (preview && !preview.stale) {
    preview.stale = true;
    setLit([]);
    $("ed-decision").textContent = "You edited the bot. Press ▶ Preview to restart with your changes.";
  }
  clearTimeout(changeTimer);
  changeTimer = setTimeout(() => {
    const { spec, problems } = workspaceToSpec();
    const text = JSON.stringify(spec);
    const errors = JSON.parse(ctx.api.check_bot(text));
    showProblems([...problems, ...errors]);
    const report = problems.length || errors.length ? { error: "problems" } : JSON.parse(ctx.api.analyze_bot(text));
    renderExplain($("ed-explain-body"), $("ed-explain-count"), spec, report);
    try { localStorage.setItem("mirrormatch.draft", text); } catch { /* storage unavailable */ }
  }, 250);
}

function fillTemplateSelect() {
  const sel = $("ed-template");
  sel.innerHTML = "";
  for (const [key, spec] of Object.entries(ctx.starters)) sel.add(new Option(`starter: ${spec.name || key}`, `starter:${key}`));
  for (const label of Object.keys(ctx.uploaded())) sel.add(new Option(`yours: ${label}`, `upload:${label}`));
}

function currentSpecText() {
  return JSON.stringify(workspaceToSpec().spec, null, 2);
}

function save() {
  const { spec } = workspaceToSpec();
  const errors = JSON.parse(ctx.api.check_bot(JSON.stringify(spec)));
  if (errors.length) { showProblems(errors); return null; }
  ctx.saveBot(spec.name, JSON.stringify(spec, null, 2));
  fillTemplateSelect();
  $("ed-result").textContent = `Saved "${spec.name}" to your bots.`;
  return spec.name;
}

function download() {
  const { spec } = workspaceToSpec();
  const blob = new Blob([currentSpecText()], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${spec.name.replace(/[^\w-]+/g, "_") || "bot"}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function runTest() {
  if (testRun) { testRun.cancel = true; return; }
  const { spec } = workspaceToSpec();
  const text = JSON.stringify(spec);
  const errors = JSON.parse(ctx.api.check_bot(text));
  if (errors.length) { showProblems(errors); return; }
  const opp = ctx.resolveBot($("ed-opponent").value);
  const games = Number($("ed-games").value);
  const run = { cancel: false, w: 0, l: 0, d: 0, g: 0 };
  testRun = run;
  $("ed-test").textContent = "Stop";
  const seed0 = Math.floor(Math.random() * 2 ** 30);
  const step = () => {
    if (run.cancel || run.g >= games) {
      testRun = null;
      $("ed-test").textContent = "Run test";
      $("ed-result").textContent =
        `${run.cancel ? "Stopped: " : ""}vs ${opp.label}: ${run.w} won, ${run.l} lost, ${run.d} drawn (of ${run.g})`;
      return;
    }
    const res = ctx.api.play_game(text, opp.spec, seed0 + run.g, run.g % 2 === 0);
    run[res[0]] += 1;
    run.g += 1;
    $("ed-result").textContent = `vs ${opp.label}: ${run.g}/${games} played · ${run.w}-${run.l}-${run.d}`;
    setTimeout(step, 0);  // yield so the page stays responsive
  };
  step();
}

function watchVs() {
  const name = save();
  if (name) ctx.watch(`upload:${name}`, $("ed-opponent").value);
}

// ---- live preview ----------------------------------------------------------------

function setLit(ids) {
  const next = new Set(ids);
  for (const id of lit) if (!next.has(id) && ws.getBlockById(id)) ws.highlightBlock(id, false);
  for (const id of next) if (!lit.has(id) && ws.getBlockById(id)) ws.highlightBlock(id, true);
  lit = next;
}

function describeRule(rule) {
  const act = rule.then;
  const args = Object.keys(vocab.actions[act.action].params).map((k) => pretty(act[k]));
  return [ACTION_TEXT[act.action] || pretty(act.action), ...args].join(" ");
}

function showDecision(snap) {
  const d = snap.debug && snap.debug[0];
  if (!preview || preview.stale || !d || d.kind !== "rules") return;
  setLit(Object.values(d.fired).map((f) => preview.ruleBlocks[f.index]).filter(Boolean));
  const line = (label, ch) => {
    const f = d.fired[ch];
    return f ? `${label}: <b>${describeRule(preview.rules[f.index])}</b> (#${f.index + 1})` : `${label}: none`;
  };
  const couldnt = d.status.filter((st) => st === "couldnt").length;
  $("ed-decision").innerHTML = [line("Move", "move"), line("Ability", "ability"), `Mode: <b>${d.mode}</b>`].join("<br>") +
    (couldnt ? `<br>${couldnt} matching action${couldnt > 1 ? "s" : ""} couldn't happen and passed to the next.` : "");
}

function startPreview() {
  const { spec, ruleBlocks } = workspaceToSpec();
  const text = JSON.stringify(spec);
  const errors = JSON.parse(ctx.api.check_bot(text));
  if (errors.length) { showProblems(errors); return; }
  if (preview) preview.session.destroy();
  const opp = ctx.resolveBot($("ed-opponent").value);
  const seed = Math.floor(Math.random() * 2 ** 31);
  const session = ctx.api.Session(text, opp.spec, "normal", seed);
  preview = {
    session, snap: JSON.parse(session.snapshot()), acc: 0, paused: false, stale: false,
    ruleBlocks, rules: spec.rules,
    view: { names: [spec.name, opp.label], human: false, aimLineFor: -1, moveMarker: null, speed: 1, showDecisions: true },
  };
  previewRenderer.resetEffects();
  setLit([]);
  $("ed-pause").textContent = "Pause";
  $("ed-preview").textContent = "↻ Restart";
}

let previewLast = performance.now();
function previewFrame(now) {
  const dt = Math.min((now - previewLast) / 1000, 0.25);
  previewLast = now;
  requestAnimationFrame(previewFrame);
  if (!preview || $("builder").hidden) return;
  const speed = Number($("ed-speed").value);
  preview.view.speed = speed;
  if (!preview.paused && !preview.snap.done) {
    preview.acc += dt * speed;
    const n = Math.floor(preview.acc * ctx.info.tick_rate);
    if (n > 0) {
      preview.acc -= n / ctx.info.tick_rate;
      preview.snap = JSON.parse(preview.session.advance(n));
      showDecision(preview.snap);
    }
  }
  previewRenderer.style = ctx.graphicsStyle();
  previewRenderer.draw(preview.snap, preview.view);
}

// ---- setup -----------------------------------------------------------------------

export function initEditor(context) {
  ctx = context;
  vocab = ctx.vocab;
  defineBlocks();
  const theme = Blockly.Theme.defineTheme("mirrormatch", {
    base: Blockly.Themes.Classic,
    componentStyles: {
      workspaceBackgroundColour: "#1c2028", toolboxBackgroundColour: "#12141a", toolboxForegroundColour: "#e1e4eb",
      flyoutBackgroundColour: "#222630", flyoutForegroundColour: "#cfd3dc", flyoutOpacity: 1,
      scrollbarColour: "#596075", scrollbarOpacity: 0.5, insertionMarkerColour: "#ffffff", insertionMarkerOpacity: 0.3,
    },
    fontStyle: { family: "system-ui, sans-serif", size: 11 },
  });
  ws = Blockly.inject("blockly", {
    toolbox: toolbox(), theme, renderer: "zelos", trashcan: true, sounds: false,
    zoom: { controls: true, wheel: true, startScale: 0.85 }, move: { scrollbars: true, drag: true, wheel: false },
  });
  ws.addChangeListener((e) => { if (!e.isUiEvent) onChange(); });
  setupBuildPanels(ws, Blockly);

  for (const o of ctx.botOptions()) $("ed-opponent").add(new Option(o.label, o.value));
  $("ed-opponent").value = "builtin:dodger";
  fillTemplateSelect();
  $("ed-check").addEventListener("click", () => { if ($("ed-problems").childElementCount) $("ed-problems").hidden = !$("ed-problems").hidden; });
  for (const id of ["ed-new", "ed-load", "ed-save", "ed-download"]) $(id).addEventListener("click", closeMenu);
  document.addEventListener("click", (e) => { if (!$("ed-menu").contains(e.target)) closeMenu(); });
  $("ed-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    closeMenu();
    if (!file) return;
    let spec;
    try { spec = JSON.parse(await file.text()); } catch { showProblems([`${file.name} isn't valid JSON`]); return; }
    const errors = JSON.parse(ctx.api.check_bot(JSON.stringify(spec)));
    if (errors.length) { showProblems([`${file.name}: ${errors[0]}`, ...errors.slice(1)]); return; }
    loadSafely(spec);
  });
  $("ed-load").addEventListener("click", () => {
    const v = $("ed-template").value;
    const [kind, ...rest] = v.split(":");
    const key = rest.join(":");
    const spec = kind === "starter" ? ctx.starters[key] : JSON.parse(ctx.uploaded()[key]);
    loadSafely(spec);
  });
  $("ed-new").addEventListener("click", () =>
    specToWorkspace({ name: "my bot", version: vocab.version, rules: [{ if: [], then: { action: "shoot", aim: "lead" } }, { if: [], then: { action: "approach" } }] }));
  previewRenderer = new Renderer($("ed-canvas"), ctx.info);
  $("ed-preview").addEventListener("click", startPreview);
  $("ed-pause").addEventListener("click", () => {
    if (!preview) return;
    preview.paused = !preview.paused;
    $("ed-pause").textContent = preview.paused ? "Resume" : "Pause";
  });
  requestAnimationFrame(previewFrame);
  $("ed-save").addEventListener("click", save);
  $("ed-download").addEventListener("click", download);
  $("ed-share").addEventListener("click", () => {
    closeMenu();
    const { spec, problems } = workspaceToSpec();
    const text = JSON.stringify(spec);
    if (problems.length || JSON.parse(ctx.api.check_bot(text)).length) { toast("Fix the bot's problems before sharing it."); return; }
    copyShareLink("bot", text, `"${spec.name || "your bot"}"`);
  });
  $("ed-test").addEventListener("click", runTest);
  $("ed-watch").addEventListener("click", watchVs);

  let draft = null;
  try { draft = JSON.parse(localStorage.getItem("mirrormatch.draft") || "null"); } catch { draft = null; }
  if (!draft || !loadSafely(draft, true)) loadSafely(ctx.starters.leader);
}

export function onEditorShown() {
  if (ws) Blockly.svgResize(ws);
}

// Exposed for automated checks.
export const editorDebug = {
  workspaceToSpec: () => workspaceToSpec(), specToWorkspace: (s) => specToWorkspace(s),
  preview: () => preview && { tick: preview.snap.tick, done: preview.snap.done, stale: preview.stale, lit: [...lit],
                              debug: preview.snap.debug },
};
