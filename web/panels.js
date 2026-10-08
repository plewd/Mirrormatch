// Build tab side panels: the block toolbox (left) and the preview/test sidebar (right) can each
// be pinned open or collapsed to a slim edge tab. Unpinned, a panel opens from its tab and
// closes by itself: the toolbox after you drop a block, the sidebar (an overlay) on a click
// outside it. Pins are remembered.

const $ = (id) => document.getElementById(id);
const STORE_KEY = "mirrormatch.build.pins";

// A minimal line-drawn thumbtack; CSS tilts and dims it when unpinned.
const PIN_SVG = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3.5h6l-1 5.5 3 3H7l3-3z"/><path d="M12 12v8.5"/></svg>`;

export function setupBuildPanels(ws, Blockly) {
  const state = { blocksPinned: true, sidePinned: true, blocksOpen: false, sideOpen: false };
  try { Object.assign(state, JSON.parse(localStorage.getItem(STORE_KEY) || "{}"), { blocksOpen: false, sideOpen: false }); } catch { /* defaults */ }
  const save = () => {
    try { localStorage.setItem(STORE_KEY, JSON.stringify({ blocksPinned: state.blocksPinned, sidePinned: state.sidePinned })); } catch { /* this visit only */ }
  };

  const toolbox = ws.getToolbox();
  const blocksPin = document.createElement("button");
  blocksPin.type = "button";
  blocksPin.className = "pin toolbox-pin";
  toolbox.HtmlDiv.append(blocksPin);
  const sidePin = $("ed-side-pin");
  for (const b of [blocksPin, sidePin]) b.innerHTML = PIN_SVG;

  const builder = $("builder");
  const apply = () => {
    toolbox.setVisible(state.blocksPinned || state.blocksOpen);
    $("ed-blocks-tab").hidden = state.blocksPinned || state.blocksOpen;
    builder.classList.toggle("side-floating", !state.sidePinned);
    builder.classList.toggle("side-open", !state.sidePinned && state.sideOpen);
    $("ed-side-tab").hidden = state.sidePinned;
    for (const [btn, on, what] of [[blocksPin, state.blocksPinned, "blocks"], [sidePin, state.sidePinned, "panel"]]) {
      btn.setAttribute("aria-pressed", String(on));
      btn.title = on ? `Unpin: hide the ${what} when not in use` : `Pin: keep the ${what} open`;
    }
    requestAnimationFrame(() => Blockly.svgResize(ws));
  };
  const closeBlocks = () => { if (!state.blocksPinned && state.blocksOpen) { state.blocksOpen = false; apply(); } };
  const closeSide = () => { if (!state.sidePinned && state.sideOpen) { state.sideOpen = false; apply(); } };

  $("ed-blocks-tab").addEventListener("click", () => { state.blocksOpen = true; apply(); });
  blocksPin.addEventListener("click", () => { state.blocksPinned = !state.blocksPinned; state.blocksOpen = !state.blocksPinned; save(); apply(); });
  $("ed-side-tab").addEventListener("click", () => { state.sideOpen = !state.sideOpen; apply(); });
  sidePin.addEventListener("click", () => { state.sidePinned = !state.sidePinned; state.sideOpen = false; save(); apply(); });

  // Unpinned toolbox: done once a block has been dropped, or on a click on empty workspace.
  ws.addChangeListener((e) => {
    if (e.type === Blockly.Events.BLOCK_DRAG && !e.isStart) closeBlocks();
    if (e.type === Blockly.Events.CLICK && e.targetType === "workspace") closeBlocks();
  });
  // Unpinned sidebar: an overlay that closes on a click anywhere outside it (or Esc).
  document.addEventListener("pointerdown", (e) => {
    if (!$("ed-side").contains(e.target) && !$("ed-side-tab").contains(e.target)) closeSide();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeSide(); closeBlocks(); } });
  apply();
}
