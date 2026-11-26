"""A JavaScript check of a client schema body before push (S48-T16): `node --check`, then a load with a stub `define()`.

`lines(path)` gives the two lines `validate` of the Classic and Freedom toolkits prints:

    js syntax: ok                                  (or the first error lines; `node not found: JS syntax not checked`)
    js load: viewConfigDiff 12, handlers 2 (a, b), methods 5 (x, y)

The load calls the module's function with stub arguments and counts what it returns: an array by its length, an object by
its keys, `handlers` by its `request` names. A body that throws on load (code outside the methods that needs the platform) is
reported as `js load: not loaded (<error>)`, not as a failure.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

LOAD = r"""
const vm = require('vm'), fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8').replace(/^\uFEFF/, '');
const stub = new Proxy(function () {}, {get: (t, k) => (k === Symbol.toPrimitive ? () => '' : stub), apply: () => stub, construct: () => stub});
let module_ = null;
try {
  vm.runInNewContext(src, {define: (name, deps, fn) => { module_ = fn; }, Terrasoft: stub, Ext: stub, Creatio: stub});
  const result = module_.apply(null, Array(module_.length).fill(stub));
  const out = {};
  for (const [k, v] of Object.entries(result || {})) {
    if (Array.isArray(v)) out[k] = [v.length, k === 'handlers' ? v.map(h => h && h.request) : []];
    else if (v && typeof v === 'object') out[k] = [Object.keys(v).length, Object.keys(v)];
  }
  console.log(JSON.stringify(out));
} catch (e) { console.log(JSON.stringify({error: String(e).split('\n')[0]})); }
"""


def lines(path: Path | str) -> list[str]:
    node = shutil.which("node")
    if not node:
        return ["node not found: JS syntax not checked"]
    path = str(path)
    syntax = subprocess.run([node, "--check", path], capture_output=True, text=True, encoding="utf-8", timeout=30)
    if syntax.returncode:
        return ["js syntax: ERROR " + " | ".join(l.strip() for l in syntax.stderr.splitlines() if l.strip())[:300]]
    run = subprocess.run([node, "-e", LOAD, path], capture_output=True, text=True, encoding="utf-8", timeout=30)
    try:
        found = json.loads(run.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return ["js syntax: ok", f"js load: not loaded ({run.stderr.strip()[:120] or 'no answer'})"]
    if "error" in found:
        return ["js syntax: ok", f"js load: not loaded ({found['error'][:120]})"]
    parts = [f"{k} {n}" + (f" ({', '.join(str(x) for x in names[:8])}{', ...' if len(names) > 8 else ''})" if names else "")
             for k, (n, names) in found.items()]
    return ["js syntax: ok", "js load: " + (", ".join(parts) or "nothing returned")]
