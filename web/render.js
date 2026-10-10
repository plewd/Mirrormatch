// Canvas renderer: a port of arena/render.py. Draws snapshots; never changes the sim.
//
// Two styles: "classic" is the original flat look; "polished" adds cosmetic layers
// on top (particles, icons, glows, shadows) without changing what anything means.
import { label } from "./settings.js";
import { Effects } from "./effects.js";
import { drawIcon } from "./icons.js";
import { actionShort } from "./labels.js";

export const HUD_HEIGHT = 56;
export const STYLES = ["polished", "classic"];

const C = {
  bg: "#12141a", floor: "#222630", grid: "#2a2f3b", border: "#5a6278",
  text: "#e1e4eb", dim: "#828896", cast: "#ffe678", shield: "#78e6ff",
  root: "#aaaab9", wall: "#c8cddc", pickup: "#fac850", heal: "#6edc82",
  players: ["#50a0ff", "#f05a50"],
  lights: ["#a9d0ff", "#ffaaa3"],  // highlight tints for the polished champion shading
  rule: { move: "#6fcf8f", ability: "#e89350", mode: "#4fb3d1" },  // rule-word text colors (style.css --*-text)
};
const BIG_PROJECTILE = 50;  // above this radius, polished draws a translucent wave instead of a solid ball
const CAN_HIT = ["boomerang", "root", "hook", "blast"];  // items with a hit rate (wall and shield have none)
const CORE = { root: C.root, boomerang: C.pickup, hook: C.wall };

export class Renderer {
  constructor(canvas, info) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.info = info;
    this.style = "polished";
    this.effects = new Effects();
    this.lastDraw = null;
    this.doneAt = null;
  }

  get polished() { return this.style === "polished"; }

  /** Forget effects from the previous match (call when a new one starts). */
  resetEffects() {
    this.effects = new Effects();
    this.doneAt = null;
  }

  // world -> canvas pixels (the canvas is sized to the arena plus the HUD strip)
  sx(x) { return x; }
  sy(y) { return HUD_HEIGHT + y; }

  toWorld(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const scale = this.canvas.width / rect.width;
    return [(clientX - rect.left) * scale, (clientY - rect.top) * scale - HUD_HEIGHT];
  }

  draw(snap, view) {
    const g = this.ctx;
    const { width: W, height: H } = this.info;
    const now = performance.now();
    const dt = this.lastDraw === null ? 0 : Math.min((now - this.lastDraw) / 1000, 0.1);
    this.lastDraw = now;
    const t = now / 1000;
    if (this.polished) {
      this.effects.observe(snap);
      this.effects.update(dt, snap);
    }
    g.save();
    const [ox, oy] = this.polished ? this.effects.shakeOffset() : [0, 0];
    g.translate(ox, oy);  // screen shake moves the arena, never the HUD
    g.fillStyle = C.bg;
    g.fillRect(0, 0, this.canvas.width, this.canvas.height);
    g.fillStyle = C.floor;
    g.fillRect(0, HUD_HEIGHT, W, H);
    g.strokeStyle = C.grid;
    g.lineWidth = 1;
    g.beginPath();
    for (let x = 100; x < W; x += 100) { g.moveTo(x + 0.5, this.sy(0)); g.lineTo(x + 0.5, this.sy(H)); }
    for (let y = 100; y < H; y += 100) { g.moveTo(0, this.sy(y) + 0.5); g.lineTo(W, this.sy(y) + 0.5); }
    g.stroke();
    if (this.polished) {  // soft vignette toward the edges
      const v = g.createRadialGradient(W / 2, this.sy(H / 2), H * 0.35, W / 2, this.sy(H / 2), W * 0.7);
      v.addColorStop(0, "rgba(0,0,0,0)");
      v.addColorStop(1, "rgba(0,0,0,0.38)");
      g.fillStyle = v;
      g.fillRect(0, HUD_HEIGHT, W, H);
    }
    g.strokeStyle = C.border;
    g.lineWidth = 2;
    g.strokeRect(1, HUD_HEIGHT + 1, W - 2, H - 2);

    const color = (owner) => C.players[owner];

    if (view.moveMarker && !snap.done) {
      const [mx, my] = view.moveMarker;
      g.strokeStyle = C.players[0];
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(mx - 6, this.sy(my) - 6); g.lineTo(mx + 6, this.sy(my) + 6);
      g.moveTo(mx - 6, this.sy(my) + 6); g.lineTo(mx + 6, this.sy(my) - 6);
      g.stroke();
    }

    this.drawHeal(snap.heal, t);

    for (const pk of snap.pickups) {
      if (this.polished) { this.drawPickupPolished(pk, t); continue; }
      g.strokeStyle = C.pickup;
      g.lineWidth = 3;
      g.beginPath();
      g.arc(pk.x, this.sy(pk.y), this.info.pickup_radius, 0, Math.PI * 2);
      g.stroke();
      g.fillStyle = C.pickup;
      g.font = "bold 15px system-ui, sans-serif";
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.fillText(pk.ability[0].toUpperCase(), pk.x, this.sy(pk.y) + 1);
    }

    for (const z of snap.zones) {
      g.fillStyle = color(z.owner) + "33";
      g.beginPath(); g.arc(z.x, this.sy(z.y), z.r, 0, Math.PI * 2); g.fill();
      g.fillStyle = color(z.owner) + "77";
      g.beginPath(); g.arc(z.x, this.sy(z.y), Math.max(1, z.r * z.frac), 0, Math.PI * 2); g.fill();
      g.strokeStyle = color(z.owner);
      g.lineWidth = 2;
      g.beginPath(); g.arc(z.x, this.sy(z.y), z.r, 0, Math.PI * 2); g.stroke();
    }

    for (const w of snap.walls) {
      g.lineCap = "round";
      g.strokeStyle = C.wall; g.lineWidth = 10;
      g.beginPath(); g.moveTo(w.ax, this.sy(w.ay)); g.lineTo(w.bx, this.sy(w.by)); g.stroke();
      g.strokeStyle = color(w.owner); g.lineWidth = 2;
      g.beginPath(); g.moveTo(w.ax, this.sy(w.ay)); g.lineTo(w.bx, this.sy(w.by)); g.stroke();
      g.lineCap = "butt";
    }

    for (const p of snap.projectiles) {
      const col = color(p.owner);
      if (p.ability === "hook") {
        const o = snap.champions[p.owner];
        g.strokeStyle = C.root; g.lineWidth = 2;
        g.beginPath(); g.moveTo(o.x, this.sy(o.y)); g.lineTo(p.x, this.sy(p.y)); g.stroke();
      }
      if (this.polished && p.r > BIG_PROJECTILE) {  // a huge slow wave (root shot): see-through, glowing edge
        g.fillStyle = (CORE[p.ability] || "#ffffff") + "33";
        g.beginPath(); g.arc(p.x, this.sy(p.y), p.r, 0, Math.PI * 2); g.fill();
        g.shadowColor = col; g.shadowBlur = 18;
        g.strokeStyle = col; g.lineWidth = 3;
        g.beginPath(); g.arc(p.x, this.sy(p.y), p.r, 0, Math.PI * 2); g.stroke();
        g.shadowBlur = 0;
        continue;
      }
      g.strokeStyle = col;
      g.lineWidth = Math.max(2, p.r * 0.5);
      g.beginPath();
      g.moveTo(p.x - p.dx * p.trail, this.sy(p.y - p.dy * p.trail));
      g.lineTo(p.x, this.sy(p.y));
      g.stroke();
      if (this.polished) { g.shadowColor = col; g.shadowBlur = 16; }
      g.fillStyle = CORE[p.ability] || "#ffffff";
      g.beginPath(); g.arc(p.x, this.sy(p.y), Math.max(3, p.r), 0, Math.PI * 2); g.fill();
      g.shadowBlur = 0;
      g.strokeStyle = col; g.lineWidth = 3;
      g.beginPath(); g.arc(p.x, this.sy(p.y), Math.max(3, p.r), 0, Math.PI * 2); g.stroke();
    }

    const r = this.info.champion_radius;
    snap.champions.forEach((c, i) => {
      const col = color(i);
      const cx = c.x, cy = this.sy(c.y);
      if (c.forced) {  // motion trail
        for (const k of [3, 2, 1]) {
          g.globalAlpha = 0.5 / (k + 1);
          g.fillStyle = col;
          g.beginPath(); g.arc(c.x - c.vx * k, this.sy(c.y - c.vy * k), r, 0, Math.PI * 2); g.fill();
        }
        g.globalAlpha = 1;
      }
      if (this.polished) {  // contact shadow, then a lit body
        g.fillStyle = "rgba(0,0,0,0.35)";
        g.beginPath(); g.ellipse(cx + 4, cy + r * 0.75, r * 0.95, r * 0.4, 0, 0, Math.PI * 2); g.fill();
        const body = g.createRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 0.1, cx, cy, r);
        body.addColorStop(0, C.lights[i]);
        body.addColorStop(0.55, col);
        body.addColorStop(1, col);
        g.fillStyle = body;
      } else {
        g.fillStyle = col;
      }
      g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
      if (c.rooted) {
        g.strokeStyle = C.root; g.lineWidth = 4;
        g.beginPath(); g.arc(cx, cy, r + 3, 0, Math.PI * 2); g.stroke();
        g.lineWidth = 3;
        for (let k = 0; k < 8; k++) {
          const a = (k * Math.PI) / 4;
          g.beginPath();
          g.moveTo(cx + Math.cos(a) * (r + 3), cy + Math.sin(a) * (r + 3));
          g.lineTo(cx + Math.cos(a) * (r + 11), cy + Math.sin(a) * (r + 11));
          g.stroke();
        }
      }
      if (c.shielded) {
        if (this.polished) { g.shadowColor = C.shield; g.shadowBlur = 12; }
        g.strokeStyle = C.shield; g.lineWidth = 3;
        g.beginPath(); g.arc(cx, cy, r + 9 + (this.polished ? Math.sin(t * 6) * 1.5 : 0), 0, Math.PI * 2); g.stroke();
        g.shadowBlur = 0;
      }
      if (c.cast) {
        g.strokeStyle = C.cast; g.lineWidth = 4;
        g.beginPath();
        g.arc(cx, cy, r + 6, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(c.cast.progress, 0.02));
        g.stroke();
        if (i === view.aimLineFor) {  // only your own aim is visible, as for bots
          g.lineWidth = 2;
          g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + c.cast.dir[0] * 120, cy + c.cast.dir[1] * 120); g.stroke();
        }
      }
      let pipY = cy - r - 18;
      if (pipY < HUD_HEIGHT + 4) pipY = cy + r + 12;
      const hp = this.info.champion_hp;
      for (let k = 0; k < hp; k++) {
        g.fillStyle = k < c.hp ? col : "#464650";
        g.fillRect(cx - (hp - 1) * 9 + k * 18 - 6, pipY, 12, 6);
      }
    });

    if (view.showSeen && snap.debug) this.drawSeen(snap);
    if (view.showDecisions && snap.debug) this.drawDecisions(snap);
    if (this.polished) this.effects.draw(g, (y) => this.sy(y));
    g.restore();  // end of screen shake

    this.drawHud(snap, view);
    if (snap.done) {
      if (this.doneAt === null) this.doneAt = now;
      this.drawEnd(snap, view, this.polished ? Math.min(1, (now - this.doneAt) / 400) : 1);
    } else {
      this.doneAt = null;
    }
  }

  /** Each bot's view at its last decision, which lags behind the game (reaction delay plus
   *  decision rate): dashed rings for the enemy shots it saw and where it thought the enemy
   *  was, a solid ring and a line for the shot it read as coming at it, and the view's age. */
  drawSeen(snap) {
    const g = this.ctx;
    const r = this.info.champion_radius;
    snap.champions.forEach((c, i) => {
      const seen = snap.debug[i] && snap.debug[i].seen;
      if (!seen) return;  // a human, or no decision yet
      const col = C.players[i];
      g.save();
      g.strokeStyle = col;
      g.globalAlpha = 0.85;
      g.lineWidth = 2;
      g.setLineDash([5, 4]);
      g.beginPath(); g.arc(seen.enemy[0], this.sy(seen.enemy[1]), r, 0, Math.PI * 2); g.stroke();
      seen.projectiles.forEach((pr, k) => {
        if (k === seen.threat) return;
        g.beginPath(); g.arc(pr.x, this.sy(pr.y), Math.max(pr.r, 6), 0, Math.PI * 2); g.stroke();
      });
      const t = seen.threat === null ? null : seen.projectiles[seen.threat];
      if (t) {
        g.setLineDash([]);
        g.lineWidth = 3;
        g.globalAlpha = 1;
        g.beginPath(); g.arc(t.x, this.sy(t.y), Math.max(t.r, 6) + 3, 0, Math.PI * 2); g.stroke();
        g.lineWidth = 1.5;
        g.setLineDash([2, 4]);
        g.beginPath(); g.moveTo(t.x, this.sy(t.y)); g.lineTo(seen.me[0], this.sy(seen.me[1])); g.stroke();
      }
      g.restore();
      // Below the champion; further down if the HP pips and decision label moved there (near the top),
      // or above the decision label near the bottom edge.
      const cy = this.sy(c.y);
      let y = cy - r - 18 < HUD_HEIGHT + 4 ? cy + r + 44 : cy + r + 16;
      if (y > this.canvas.height - 8) y = cy - r - 74;
      g.font = "600 11px system-ui, sans-serif";
      g.textAlign = "center";
      g.textBaseline = "middle";
      const text = `${t ? "⚠ " : ""}view ${seen.age.toFixed(2)} s old`;
      const w = g.measureText(text).width + 10;
      g.fillStyle = "rgba(10, 12, 16, 0.72)";
      g.beginPath(); g.roundRect(c.x - w / 2, y - 8, w, 16, 5); g.fill();
      g.fillStyle = col;
      g.fillText(text, c.x, y + 1);
    });
  }

  /** Small labels over each bot saying what it decided last ("strafe · shoot"), each part
   *  colored like its block (move, ability, mode), after a dot in the bot's own color. */
  drawDecisions(snap) {
    const g = this.ctx;
    const r = this.info.champion_radius;
    snap.champions.forEach((c, i) => {
      const d = snap.debug[i];
      if (!d) return;  // a human
      const parts = [];  // [text, color]
      if (d.kind === "rules") {
        if (d.fired.move) parts.push([actionShort(d.fired.move.action), C.rule.move]);
        if (d.fired.ability) parts.push([actionShort(d.fired.ability.action), C.rule.ability]);
        if (!parts.length) parts.push(["nothing", C.dim]);
        if (d.mode !== "normal") parts.push([d.mode, C.rule.mode]);
      } else if (d.cast) {
        parts.push([`cast ${d.cast}`, C.rule.ability]);
      } else {
        parts.push([d.moving ? "moving" : "waiting", d.moving ? C.rule.move : C.dim]);
      }
      g.font = "600 12px system-ui, sans-serif";
      const SEP = "  ·  ", DOT = 10;
      const widths = parts.map(([t]) => g.measureText(t).width);
      const sepW = g.measureText(SEP).width;
      const w = DOT + widths.reduce((a, b) => a + b, 0) + sepW * (parts.length - 1) + 14;
      let y = this.sy(c.y) - r - 46;
      if (y < HUD_HEIGHT + 4) y = this.sy(c.y) + r + 26;
      g.fillStyle = "rgba(10, 12, 16, 0.78)";
      g.beginPath();
      g.roundRect(c.x - w / 2, y - 10, w, 20, 6);
      g.fill();
      let x = c.x - w / 2 + 7;
      g.fillStyle = C.players[i];
      g.beginPath(); g.arc(x + 3, y, 3.5, 0, Math.PI * 2); g.fill();
      x += DOT;
      g.textAlign = "left";
      g.textBaseline = "middle";
      parts.forEach(([text, color], k) => {
        if (k > 0) { g.fillStyle = C.dim; g.fillText(SEP, x, y + 1); x += sepW; }
        g.fillStyle = color;
        g.fillText(text, x, y + 1);
        x += widths[k];
      });
    });
  }

  drawPickupPolished(pk, t) {
    const g = this.ctx;
    const r = this.info.pickup_radius;
    const bob = Math.sin(t * 3 + pk.x * 0.01) * 3;
    const cx = pk.x, cy = this.sy(pk.y) + bob;
    g.fillStyle = "rgba(0,0,0,0.3)";  // shadow stays on the ground
    g.beginPath(); g.ellipse(pk.x, this.sy(pk.y) + r + 4, r * 0.7, r * 0.22, 0, 0, Math.PI * 2); g.fill();
    const glow = g.createRadialGradient(cx, cy, 2, cx, cy, r * 1.8);
    glow.addColorStop(0, "rgba(250,200,80,0.45)");
    glow.addColorStop(1, "rgba(250,200,80,0)");
    g.fillStyle = glow;
    g.beginPath(); g.arc(cx, cy, r * 1.8, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#1c2028";
    g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
    g.strokeStyle = C.pickup; g.lineWidth = 2.5;
    g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.stroke();
    drawIcon(g, pk.ability, cx, cy, r * 0.62, C.pickup);
  }

  drawHeal(h, t = 0) {
    if (!h) return;
    const g = this.ctx;
    const cx = h.x, cy = this.sy(h.y);
    if (h.up && this.polished) {
      const pulse = 1 + Math.sin(t * 4) * 0.08;
      const glow = g.createRadialGradient(cx, cy, 2, cx, cy, h.r * 2.6);
      glow.addColorStop(0, "rgba(110,220,130,0.55)");
      glow.addColorStop(1, "rgba(110,220,130,0)");
      g.fillStyle = glow;
      g.beginPath(); g.arc(cx, cy, h.r * 2.6, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#1c2a22";
      g.beginPath(); g.arc(cx, cy, h.r * pulse, 0, Math.PI * 2); g.fill();
      g.strokeStyle = C.heal; g.lineWidth = 3;
      g.beginPath(); g.arc(cx, cy, h.r * pulse, 0, Math.PI * 2); g.stroke();
      drawIcon(g, "heal", cx, cy, h.r * 0.8, C.heal);
      return;
    }
    if (h.up) {
      g.fillStyle = C.heal;
      g.beginPath(); g.arc(cx, cy, h.r, 0, Math.PI * 2); g.fill();
      g.strokeStyle = C.bg; g.lineWidth = 4;
      g.beginPath();
      g.moveTo(cx - h.r / 2, cy); g.lineTo(cx + h.r / 2, cy);
      g.moveTo(cx, cy - h.r / 2); g.lineTo(cx, cy + h.r / 2);
      g.stroke();
      return;
    }
    g.strokeStyle = "#3c5a46"; g.lineWidth = 1;  // where it will appear
    g.beginPath(); g.arc(cx, cy, h.r, 0, Math.PI * 2); g.stroke();
    if (h.in < 3) {  // countdown ring for the last few seconds
      g.strokeStyle = C.heal; g.lineWidth = 3;
      g.beginPath(); g.arc(cx, cy, h.r + 4, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - h.in / 3)); g.stroke();
    }
  }

  drawHud(snap, view) {
    const g = this.ctx;
    const W = this.canvas.width;
    g.fillStyle = C.bg;
    g.fillRect(0, 0, W, HUD_HEIGHT);
    g.font = "600 15px system-ui, sans-serif";
    g.textBaseline = "top";
    const hp = this.info.champion_hp;
    const [left, right] = snap.champions;

    g.textAlign = "left";
    g.fillStyle = C.players[0];
    g.fillText(`${view.names[0]}  HP ${left.hp}/${hp}`, 14, 8);
    let bx = 14;
    this.info.loadout.forEach((aid, slot) => {
      const cd = left.cooldowns[aid];
      this.slot(bx, `${label(aid)} ${aid}${cd.left > 0 ? " " + cd.left.toFixed(1) + "s" : ""}`, cd.left <= 0, 1 - cd.frac, C.players[0]);
      bx += 130;
    });
    this.slot(bx, left.item ? `${label("item")} ${left.item}` : `${label("item")} –`, !!left.item, left.item ? 1 : 0, C.pickup);
    if (this.polished && left.item) drawIcon(g, left.item, bx + 108, 39, 7, C.bg);

    g.textAlign = "right";
    g.fillStyle = C.players[1];
    g.font = "600 15px system-ui, sans-serif";
    g.textBaseline = "top";
    g.fillText(`${view.names[1]}  HP ${right.hp}/${hp}${right.item ? `  [${right.item}]` : ""}`, W - 14, 8);

    g.textAlign = "center";
    g.fillStyle = C.text;
    g.fillText(`${snap.time_left.toFixed(1)}s${view.speed > 1 ? `  (${view.speed}×)` : ""}`, W / 2, 18);
  }

  slot(x, text, ready, fill, color) {
    const g = this.ctx;
    g.fillStyle = "#3c404c";
    g.fillRect(x, 30, 120, 18);
    g.fillStyle = ready ? color : C.dim;
    g.fillRect(x, 30, 120 * Math.max(0, Math.min(1, fill)), 18);
    g.fillStyle = ready ? C.bg : C.text;
    g.font = "600 13px system-ui, sans-serif";
    g.textAlign = "left";
    g.textBaseline = "middle";
    g.fillText(text, x + 5, 39);
  }

  drawEnd(snap, view, fade = 1) {
    const g = this.ctx;
    const W = this.canvas.width, Ht = this.canvas.height;
    g.save();
    g.globalAlpha = fade;
    g.fillStyle = "rgba(0, 0, 0, 0.62)";
    g.fillRect(0, 0, W, Ht);
    let title, col;
    if (snap.winner === null) { title = "Draw"; col = C.text; }
    else if (view.human) { title = snap.winner === 0 ? "You win" : "You lose"; col = C.players[snap.winner]; }
    else { title = `${view.names[snap.winner]} wins`; col = C.players[snap.winner]; }
    const withStats = !!snap.stats;
    const top = withStats ? Ht / 2 - 250 : Ht / 2 - 40;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillStyle = col;
    g.font = "700 64px system-ui, sans-serif";
    g.fillText(title, W / 2, top);
    g.fillStyle = C.text;
    g.font = "16px system-ui, sans-serif";
    g.fillText(view.human ? `${label("restart")}: play again  ·  Esc: opponents` : `${label("restart")}: play again`, W / 2, top + 54);
    if (withStats) this.drawStats(snap.stats, view, top + 100);
    g.restore();
  }

  /** A compact table comparing both players' match stats. */
  drawStats(stats, view, y0) {
    const g = this.ctx;
    const W = this.canvas.width;
    const rate = this.info.tick_rate || 30;
    const loadout = this.info.loadout || ["bolt", "dash"];
    const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
    const breakdown = (o) => {
      const parts = Object.entries(o).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${v}`);
      return parts.length ? `${sum(o)}  (${parts.join(", ")})` : "0";
    };
    const ratio = (st, aid) => {
      const c = st.casts[aid] || 0;
      return c ? `${st.hits[aid] || 0}/${c}  (${Math.round((100 * (st.hits[aid] || 0)) / c)}%)` : "–";
    };
    const items = (st) => {
      const used = Object.keys(st.casts).filter((a) => !loadout.includes(a) && CAN_HIT.includes(a));
      return used.length ? used.map((a) => `${a} ${st.hits[a] || 0}/${st.casts[a]}`).join(", ") : "–";
    };
    const rows = [
      ["Bolt hits", (st) => ratio(st, "bolt")],
      ["Item hits", items],
      ["Damage dealt", (st) => breakdown(st.dealt)],
      ["Damage taken", (st) => breakdown(st.taken)],
      ["Dashes", (st) => String(st.casts.dash || 0)],
      ["Pickups", (st) => `${st.pickups} taken, ${st.items_used} used`],
      ["Heals", (st) => (st.heals ? `${st.heals}  (+${st.healed} HP)` : "0")],
      ["Shield blocks", (st) => String(st.blocks)],
      ["Near the center", (st) => `${(st.center_ticks / rate).toFixed(1)}s`],
      ["Distance moved", (st) => `${Math.round(st.distance)} u`],
    ];
    const x0 = W / 2 - 330, x1 = W / 2 - 40, x2 = W / 2 + 190, rowH = 30;
    g.fillStyle = "rgba(18, 20, 26, 0.85)";
    g.beginPath(); g.roundRect(x0 - 24, y0 - 26, 700, rowH * (rows.length + 1) + 22, 10); g.fill();
    g.font = "700 15px system-ui, sans-serif";
    g.textBaseline = "middle";
    g.textAlign = "left";
    g.fillStyle = C.players[0]; g.fillText(view.names[0], x1, y0);
    g.fillStyle = C.players[1]; g.fillText(view.names[1], x2, y0);
    g.font = "14px system-ui, sans-serif";
    rows.forEach(([label, fn], k) => {
      const y = y0 + rowH * (k + 1);
      g.fillStyle = C.dim; g.fillText(label, x0, y);
      g.fillStyle = C.text; g.fillText(fn(stats[0]), x1, y); g.fillText(fn(stats[1]), x2, y);
    });
  }
}
