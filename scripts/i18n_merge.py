#!/usr/bin/env python3
"""Rebuild an addon's fr.po from a fresh `odoo-bin i18n export`, keeping known translations.

    python scripts/i18n_merge.py EXPORT.po addons/ea_audit_tools/i18n/fr.po addons/ea_audit_tools/i18n/fr_glossary.json

The export gives the right references (model:, model_terms:, code:) for every current string.
A msgstr comes from the export, else the existing fr.po, else the glossary. The strings still
without French are printed, one per line, so nothing goes missing silently.
"""
import ast
import json
import re
import sys


def _unquote(line):
    return ast.literal_eval(line)


def parse(path):
    """[(comment lines, msgid, msgstr)], the header first."""
    entries, comments, msgid, msgstr, target = [], [], None, None, None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith("#"):
                if msgid is not None:
                    entries.append((comments, msgid, msgstr))
                    comments, msgid, msgstr, target = [], None, None, None
                comments.append(line)
            elif line.startswith("msgid "):
                if msgid is not None:
                    entries.append((comments, msgid, msgstr))
                    comments = []
                msgid, msgstr, target = _unquote(line[6:]), "", "id"
            elif line.startswith("msgstr "):
                msgstr, target = _unquote(line[7:]), "str"
            elif line.startswith('"'):
                if target == "id":
                    msgid += _unquote(line)
                else:
                    msgstr += _unquote(line)
    if msgid is not None:
        entries.append((comments, msgid, msgstr))
    return entries


def quote(text):
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    if "\n" not in escaped:
        return '"%s"' % escaped
    parts = re.split(r"(?<=\n)", escaped)
    return '""\n' + "\n".join('"%s"' % part.replace("\n", "\\n") for part in parts if part)


def main(export_path, po_path, glossary_path):
    known = {msgid: msgstr for _comments, msgid, msgstr in parse(po_path) if msgid and msgstr}
    with open(glossary_path, encoding="utf-8") as handle:
        glossary = json.load(handle)
    exported = parse(export_path)
    if len(exported) < 2:
        sys.exit("the export is empty: nothing written")
    out, missing = [], []
    for comments, msgid, msgstr in exported:
        if msgid:
            msgstr = msgstr if msgstr and msgstr != msgid else known.get(msgid) or glossary.get(msgid) or msgstr
            if not msgstr:
                missing.append(msgid)
        out.append("\n".join(comments + ["msgid " + quote(msgid), "msgstr " + quote(msgstr)]))
    with open(po_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(out) + "\n")
    print("%d entries, %d without French" % (len(out), len(missing)))
    for msgid in missing:
        print(json.dumps(msgid, ensure_ascii=False))


if __name__ == "__main__":
    main(*sys.argv[1:4])
