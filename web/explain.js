// Build's "What your bot does" panel: the rules in plain English, grouped the way the bot
// decides (first matching rule per channel), plus warnings from `rules.analyze` (Python).
import { describeAction, describeCondition } from "./labels.js";

const CHANNELS = [["move", "Moving"], ["ability", "Abilities"], ["mode", "Modes"]];

function sentence(rule) {
  const conds = (rule.if || []).map(describeCondition);
  const action = describeAction(rule.then);
  if (!conds.length) return `Always: ${action}.`;
  const when = conds.join(" and ");
  return `${when[0].toUpperCase()}${when.slice(1)}: ${action}.`;
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

/** Fill the panel for `spec` from `report` ({groups, warnings} or {error}). */
export function renderExplain(body, count, spec, report) {
  if (report.error) {
    count.textContent = "";
    body.replaceChildren(el("p", "hint", "Fix the problems above first, then this explains your bot."));
    return;
  }
  const dead = new Set(report.warnings.flatMap((w) => (w.kind === "contradiction" || w.kind === "shadowed" ? w.rules : [])));
  const n = report.warnings.length;
  count.textContent = n ? `· ${n} warning${n > 1 ? "s" : ""}` : "";
  count.classList.toggle("bad", n > 0);

  const parts = [];
  if (n) {
    const list = el("ul", "explain-warnings");
    for (const w of report.warnings) list.append(el("li", "", w.message));
    parts.push(list);
  }
  parts.push(el("p", "hint", "Each decision, the bot runs the first rule that matches in each group below."));
  for (const [key, title] of CHANNELS) {
    const numbers = report.groups[key];
    if (!numbers.length) continue;
    parts.push(el("h4", `explain-head ${key}`, title));
    const list = el("ol", "explain-rules");
    for (const i of numbers) {
      const item = el("li", dead.has(i) ? "dead" : "");
      item.append(el("span", "explain-num", `${i}`), el("span", "", sentence(spec.rules[i - 1])));
      if (dead.has(i)) item.title = "This rule can never run (see the warnings above).";
      list.append(item);
    }
    parts.push(list);
  }
  body.replaceChildren(...parts);
}
