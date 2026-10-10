// Settings: key bindings (Bolt, Dash, Item, Restart), the mouse button that moves, and the
// graphics style, in one ⚙ panel. Saved in localStorage. Every key hint on the page is a
// [data-key="bolt"] / [data-move] element, refreshed here whenever a binding changes.

const $ = (id) => document.getElementById(id);
const STORE_KEY = "mirrormatch.settings";
const DEFAULT_KEYS = { bolt: "q", dash: "w", item: "e", restart: "r" };
const DEFAULT_MOVE = 2;  // mouse button: 2 = right, 0 = left
// Taken by the rest of the page (leave a match, pause, step, focus...), so they can't be bound.
const RESERVED = new Set(["escape", " ", "tab", "enter", "arrowleft", "arrowright", "arrowup", "arrowdown",
  "shift", "control", "alt", "meta", "capslock", "dead"]);

export const settings = { keys: { ...DEFAULT_KEYS }, moveButton: DEFAULT_MOVE };
const listeners = [];

try {
  const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
  if (saved.keys) Object.assign(settings.keys, saved.keys);
  if (saved.moveButton === 0 || saved.moveButton === 2) settings.moveButton = saved.moveButton;
} catch { /* defaults */ }

function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(settings)); } catch { /* this visit only */ }
}

/** How a key is shown: "Q", "F2", "Space". */
export function keyLabel(key) {
  if (key === " ") return "Space";
  return key.length === 1 ? key.toUpperCase() : key[0].toUpperCase() + key.slice(1);
}

/** The shown key for an action ("bolt", "dash", "item", "restart"). */
export const label = (action) => keyLabel(settings.keys[action] || "?");

export const moveLabel = () => (settings.moveButton === 2 ? "Right-click" : "Left-click");

/** The action bound to a pressed key (KeyboardEvent.key, any case), or undefined. */
export function actionForKey(key) {
  const k = key.toLowerCase();
  return Object.keys(settings.keys).find((a) => settings.keys[a] === k);
}

export function onSettingsChange(fn) { listeners.push(fn); }

/** Rewrite every key hint on the page to the current bindings. */
export function refreshHints(root = document) {
  for (const el of root.querySelectorAll("[data-key]")) el.textContent = label(el.dataset.key);
  for (const el of root.querySelectorAll("[data-move]")) {
    el.textContent = el.dataset.move === "lower" ? moveLabel().toLowerCase() : moveLabel();
  }
}

function changed() {
  save();
  refreshHints();
  renderPanel();
  for (const fn of listeners) fn(settings);
}

let listening = null;  // the action waiting for a key press, while rebinding
let graphics = null;   // {get, set} from app.js

function renderPanel() {
  for (const b of document.querySelectorAll("#settings-panel [data-bind]")) {
    const action = b.dataset.bind;
    b.textContent = listening === action ? "press a key…" : label(action);
    b.classList.toggle("listening", listening === action);
  }
  for (const b of document.querySelectorAll("#set-move .chip")) b.setAttribute("aria-pressed", String(Number(b.dataset.value) === settings.moveButton));
  if (graphics) for (const b of document.querySelectorAll("#set-graphics .chip")) b.setAttribute("aria-pressed", String(b.dataset.value === graphics.get()));
}

function hint(text) { $("set-hint").textContent = text; }

const DEFAULT_HINT = "Click a key, then press the new one. Esc cancels.";

/** Wire up the ⚙ button and panel. `graphicsStyle` = {get, set} for the graphics choice. */
export function initSettings(graphicsStyle) {
  graphics = graphicsStyle;
  const panel = $("settings-panel");
  const open = (on) => {
    panel.hidden = !on;
    $("settings-btn").setAttribute("aria-expanded", String(on));
    if (!on) { listening = null; hint(DEFAULT_HINT); }
    renderPanel();
  };
  $("settings-btn").addEventListener("click", (e) => { e.stopPropagation(); open(panel.hidden); });
  document.addEventListener("pointerdown", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && !$("settings-btn").contains(e.target)) open(false);
  });
  for (const b of panel.querySelectorAll("[data-bind]")) {
    b.addEventListener("click", () => { listening = listening === b.dataset.bind ? null : b.dataset.bind; hint(DEFAULT_HINT); renderPanel(); });
  }
  for (const b of panel.querySelectorAll("#set-move .chip")) {
    b.addEventListener("click", () => { settings.moveButton = Number(b.dataset.value); changed(); });
  }
  for (const b of panel.querySelectorAll("#set-graphics .chip")) {
    b.addEventListener("click", () => { graphics.set(b.dataset.value); renderPanel(); });
  }
  $("set-reset").addEventListener("click", () => {
    Object.assign(settings.keys, DEFAULT_KEYS);
    settings.moveButton = DEFAULT_MOVE;
    listening = null;
    hint("Back to the defaults.");
    changed();
  });
  // Rebinding grabs the next key press before the rest of the page sees it (capture phase).
  window.addEventListener("keydown", (e) => {
    if (panel.hidden) return;
    if (!listening) {
      if (e.key === "Escape") { open(false); e.stopImmediatePropagation(); }
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    const key = e.key.toLowerCase();
    if (key === "escape") { listening = null; hint(DEFAULT_HINT); renderPanel(); return; }
    if (RESERVED.has(key) || e.key.length === 0) { hint(`${keyLabel(e.key)} is used elsewhere in the game; pick another key.`); return; }
    const action = listening;
    const other = actionForKey(key);
    if (other && other !== action) {
      settings.keys[other] = settings.keys[action];  // swap, so no two actions share a key
      hint(`Swapped: ${other} is now ${keyLabel(settings.keys[other])}.`);
    } else {
      hint(DEFAULT_HINT);
    }
    settings.keys[action] = key;
    listening = null;
    changed();
  }, true);
  refreshHints();
  renderPanel();
}
