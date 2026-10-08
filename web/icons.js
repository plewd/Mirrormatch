// Small vector icons for pickups and the heal, drawn with canvas paths so they
// scale crisply anywhere (map, HUD). `s` is the half-size in pixels.

export function drawIcon(g, name, x, y, s, color) {
  g.save();
  g.strokeStyle = color;
  g.fillStyle = color;
  g.lineWidth = Math.max(1.5, s * 0.22);
  g.lineCap = "round";
  g.lineJoin = "round";
  g.beginPath();
  switch (name) {
    case "boomerang":
      g.moveTo(x - 0.75 * s, y + 0.4 * s);
      g.quadraticCurveTo(x, y - 1.0 * s, x + 0.75 * s, y + 0.4 * s);
      g.stroke();
      break;
    case "shield":
      g.moveTo(x, y - 0.8 * s);
      g.lineTo(x + 0.65 * s, y - 0.5 * s);
      g.lineTo(x + 0.6 * s, y + 0.1 * s);
      g.quadraticCurveTo(x + 0.45 * s, y + 0.6 * s, x, y + 0.85 * s);
      g.quadraticCurveTo(x - 0.45 * s, y + 0.6 * s, x - 0.6 * s, y + 0.1 * s);
      g.lineTo(x - 0.65 * s, y - 0.5 * s);
      g.closePath();
      g.stroke();
      break;
    case "root":
      g.arc(x, y, 0.38 * s, 0, Math.PI * 2);
      for (let k = 0; k < 6; k++) {
        const a = (k * Math.PI) / 3 + Math.PI / 6;
        g.moveTo(x + Math.cos(a) * 0.38 * s, y + Math.sin(a) * 0.38 * s);
        g.lineTo(x + Math.cos(a) * 0.85 * s, y + Math.sin(a) * 0.85 * s);
      }
      g.stroke();
      break;
    case "wall":
      g.rect(x - 0.7 * s, y - 0.55 * s, 1.4 * s, 1.1 * s);
      g.moveTo(x - 0.7 * s, y);
      g.lineTo(x + 0.7 * s, y);
      g.moveTo(x - 0.1 * s, y - 0.55 * s);
      g.lineTo(x - 0.1 * s, y);
      g.moveTo(x + 0.25 * s, y);
      g.lineTo(x + 0.25 * s, y + 0.55 * s);
      g.stroke();
      break;
    case "hook":
      g.moveTo(x + 0.25 * s, y - 0.85 * s);
      g.lineTo(x + 0.25 * s, y + 0.2 * s);
      g.arc(x - 0.12 * s, y + 0.2 * s, 0.37 * s, 0, Math.PI);
      g.lineTo(x - 0.49 * s, y - 0.1 * s);
      g.stroke();
      break;
    case "blast":
      for (let k = 0; k < 8; k++) {
        const a = (k * Math.PI) / 4;
        const inner = k % 2 ? 0.3 : 0.25;
        const outer = k % 2 ? 0.6 : 0.9;
        g.moveTo(x + Math.cos(a) * inner * s, y + Math.sin(a) * inner * s);
        g.lineTo(x + Math.cos(a) * outer * s, y + Math.sin(a) * outer * s);
      }
      g.stroke();
      g.beginPath();
      g.arc(x, y, 0.18 * s, 0, Math.PI * 2);
      g.fill();
      break;
    case "heal":
      g.lineWidth = Math.max(2, s * 0.32);
      g.moveTo(x - 0.55 * s, y);
      g.lineTo(x + 0.55 * s, y);
      g.moveTo(x, y - 0.55 * s);
      g.lineTo(x, y + 0.55 * s);
      g.stroke();
      break;
    default:  // unknown ability: its first letter
      g.font = `bold ${Math.round(s * 1.3)}px system-ui, sans-serif`;
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.fillText(name[0].toUpperCase(), x, y + 1);
  }
  g.restore();
}
