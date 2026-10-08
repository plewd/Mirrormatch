// Cosmetic particle effects for the Polished graphics style.
//
// Events are found by comparing consecutive snapshots (an HP drop is a hit, a
// projectile that vanished ended somewhere, ...), so the sim knows nothing about
// effects and replays stay exact. Effects run on wall-clock time, not game ticks.

const MAX_PARTICLES = 700;
const PLAYER = ["#50a0ff", "#f05a50"];
const PALE = ["#bcdcff", "#ffc4bd"];
const ABILITY_COLOR = { root: "#c9c9d6", boomerang: "#fac850", hook: "#dfe3ee" };

const rand = (a, b) => a + Math.random() * (b - a);

export class Effects {
  constructor() {
    this.particles = [];
    this.rings = [];
    this.texts = [];
    this.shake = 0;
    this.prev = null;
    this.trailClock = 0;
  }

  // ---- spawning --------------------------------------------------------------

  burst(x, y, n, color, { speed = [60, 220], life = [0.3, 0.7], size = [2, 4], drag = 3, glow = true } = {}) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const v = rand(...speed);
      const l = rand(...life);
      this.particles.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: l, max: l, size: rand(...size), color, drag, glow });
    }
    if (this.particles.length > MAX_PARTICLES) this.particles.splice(0, this.particles.length - MAX_PARTICLES);
  }

  ring(x, y, from, to, color, life = 0.45, width = 3) {
    this.rings.push({ x, y, from, to, color, life, max: life, width });
  }

  text(x, y, text, color) {
    this.texts.push({ x, y, text, color, life: 0.9, max: 0.9 });
  }

  // ---- events from snapshot differences --------------------------------------

  observe(snap) {
    const prev = this.prev;
    this.prev = snap;
    if (!prev || snap.tick <= prev.tick) return;  // same frame, or a new match

    snap.champions.forEach((c, i) => {
      const p = prev.champions[i];
      if (c.hp < p.hp) {  // took a hit
        this.burst(c.x, c.y, 26, PLAYER[1 - i], { speed: [80, 260] });
        this.burst(c.x, c.y, 10, "#ffffff", { speed: [40, 140], life: [0.15, 0.35] });
        this.text(c.x, c.y - 66, `−${p.hp - c.hp}`, "#ff6b6b");
        this.shake = Math.max(this.shake, 7);
      } else if (c.hp > p.hp) {  // healed
        this.burst(c.x, c.y, 18, "#6edc82", { speed: [20, 90], life: [0.5, 1.0] });
        this.text(c.x, c.y - 66, `+${c.hp - p.hp}`, "#7ff09a");
      }
      if (c.forced && !p.forced) {  // dash or pull starts: kick up dust behind
        for (let k = 0; k < 10; k++) {
          const l = rand(0.25, 0.5);
          this.particles.push({ x: c.x + rand(-10, 10), y: c.y + rand(-10, 10), vx: -c.vx * rand(3, 8) + rand(-30, 30),
            vy: -c.vy * rand(3, 8) + rand(-30, 30), life: l, max: l, size: rand(2, 5), color: "#8a90a0", drag: 5, glow: false });
        }
      }
      if (p.shielded && !c.shielded && c.hp === p.hp) this.ring(c.x, c.y, 34, 70, "#78e6ff", 0.4, 4);  // blocked (or faded)
    });

    const alive = new Set(snap.projectiles.map((p) => p.id));
    for (const p of prev.projectiles) {
      if (!alive.has(p.id)) this.burst(p.x, p.y, 10, ABILITY_COLOR[p.ability] || PALE[p.owner], { speed: [40, 150], life: [0.15, 0.4] });
    }

    const key = (pk) => `${pk.x.toFixed(1)},${pk.y.toFixed(1)},${pk.ability}`;
    const still = new Set(snap.pickups.map(key));
    for (const pk of prev.pickups) {
      if (!still.has(key(pk))) {
        this.burst(pk.x, pk.y, 22, "#fac850", { speed: [30, 160], life: [0.4, 0.8], size: [1.5, 3.5] });
        this.ring(pk.x, pk.y, 10, 46, "#fac850", 0.4, 2);
      }
    }

    if (prev.heal && snap.heal && prev.heal.up && !snap.heal.up) {
      this.burst(snap.heal.x, snap.heal.y, 30, "#6edc82", { speed: [40, 200], life: [0.4, 0.9] });
      this.ring(snap.heal.x, snap.heal.y, 20, 90, "#6edc82", 0.5, 3);
    }

    const zonesNow = new Set(snap.zones.map((z) => `${z.x.toFixed(1)},${z.y.toFixed(1)}`));
    for (const z of prev.zones) {
      if (!zonesNow.has(`${z.x.toFixed(1)},${z.y.toFixed(1)}`)) {  // detonated
        this.ring(z.x, z.y, z.r * 0.3, z.r * 1.15, PLAYER[z.owner], 0.45, 6);
        this.burst(z.x, z.y, 34, PALE[z.owner], { speed: [100, 340], life: [0.25, 0.6] });
        this.shake = Math.max(this.shake, 5);
      }
    }

    if (snap.walls.length > prev.walls.length) {
      for (const w of snap.walls.slice(prev.walls.length)) {
        for (let k = 0; k <= 8; k++) {
          const t = k / 8;
          this.burst(w.ax + (w.bx - w.ax) * t, w.ay + (w.by - w.ay) * t, 2, "#c8cddc", { speed: [10, 60], life: [0.3, 0.6], glow: false });
        }
      }
    }
  }

  // ---- simulation and drawing --------------------------------------------------

  update(dt, snap) {
    // Spark trails behind moving projectiles, a few per projectile per frame.
    this.trailClock += dt;
    if (snap && this.trailClock > 1 / 45) {
      this.trailClock = 0;
      for (const p of snap.projectiles) {
        const l = rand(0.15, 0.35);
        this.particles.push({ x: p.x - p.dx * rand(0, 12) + rand(-3, 3), y: p.y - p.dy * rand(0, 12) + rand(-3, 3),
          vx: -p.dx * rand(10, 60) + rand(-15, 15), vy: -p.dy * rand(10, 60) + rand(-15, 15),
          life: l, max: l, size: rand(1.5, Math.min(4, Math.max(2, p.r * 0.18))), color: ABILITY_COLOR[p.ability] || PALE[p.owner], drag: 2, glow: true });
      }
    }
    for (const p of this.particles) {
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      const k = Math.max(0, 1 - p.drag * dt);
      p.vx *= k;
      p.vy *= k;
      p.life -= dt;
    }
    this.particles = this.particles.filter((p) => p.life > 0);
    for (const r of this.rings) r.life -= dt;
    this.rings = this.rings.filter((r) => r.life > 0);
    for (const t of this.texts) { t.life -= dt; t.y -= 38 * dt; }
    this.texts = this.texts.filter((t) => t.life > 0);
    this.shake *= Math.pow(0.0005, dt);  // fast decay
    if (this.shake < 0.3) this.shake = 0;
  }

  shakeOffset() {
    return this.shake ? [rand(-1, 1) * this.shake, rand(-1, 1) * this.shake] : [0, 0];
  }

  draw(g, sy) {
    g.save();
    for (const r of this.rings) {
      const t = 1 - r.life / r.max;
      g.globalAlpha = (1 - t) * 0.9;
      g.strokeStyle = r.color;
      g.lineWidth = r.width * (1 - t * 0.6);
      g.beginPath();
      g.arc(r.x, sy(r.y), r.from + (r.to - r.from) * t, 0, Math.PI * 2);
      g.stroke();
    }
    for (const glow of [false, true]) {
      g.globalCompositeOperation = glow ? "lighter" : "source-over";
      for (const p of this.particles) {
        if (p.glow !== glow) continue;
        const a = p.life / p.max;
        g.globalAlpha = a;
        g.fillStyle = p.color;
        g.beginPath();
        g.arc(p.x, sy(p.y), Math.max(0.5, p.size * (0.4 + 0.6 * a)), 0, Math.PI * 2);
        g.fill();
      }
    }
    g.globalCompositeOperation = "source-over";
    g.font = "800 22px system-ui, sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    for (const t of this.texts) {
      g.globalAlpha = Math.min(1, (t.life / t.max) * 1.6);
      g.lineWidth = 4;
      g.strokeStyle = "rgba(0,0,0,0.6)";
      g.strokeText(t.text, t.x, sy(t.y));
      g.fillStyle = t.color;
      g.fillText(t.text, t.x, sy(t.y));
    }
    g.restore();
  }
}
