// The Play tab's opponent lobby: a card per bot (easiest first), the player's own bots,
// a "Build a bot" card, difficulty chips and a Play button. Plain DOM; app.js decides
// when it's shown and starts the match.
import { BOT_INFO, byStrength } from "./labels.js";

const $ = (id) => document.getElementById(id);
const PICK_KEY = "mirrormatch.opponent";
const DIFF_KEY = "mirrormatch.difficulty";

function load(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}

function store(key, value) {
  try { localStorage.setItem(key, value); } catch { /* keep for this visit */ }
}

export class Lobby {
  /** botOptions() lists {value, label} like the dropdowns; onPlay(value, difficulty) starts a match;
   *  onBuild() opens the Build tab. */
  constructor({ botOptions, difficulties, onPlay, onBuild, onBuildShared, onSaveShared }) {
    this.botOptions = botOptions;
    this.onPlay = onPlay;
    this.selected = load(PICK_KEY, "builtin:dodger");
    this.difficulty = load(DIFF_KEY, "normal");
    if (!difficulties.includes(this.difficulty)) this.difficulty = "normal";

    const chips = $("lobby-difficulty");
    for (const d of difficulties) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = d;
      b.dataset.value = d;
      b.setAttribute("aria-pressed", String(d === this.difficulty));
      b.addEventListener("click", () => this.setDifficulty(d));
      chips.append(b);
    }
    $("lobby-play").addEventListener("click", () => this.play());
    $("shared-build").addEventListener("click", () => onBuildShared(this.sharedValue));
    $("shared-save").addEventListener("click", () => onSaveShared(this.sharedValue));
    for (const link of document.querySelectorAll("[data-lobby-build]")) {
      link.addEventListener("click", (e) => { e.preventDefault(); onBuild(); });
    }
    this.render();
  }

  get visible() { return !$("lobby").hidden; }

  setDifficulty(d) {
    this.difficulty = d;
    store(DIFF_KEY, d);
    for (const b of $("lobby-difficulty").children) b.setAttribute("aria-pressed", String(b.dataset.value === d));
  }

  select(value) {
    this.selected = value;
    store(PICK_KEY, value);
    for (const card of document.querySelectorAll("#lobby .bot-card")) {
      card.setAttribute("aria-pressed", String(card.dataset.value === value));
    }
    const opt = this.botOptions().find((o) => o.value === value);
    $("lobby-play").textContent = `Play ${opt ? opt.label.replace(/ \(yours\)$/, "") : "?"} ▶`;
  }

  play() {
    if (this.botOptions().some((o) => o.value === this.selected)) this.onPlay(this.selected, this.difficulty);
  }

  /** Rebuild the cards (call when saved bots change). */
  render() {
    const opts = this.botOptions();
    const builtin = byStrength(opts.filter((o) => !o.value.startsWith("upload:") && !o.value.startsWith("shared:")));
    const yours = opts.filter((o) => o.value.startsWith("upload:"));
    // A bot from a share link leads "Your bots" (dotted outline), selected when it first appears.
    const sharedOpt = opts.find((o) => o.value.startsWith("shared:"));
    $("lobby-shared-note").hidden = !sharedOpt;
    if (sharedOpt && this.sharedValue !== sharedOpt.value) this.selected = sharedOpt.value;
    this.sharedValue = sharedOpt ? sharedOpt.value : null;

    $("lobby-builtin").replaceChildren(...builtin.map((o) => this.card(o, BOT_INFO[o.value])));
    const add = document.createElement("button");
    add.type = "button";
    add.className = "bot-card new";
    add.innerHTML = "<b>＋ Build a bot</b><span>Snap rules together from blocks</span>";
    add.addEventListener("click", () => document.querySelector("[data-lobby-build]").click());
    const sharedCard = sharedOpt ? [this.card(sharedOpt, { blurb: "Shared with you" })] : [];
    for (const c of sharedCard) c.classList.add("shared");
    $("lobby-yours").replaceChildren(...sharedCard, ...yours.map((o) => this.card(o, { blurb: "Yours, from Build" })), add);

    if (!opts.some((o) => o.value === this.selected)) this.selected = "builtin:dodger";
    this.select(this.selected);
  }

  card(opt, meta) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "bot-card";
    b.dataset.value = opt.value;
    const name = document.createElement("b");
    name.textContent = opt.label.replace(/ \(yours\)$/, "");
    const blurb = document.createElement("span");
    blurb.textContent = meta ? meta.blurb : "Trained bot";
    b.append(name, blurb);
    if (meta && meta.win !== undefined) {
      const bar = document.createElement("i");
      bar.className = "strength";
      bar.style.setProperty("--win", `${Math.max(meta.win, 2)}%`);  // a sliver even at 0, so the track reads as a bar
      bar.title = `Wins ${meta.win}% of games against the other bots`;
      b.append(bar);
    }
    b.addEventListener("click", () => this.select(opt.value));
    b.addEventListener("dblclick", () => { this.select(opt.value); this.play(); });
    return b;
  }

  /** Arrow keys move the selection through the cards; Enter plays. Returns true if handled. */
  key(e) {
    if (e.key === "Enter") {
      const other = e.target instanceof HTMLAnchorElement ||
        (e.target instanceof HTMLButtonElement && (!e.target.classList.contains("bot-card") || e.target.classList.contains("new")));
      if (other) return false;  // Enter on a link, chip or the "Build a bot" card does its own thing
      this.play();
      return true;
    }
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return false;
    const cards = [...document.querySelectorAll("#lobby .bot-card:not(.new)")];
    const i = cards.findIndex((c) => c.dataset.value === this.selected);
    const step = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1;
    const next = cards[(i + step + cards.length) % cards.length];
    if (next) { this.select(next.dataset.value); next.focus(); }
    return true;
  }
}
