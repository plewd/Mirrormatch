"""Smoke-test the browser build in real headless Chrome (no extra dependencies).

    python tools/browser_check.py "http://127.0.0.1:8000/?auto=watch" out.png [--wait-tick 200] [--js "..."]

Opens the page, waits until `window.__mirrormatch.tick` reaches --wait-tick (or the
page reports an error), optionally runs some JavaScript, then saves a screenshot
and prints the page status and console errors. Talks to Chrome's DevTools
protocol over a minimal standard-library WebSocket client.
"""

import argparse
import base64
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class WebSocket:
    def __init__(self, url: str, timeout: float = 30) -> None:
        assert url.startswith("ws://")
        host_port, path = url[5:].split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.sock.recv(4096)
        if b" 101 " not in resp.split(b"\r\n")[0]:
            raise RuntimeError(f"websocket handshake failed: {resp[:200]!r}")
        self.buf = resp.split(b"\r\n\r\n", 1)[1]

    def send(self, text: str) -> None:
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        header = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                  bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                  bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self) -> str:
        message = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            message += self._read(n)
            if b0 & 0x80:
                return message.decode()


class Page:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.next_id = 0
        self.console_errors: list[str] = []

    def call(self, method: str, **params):
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                self.console_errors.append(msg["params"]["exceptionDetails"].get("text", "exception"))
            elif msg.get("method") == "Runtime.consoleAPICalled" and msg["params"]["type"] == "error":
                self.console_errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"]))
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def eval(self, expr: str):
        res = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return res["result"].get("value")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--wait-tick", type=int, default=150)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--js", default=None, help="JavaScript to run after the wait, before the screenshot")
    ap.add_argument("--after-js-wait", type=float, default=1.0)
    ap.add_argument("--size", default="1280,1000", help="window size as W,H")
    args = ap.parse_args()

    port = 9333
    profile = tempfile.mkdtemp(prefix="mm-chrome-")
    chrome = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={port}", f"--user-data-dir={profile}", f"--window-size={args.size}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1))
                break
            except OSError:
                time.sleep(0.2)
        tab = next(t for t in tabs if t["type"] == "page")
        page = Page(WebSocket(tab["webSocketDebuggerUrl"], timeout=max(30, args.timeout)))
        page.call("Runtime.enable")
        page.call("Page.enable")
        width, height = (int(v) for v in args.size.split(","))
        page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        page.call("Page.navigate", url=args.url)
        start = time.time()
        state = None
        while time.time() - start < args.timeout:
            state = page.eval("JSON.stringify({s: window.__mirrormatch || null, status: document.getElementById('status')?.textContent})")
            parsed = json.loads(state)
            if (parsed["s"] and parsed["s"]["ready"] and parsed["s"]["tick"] >= args.wait_tick) or "Failed" in (parsed["status"] or ""):
                break
            time.sleep(0.5)
        if args.js:
            print("js ->", page.eval(args.js))
            time.sleep(args.after_js_wait)
            state = page.eval("JSON.stringify({s: window.__mirrormatch || null, status: document.getElementById('status')?.textContent})")
        shot = page.call("Page.captureScreenshot", format="png")
        pathlib.Path(args.out).write_bytes(base64.b64decode(shot["data"]))
        print(f"after {time.time() - start:.1f}s: {state}")
        if page.console_errors:
            print("console errors:", *page.console_errors[:10], sep="\n  ")
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
    final = json.loads(state)["s"] if state else None
    sys.exit(0 if final and final["ready"] and final["tick"] >= args.wait_tick and not page.console_errors else 1)


if __name__ == "__main__":
    main()
