// Human-readable names for rule-language sensors and actions, shared by the
// block editor and the in-game decision overlay.

export const pretty = (s) => s.replaceAll("_", " ");

export const SENSOR_TEXT = {
  enemy_distance: "enemy distance", threat_time: "seconds until a hit", my_hp: "my HP", enemy_hp: "enemy HP",
  time_left: "seconds left", pickup_distance: "pickup distance", threatened: "a shot is coming at me",
  can_sidestep: "I can sidestep it", ready: "ready:", in_range: "in range:", holding: "I'm holding",
  enemy_holding: "enemy is holding", closer_to_pickup: "I'm closer to a pickup", enemy_casting: "enemy is casting",
  enemy_rooted: "enemy is rooted", enemy_shielded: "enemy is shielded", enemy_dashing: "enemy is dashing",
  i_am_rooted: "I'm rooted", enemy_ready: "enemy's ready:", enemy_cooldown: "enemy's cooldown on",
  since_enemy_used: "seconds since enemy used", since_i_used: "seconds since I used",
  since_i_was_hit: "seconds since I got hit", since_i_hit_enemy: "seconds since I hit them",
  in_mode: "my mode is", time_in_mode: "seconds in this mode", chance: "with chance (%)",
  heal_up: "the heal is up", heal_in: "seconds until the heal", heal_distance: "distance to the heal",
  closer_to_heal: "I'm closer to the heal",
};

export const ACTION_TEXT = {
  approach: "approach the enemy", retreat: "retreat", strafe: "strafe", go_to_pickup: "go to the pickup",
  hold: "hold position", wander: "wander", shoot: "shoot Bolt, aim", dash: "dash", use_item: "use item, aim",
  hold_fire: "hold fire", set_mode: "switch to mode", go_to_heal: "go to the heal",
};

// Compact versions for labels floating over champions.
export const ACTION_SHORT = {
  approach: "approach", retreat: "retreat", strafe: "strafe", go_to_pickup: "→ pickup", hold: "hold",
  wander: "wander", shoot: "shoot", dash: "dash", use_item: "use item", hold_fire: "hold fire",
  set_mode: "mode", go_to_heal: "→ heal",
};

export const actionShort = (name) => ACTION_SHORT[name] || pretty(name);

/** One condition as a short phrase, matching how the editor's blocks read. */
export function describeCondition(cond) {
  const neg = "not" in cond;
  const c = neg ? cond.not : cond;
  if (c.sensor === "chance") return `${neg ? "unless" : "if"} ${c.value}% chance`;
  const params = Object.entries(c).filter(([k]) => !["sensor", "op", "value"].includes(k)).map(([, v]) => pretty(v));
  const compare = c.op ? ` ${c.op} ${c.value}` : "";
  return `${neg ? "unless" : "if"} ${SENSOR_TEXT[c.sensor] || pretty(c.sensor)}${params.length ? " " + params.join(" ") : ""}${compare}`;
}

/** An action with its parameters, e.g. "dash away from threat". */
export function describeAction(act) {
  const params = Object.entries(act).filter(([k]) => k !== "action").map(([, v]) => pretty(v));
  return [ACTION_TEXT[act.action] || pretty(act.action), ...params].join(" ");
}

// Opponent cards in the Play lobby: a one-line style and a strength (win % against the
// other bots). Keyed like the bot dropdowns. Refresh the numbers when a bot changes.
// Source: 200-game round robin at normal difficulty, commit 6230cd2 (2026-10-08).
export const BOT_INFO = {
  "builtin:idle": { blurb: "Target practice: never moves or shoots", win: 0 },
  "builtin:random": { blurb: "Warm-up: wanders and fires at random", win: 0.3 },
  "builtin:aimer": { blurb: "Stands still and shoots straight at you", win: 11.4 },
  "builtin:leader": { blurb: "Aims where you're going, not where you are", win: 9.9 },
  "starter:leader": { blurb: "leader, built from rule blocks", win: 10.2 },
  "builtin:dodger": { blurb: "Sidesteps your shots and leads its own", win: 50.6 },
  "starter:dodger": { blurb: "dodger, built from rule blocks", win: 50.4 },
  "starter:baiter": { blurb: "Baits out your dash, then punishes it", win: 67.2 },
  "builtin:ppo_v2": { blurb: "Trained bot (learned under older rules)", win: 71.1 },
  "builtin:ppo_v1": { blurb: "Trained bot, Bolt only (older rules)", win: 73.4 },
  "builtin:ppo_v3": { blurb: "Trained on the current rules: the strongest", win: 95.1 },
};

/** Bot options ({value, label}) easiest first, by BOT_INFO strength; unknown (new) bots last. */
export function byStrength(opts) {
  const strength = (o) => BOT_INFO[o.value]?.win ?? Infinity;
  return [...opts].sort((a, b) => strength(a) - strength(b) || a.label.localeCompare(b.label));
}

/** A bot option's kind, for small tags: "rules", "trained", "yours", or "" (a built-in script). */
export function botKind(value, trainedBots) {
  const [kind, name] = value.split(":");
  if (kind === "starter") return "rules";
  if (kind === "upload") return "yours";
  return trainedBots.includes(name) ? "trained" : "";
}

/** What a difficulty does to bots (it never changes game speed), from the config's presets. */
export function difficultyText(info, name) {
  const d = info.difficulty_presets[name];
  if (!d) return "";
  const ms = Math.round((1000 * d.reaction_delay) / info.tick_rate);
  const perSec = Math.round(info.tick_rate / d.rate_limit);
  return `bots react in ${ms} ms · decide ${perSec}×/s · aim ±${d.aim_noise_deg}°`;
}

/** Give a difficulty chip group tooltips and keep `note` describing the chosen level. */
export function explainDifficulty(chips, note, info) {
  const update = () => {
    for (const b of chips.children) b.title = difficultyText(info, b.dataset.value || b.textContent);
    const on = [...chips.children].find((b) => b.getAttribute("aria-pressed") === "true");
    note.textContent = on ? difficultyText(info, on.dataset.value || on.textContent) : "";
  };
  new MutationObserver(update).observe(chips, { subtree: true, childList: true, attributes: true, attributeFilter: ["aria-pressed"] });
  update();
}
