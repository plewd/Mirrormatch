// The Guide tab. Its prose is static HTML; every number comes from the game's
// config (via arena_info), so the guide can't drift when stats are rebalanced.
import { drawIcon } from "./icons.js";
import { difficultyText } from "./labels.js";

const PICKUP_GOLD = "#fac850";  // the pickup color on the map (render.js C.pickup)

const NOTES = {
  bolt: "Your main damage. The cast roots you briefly: that's when you're easiest to hit.",
  dash: "A fast, fixed-distance burst toward the cursor. Can't be used while casting or rooted.",
  boomerang: "Flies out, then returns to you. Can hit on the way out and again on the way back. Turns around at the arena edge.",
  shield: "Blocks the next enemy ability of any kind while it lasts, and a successful block heals you. Timing matters.",
  root: "A huge, slow wave. No damage, but it roots whoever it hits. Follow up with Bolt.",
  wall: "Blocks every projectile (both sides') where you aim. Doesn't block movement, and standing in it doesn't protect you.",
  hook: "Pulls the enemy to you and cancels their cast. Hitting a wall or the edge pulls you there instead.",
  blast: "A long rooting cast, then a telegraphed circle that explodes after a short fuse. Walk out of it.",
};

const fmt = (v, unit = "") => (v ? `${Number.isInteger(v) ? v : v.toFixed(2).replace(/0$/, "")}${unit}` : "–");

function abilityRow(name, st, info) {
  // Your two keys are always there; pickups get their map icon and a gold tag.
  const always = info.loadout.includes(name);
  const badge = always ? `<kbd>${name === "bolt" ? "Q" : "W"}</kbd>` : `<canvas class="ab-icon" data-icon="${name}" width="40" height="40"></canvas>`;
  const kind = always ? `<span class="ab-tag">always</span>` : `<span class="ab-tag pickup">pickup · E</span>`;
  const reach = name === "dash" ? fmt(st.range, " u") : st.speed ? `${fmt(st.range, " u")} at ${fmt(st.speed)} u/s` :
    st.range ? `placed within ${fmt(st.range, " u")}` : "–";
  const effect = [
    st.damage ? `${st.damage} dmg` : "",
    name === "root" ? `roots ${fmt(st.duration, " s")}` : "",
    name === "shield" ? `lasts ${fmt(st.duration, " s")}${st.heal ? `, a block heals ${st.heal} HP` : ""}` : "",
    name === "wall" ? `${fmt(st.length, " u")} long, lasts ${fmt(st.duration, " s")}` : "",
    name === "blast" ? `${fmt(st.radius, " u")} radius, ${fmt(st.duration, " s")} fuse` : "",
    st.radius && st.speed ? `${fmt(st.radius * 2, " u")} wide` : "",
  ].filter(Boolean).join(", ") || "–";
  return `<tr><td><div class="ab-name">${badge}<div><b>${name}</b><br>${kind}</div></div></td><td>${fmt(st.cooldown, " s")}</td>` +
    `<td>${fmt(st.cast_time, " s")}</td><td>${reach}</td><td>${effect}</td><td>${NOTES[name] || ""}</td></tr>`;
}

export function initGuide(info) {
  const table = document.getElementById("guide-ability-table");
  const order = [...info.loadout, ...info.pickup_pool];
  table.innerHTML = "<tr><th>Ability</th><th>Cooldown</th><th>Cast</th><th>Reach</th><th>Effect</th><th>Notes</th></tr>" +
    order.filter((n) => info.abilities[n]).map((n) => abilityRow(n, info.abilities[n], info)).join("");
  for (const c of table.querySelectorAll("canvas.ab-icon")) {  // drawn at 2x for sharp edges
    drawIcon(c.getContext("2d"), c.dataset.icon, c.width / 2, c.height / 2, c.width * 0.36, PICKUP_GOLD);
  }

  for (const el of document.querySelectorAll("[data-info]")) el.textContent = fmt(info[el.dataset.info]);
  for (const el of document.querySelectorAll("[data-ability]")) {
    el.textContent = fmt(info.abilities[el.dataset.ability]?.[el.dataset.field]);
  }
  document.getElementById("guide-difficulty").textContent = Object.keys(info.difficulty_presets)
    .map((name) => `${name}: ${difficultyText(info, name)}`).join("; ");
}
