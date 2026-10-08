// Synthesized sound effects (Web Audio, no files). Triggered by the engine's event
// log in each snapshot, plus a few snapshot differences (a blast going off, the heal
// appearing, the match ending). Purely cosmetic, like the particle effects.

const MIN_GAP = 0.04;  // seconds between two plays of the same sound
const MAX_PER_FRAME = 8;  // fast-forward safety: never stack more than this at once

export class Sound {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.noiseBuf = null;
    this.volume = 0.6;
    this.muted = false;
    this.lastPlayed = {};
    this.played = 0;  // for tests
    this.prev = null;
  }

  /** Browsers only allow audio after a user gesture; call this from one. */
  unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
      this.applyVolume();
      const len = this.ctx.sampleRate;
      this.noiseBuf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const data = this.noiseBuf.getChannelData(0);
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
  }

  setVolume(v) { this.volume = v; this.applyVolume(); }
  setMuted(m) { this.muted = m; this.applyVolume(); }
  applyVolume() { if (this.master) this.master.gain.value = this.muted ? 0 : this.volume * 0.5; }

  // ---- building blocks -----------------------------------------------------------

  out(pan) {
    if (pan === undefined || !this.ctx.createStereoPanner) return this.master;
    const p = this.ctx.createStereoPanner();
    p.pan.value = Math.max(-1, Math.min(1, pan));
    p.connect(this.master);
    return p;
  }

  tone(freq, { type = "sine", dur = 0.15, to = null, gain = 0.2, delay = 0, attack = 0.005, pan } = {}) {
    const t = this.ctx.currentTime + delay;
    const o = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.out(pan));
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  noise({ dur = 0.15, filter = "lowpass", freq = 1000, to = null, gain = 0.3, delay = 0, pan } = {}) {
    const t = this.ctx.currentTime + delay;
    const src = this.ctx.createBufferSource();
    src.buffer = this.noiseBuf;
    const f = this.ctx.createBiquadFilter();
    f.type = filter;
    f.frequency.setValueAtTime(freq, t);
    if (to) f.frequency.exponentialRampToValueAtTime(to, t + dur);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(this.out(pan));
    src.start(t, Math.random() * 0.5);
    src.stop(t + dur + 0.02);
  }

  // ---- the sounds ------------------------------------------------------------------

  play(name, pan) {
    if (!this.ctx || this.muted) return;
    const now = this.ctx.currentTime;
    if (now - (this.lastPlayed[name] ?? -1) < MIN_GAP) return;
    this.lastPlayed[name] = now;
    this.played += 1;
    const o = { pan };
    switch (name) {
      case "cast_bolt":
        this.tone(700, { type: "square", to: 1300, dur: 0.09, gain: 0.12, ...o });
        this.tone(1400, { type: "triangle", dur: 0.06, gain: 0.08, delay: 0.02, ...o });
        break;
      case "cast_dash":
        this.noise({ filter: "bandpass", freq: 900, to: 2600, dur: 0.2, gain: 0.45, ...o });
        break;
      case "cast_boomerang":
        this.tone(520, { type: "triangle", to: 880, dur: 0.12, gain: 0.16, ...o });
        this.tone(880, { type: "triangle", to: 520, dur: 0.12, gain: 0.12, delay: 0.12, ...o });
        break;
      case "cast_shield":
        this.tone(880, { dur: 0.35, gain: 0.12, attack: 0.03, ...o });
        this.tone(1320, { dur: 0.32, gain: 0.08, attack: 0.03, delay: 0.03, ...o });
        break;
      case "cast_root":
        this.tone(180, { to: 110, dur: 0.4, gain: 0.25, ...o });
        this.tone(360, { type: "triangle", to: 240, dur: 0.18, gain: 0.08, ...o });
        break;
      case "cast_wall":
        this.tone(140, { type: "square", dur: 0.12, gain: 0.14, ...o });
        this.noise({ freq: 700, dur: 0.1, gain: 0.3, ...o });
        break;
      case "cast_hook":
        this.tone(1600, { type: "sawtooth", to: 380, dur: 0.18, gain: 0.08, ...o });
        break;
      case "cast_blast":
        this.tone(110, { to: 440, dur: 0.8, gain: 0.08, attack: 0.1, ...o });
        break;
      case "detonate":
        this.noise({ freq: 1000, to: 100, dur: 0.6, gain: 0.7, ...o });
        this.tone(75, { to: 38, dur: 0.5, gain: 0.45, ...o });
        break;
      case "hit_enemy":
        this.noise({ filter: "highpass", freq: 1400, dur: 0.07, gain: 0.35, ...o });
        this.tone(560, { to: 260, dur: 0.12, gain: 0.22, ...o });
        break;
      case "hit_me":
        this.noise({ freq: 800, dur: 0.16, gain: 0.55, ...o });
        this.tone(210, { to: 85, dur: 0.26, gain: 0.4, ...o });
        break;
      case "hit_soft":  // root or hook landing (no damage)
        this.tone(320, { type: "triangle", to: 150, dur: 0.2, gain: 0.2, ...o });
        break;
      case "blocked":
        this.tone(1760, { type: "triangle", dur: 0.28, gain: 0.15, ...o });
        this.tone(2640, { dur: 0.22, gain: 0.07, delay: 0.01, ...o });
        break;
      case "pickup":
        this.tone(660, { dur: 0.09, gain: 0.15, ...o });
        this.tone(990, { dur: 0.12, gain: 0.15, delay: 0.08, ...o });
        break;
      case "heal":
        [523, 659, 784].forEach((f, k) => this.tone(f, { dur: 0.16, gain: 0.14, delay: k * 0.09, ...o }));
        break;
      case "heal_up":
        this.tone(1046, { dur: 0.5, gain: 0.07, attack: 0.02 });
        this.tone(1568, { dur: 0.4, gain: 0.035, attack: 0.02, delay: 0.02 });
        break;
      case "win":
        [523, 659, 784, 1046].forEach((f, k) => this.tone(f, { type: "triangle", dur: 0.22, gain: 0.16, delay: k * 0.12 }));
        break;
      case "lose":
        [392, 330, 262].forEach((f, k) => this.tone(f, { type: "triangle", dur: 0.3, gain: 0.16, delay: k * 0.18 }));
        break;
      case "draw":
        [440, 440].forEach((f, k) => this.tone(f, { type: "triangle", dur: 0.2, gain: 0.14, delay: k * 0.2 }));
        break;
    }
  }

  // ---- from snapshots to sounds -------------------------------------------------------

  /** Play the sounds for whatever happened since the previous snapshot. */
  handle(snap, view, width = 1200) {
    const prev = this.prev;
    this.prev = snap;
    if (!this.ctx || this.muted || !prev || snap.tick <= prev.tick) return;
    const panAt = (x) => (x / width - 0.5) * 1.2;
    const champPan = (i) => panAt(snap.champions[i].x);
    let budget = MAX_PER_FRAME;
    const fire = (name, pan) => { if (budget-- > 0) this.play(name, pan); };

    for (const ev of snap.events || []) {
      const kind = ev[0];
      if (kind === "cast") fire(`cast_${ev[2]}`, champPan(ev[1]));
      else if (kind === "damage" && ev[4] > 0) fire(view.human && ev[2] === 0 ? "hit_me" : "hit_enemy", champPan(ev[2]));
      else if (kind === "hit" && (ev[3] === "root" || ev[3] === "hook")) fire("hit_soft", champPan(ev[2]));
      else if (kind === "blocked") fire("blocked", champPan(ev[1]));
      else if (kind === "pickup") fire("pickup", champPan(ev[1]));
      else if (kind === "heal") fire("heal", champPan(ev[1]));
    }
    const zonesNow = new Set(snap.zones.map((z) => `${z.x.toFixed(1)},${z.y.toFixed(1)}`));
    for (const z of prev.zones) if (!zonesNow.has(`${z.x.toFixed(1)},${z.y.toFixed(1)}`)) fire("detonate", panAt(z.x));
    if (prev.heal && snap.heal && !prev.heal.up && snap.heal.up) fire("heal_up");
    if (!prev.done && snap.done) {
      if (snap.winner === null) fire("draw");
      else if (view.human) fire(snap.winner === 0 ? "win" : "lose");
      else fire("win");
    }
  }

  /** Forget the previous snapshot (after a jump or a new match), so nothing replays. */
  reset() { this.prev = null; }
}
