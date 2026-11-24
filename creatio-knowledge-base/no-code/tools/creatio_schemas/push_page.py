"""One Freedom UI page of a package to the site over clio's `update-page`, then `verify` of that schema (S44-T03).

    push_page(package, "UsrOrder_FormPage", env, clio, verify_fn)  -> (lines, exit code)

The case it serves: a one-page change in a package whose `push-pkg` would also install its data bindings (and overwrite
force-update values the site holds otherwise). `update-page` saves the body through the designer service into the
package that holds the page in the working copy (`--target-package-uid`, never the site's design package by default),
in replace mode, against the checksum `get-page` reads just before (another session's save in between is a conflict,
not an overwrite). A dry run runs the same `update-page` with `--dry-run` and stops there.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .page.fold import is_freedom


def _json_of(output: str) -> dict:
    """The first JSON object clio printed (its lines start with `[INF] - `)."""
    at = output.find("{")
    if at < 0:
        raise RuntimeError(f"clio printed no JSON: {output.strip()[-300:]}")
    return json.JSONDecoder().raw_decode(output[at:])[0]


def push_page(package: Path, page: str, env: str, clio, verify_fn, dry_run: bool = False, force: bool = False) -> tuple[list[str], int]:
    """(answer lines, exit code). `verify_fn(package, [page])` -> [(schema, status)]; `force` overwrites a newer site copy."""
    package = Path(package)
    folder = package / "Schemas" / page
    body = folder / f"{page}.js"
    if not body.is_file():
        raise FileNotFoundError(f"{body} not found: push.py page takes a page schema of this package")
    if not is_freedom(folder, page):
        raise ValueError(f"{page} is not a Freedom UI page (no SCHEMA_VIEW_CONFIG_DIFF marker): update-page writes Freedom UI pages only")
    package_uid = json.loads((package / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["UId"]
    lines = []
    with tempfile.TemporaryDirectory() as scratch:  # get-page writes .clio-pages/ into its working folder
        info = _json_of(clio.run(["get-page", "--schema-name", page, "-e", env], cwd=Path(scratch)))
    if not info.get("success"):
        raise RuntimeError(f"get-page: {info.get('error') or info}")
    checksum = (info.get("editable") or {}).get("checksum") or ""
    leaf = (info.get("page") or {}).get("currentLeafPackageName") or "?"
    if leaf != package.name:
        lines.append(f"note: the site's top copy of {page} is in {leaf}; the save goes to {package.name}'s copy, which {leaf}'s may override")
    design = str((info.get("page") or {}).get("designPackageUId") or "").lower()
    other_layer = bool(design) and design != str(package_uid).lower()
    if other_layer:
        # get-page read the default design package's layer, and clio refuses a replace into another package without --force
        # (package-choice-replace-refused, seen on the test site): the working copy IS this package's own layer, so the
        # replace is meant; the checksum of the other layer would protect nothing
        lines.append(f"note: {package.name} is not the page's default design package on the site: saved with --force into its own layer")
    args = ["update-page", "--schema-name", page, "--body-file", str(body.resolve()), "--mode", "replace",
            "--target-package-uid", package_uid, "-e", env]
    args += ["--force"] if force or other_layer else (["--expected-checksum", checksum] if checksum else [])
    if dry_run:
        args.append("--dry-run")
    try:
        answer = _json_of(clio.run(args))
    except RuntimeError as e:  # clio exits 1 on a refused save and prints the JSON with the reason
        text = str(e)
        answer = _json_of(text) if "{" in text else {"success": False, "error": text}
    if not answer.get("success"):
        error = str(answer.get("error") or "")
        if answer.get("conflict"):
            why = "conflict: the site's copy changed since get-page (re-read the page, or --force)"
        elif "third-party publisher" in error or "file archive" in error:
            # seen on the test site (S44-T03): a package pushed from files, or one whose maintainer is not the site's, is
            # read-only to the designer service - update-page cannot write into it, only push-pkg can
            why = (f"the site does not let the designer edit {package.name} (installed from an archive or another maintainer "
                   f"than the site's Maintainer setting): push the package (push.py {package.name} -e {env}), or save into an "
                   f"editable package with clio update-page --mode append")
        else:
            why = error or answer
        return lines + [f"update-page: FAILED {why}"], 1
    lines.append(f"update-page: {'dry run ok' if dry_run else 'saved'} ({package.name}, replace"
                 + (f", checksum {answer['newChecksum']}" if answer.get("newChecksum") else "") + ")")
    lines += [f"  warning: {w}" for w in answer.get("warnings") or []]
    if dry_run:
        return lines, 0
    results = verify_fn(package, [page])
    lines += [f"verify: {name} {status}" for name, status in results]
    return lines, 0 if all(status.startswith("same") for _, status in results) else 1
