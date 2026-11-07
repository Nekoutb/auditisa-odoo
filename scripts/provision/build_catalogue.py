#!/usr/bin/env python3
"""Writes the add-on catalogue of a release, from the manifests of that release. Stdlib only.

    build_catalogue.py ADDONS_DIR RELEASE_SHA > CATALOGUE.json

build_release.sh runs it on the exported commit and signs the result, so the control plane learns
what a release carries from a file made beside the signature, not from anything it could edit.
An add-on is optional when its manifest says "ea_client_addon": True; everything else is a base
feature, always on. ea_platform_admin/services/addons.py reads the same way: a test keeps them equal.
"""

import ast
import json
import pathlib
import sys

MARKER = "ea_client_addon"
SAMPLE_MARKER = "ea_client_addon_sample"


def scan(folder):
    entries = []
    for manifest in sorted(pathlib.Path(folder).glob("*/__manifest__.py")):
        code = manifest.parent.name
        if code.startswith("ea_platform_") or not (manifest.parent / "__init__.py").is_file():
            continue
        data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        if not data.get("installable", True):
            continue
        entries.append({
            "code": code,
            "name": str(data.get("name") or code),
            "summary": str(data.get("summary") or ""),
            "version": str(data.get("version") or ""),
            "optional": data.get(MARKER) is True,
            "sample": data.get(SAMPLE_MARKER) is True,
        })
    return entries


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    document = {"schema": 1, "release": argv[2], "addons": scan(argv[1])}
    sys.stdout.write(json.dumps(document, ensure_ascii=True, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv)
