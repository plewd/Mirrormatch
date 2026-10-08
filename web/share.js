// Share links: a bot or a replay packed into the page's URL fragment, so sharing needs no
// server. Data = JSON, deflate-compressed with the browser's CompressionStream, base64url.
// The fragment never reaches a server. Decoded data is untrusted: callers validate it.

const MAX_BYTES = 1 << 20;  // refuse anything that inflates past 1 MB

function toBase64Url(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64Url(text) {
  const b64 = text.replaceAll("-", "+").replaceAll("_", "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

/** Text -> compact URL-safe string. */
export async function pack(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("deflate"));
  return toBase64Url(new Uint8Array(await new Response(stream).arrayBuffer()));
}

/** The reverse of pack(); throws on anything malformed or too large. */
export async function unpack(data) {
  const stream = new Blob([fromBase64Url(data)]).stream().pipeThrough(new DecompressionStream("deflate"));
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > MAX_BYTES) { reader.cancel(); throw new Error("shared data is too large"); }
    chunks.push(value);
  }
  return new TextDecoder().decode(await new Blob(chunks).arrayBuffer());
}

/** A link to this page carrying `kind` ("bot" or "replay") and its packed text. */
export async function shareLink(kind, text) {
  return `${location.origin}${location.pathname}#${kind}=${await pack(text)}`;
}

/** What the page was opened with: {kind, data} from "#bot=..." / "#replay=...", or null. */
export function sharedFromUrl() {
  const m = /^#(bot|replay)=([\w-]+)$/.exec(location.hash);
  return m ? { kind: m[1], data: m[2] } : null;
}

/** A short message at the bottom of the page. With `link`, it shows the link to copy by hand. */
export function toast(message, link = null) {
  const el = document.getElementById("toast");
  el.replaceChildren(document.createTextNode(message));
  if (link) {
    const input = document.createElement("input");
    input.readOnly = true;
    input.value = link;
    el.append(input);
    setTimeout(() => input.select(), 0);
  }
  el.hidden = false;
  clearTimeout(el.timer);
  el.timer = setTimeout(() => { el.hidden = true; }, link ? 15000 : 3500);
}

/** Copy a link for `kind`, telling the user how it went. */
export async function copyShareLink(kind, text, what) {
  const link = await shareLink(kind, text);
  try {
    await navigator.clipboard.writeText(link);
    toast(`Link to ${what} copied. Anyone who opens it can see it.`);
  } catch {
    toast(`Copy this link to share ${what}:`, link);
  }
  return link;
}
