// Read-only rule cards beside the arena: which rule each bot used this decision.
import { describeAction, describeCondition } from "./labels.js";

const CHANNEL = {
  approach: "move", retreat: "move", strafe: "move", go_to_pickup: "move", go_to_heal: "move", hold: "move",
  wander: "move", shoot: "ability", dash: "ability", use_item: "ability", hold_fire: "ability", set_mode: "mode",
};

export class RulePanel {
  constructor(el) {
    this.el = el;
    this.cards = [];
    this.lastStatus = null;
  }

  /** Show a bot's rules, or a short note when it has none (built-in / trained bots, humans). */
  show(specText, name, color) {
    this.cards = [];
    this.lastStatus = null;
    let spec = null;
    if (specText && specText.trim().startsWith("{")) {
      try { spec = JSON.parse(specText); } catch { spec = null; }
    }
    const head = `<div class="rp-head"><b style="color:${color}">${escape(name)}</b><span class="rp-mode"></span></div>`;
    if (!spec) {
      const why = specText === "human" ? "You're playing this side." : "A built-in or trained bot: no rules to show.";
      this.el.innerHTML = `${head}<p class="hint">${why}</p>`;
      return;
    }
    const list = spec.rules.map((r, i) => {
      const ch = CHANNEL[r.then.action] || "ability";
      const conds = (r.if || []).map((c) => `<li>${escape(describeCondition(c))}</li>`).join("") || '<li class="always">always</li>';
      return `<div class="rp-card ${ch}" data-i="${i}"><div class="rp-act"><span class="rp-n">${i + 1}</span>${escape(describeAction(r.then))}</div><ul>${conds}</ul></div>`;
    }).join("");
    this.el.innerHTML = `${head}<div class="rp-list">${list}</div>` +
      '<p class="rp-legend hint"><span class="lg fired"></span>used <span class="lg couldnt"></span>couldn\'t <span class="lg false"></span>conditions false</p>';
    this.cards = [...this.el.querySelectorAll(".rp-card")];
  }

  /** Apply the latest decision trace (from the snapshot's debug entry for this bot). */
  update(debug) {
    if (!this.cards.length || !debug || debug.kind !== "rules") return;
    const key = debug.status.join(",") + debug.mode;
    if (key === this.lastStatus) return;
    this.lastStatus = key;
    debug.status.forEach((st, i) => { if (this.cards[i]) this.cards[i].dataset.status = st; });
    this.el.querySelector(".rp-mode").textContent = debug.mode !== "normal" ? `mode: ${debug.mode}` : "";
    // Keep what's firing in view by scrolling only this panel's list (never the page).
    const first = this.cards.find((c) => c.dataset.status === "fired");
    const box = this.el.querySelector(".rp-list");
    if (first && box) {
      const top = first.offsetTop, bottom = top + first.offsetHeight;
      if (top < box.scrollTop || bottom > box.scrollTop + box.clientHeight) {
        box.scrollTo({ top: Math.max(0, top - box.clientHeight / 3), behavior: "smooth" });
      }
    }
  }
}

function escape(text) {
  return String(text).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
}
