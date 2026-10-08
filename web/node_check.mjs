// Headless check: boot the vendored Pyodide in Node, load the bundled sim, and
// print the final-state digest of a scripted game (compared against CPython by
// tests/test_web.py).
import { loadPyodide } from "./vendor/pyodide/pyodide.mjs";
import { readFile } from "node:fs/promises";

const here = new URL(".", import.meta.url);
const pyodide = await loadPyodide({ indexURL: new URL("vendor/pyodide/", here).pathname });
await pyodide.loadPackage(new URL("vendor/pyodide/numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl", here).pathname);
const bundle = await readFile(new URL("build/arena.zip", here));
pyodide.unpackArchive(new Uint8Array(bundle), "zip", { extractDir: "/home/pyodide" });
const script = process.argv[2];
const out = await pyodide.runPythonAsync(await readFile(script, "utf8"));
console.log(out);
