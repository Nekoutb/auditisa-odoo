"""Builds the user manual's index from its pages. Run it after every change to a page:

    python addons/ea_audit_ui/static/manual/tools/build_index.py

It writes, next to en/ and fr/:
- index.json: the parts and pages in contents order, the title of each page in both languages and
  the screens each page explains (read by the "? Help" button and the manual's contents);
- search-en.json and search-fr.json: the words of each page, loaded at the first search.
The pure test test_manual.py fails when index.json is not what this script would write.
"""
import hashlib
import json
import os
import sys

import manual_lib


def collect():
    """The pages of both languages, or the list of what is wrong with them."""
    pages, errors = {}, []
    for lang in manual_lib.LANGS:
        for path in manual_lib.page_files(lang):
            text = manual_lib.read(path)
            meta = manual_lib.page_meta(text)
            name = os.path.splitext(os.path.basename(path))[0]
            if meta["id"] != name:
                errors.append("%s/%s.html: data-id is %r, the file name %r" % (lang, name, meta["id"], name))
                continue
            if not (meta["title"] and meta["part"] and meta["order"] and meta["part_order"]):
                errors.append("%s/%s.html: needs an <h1>, data-part, data-part-order and data-order" % (lang, name))
                continue
            pages.setdefault(name, {})[lang] = dict(meta, text=manual_lib.plain(text))
    for name, langs in sorted(pages.items()):
        for lang in manual_lib.LANGS:
            if lang not in langs:
                errors.append("%s.html has no %s page" % (name, lang))
        if len(langs) == 2 and (langs["en"]["order"], langs["en"]["part_order"]) != (langs["fr"]["order"], langs["fr"]["part_order"]):
            errors.append("%s.html: the English and French pages sit in different places" % name)
    return pages, errors


def build():
    pages, errors = collect()
    if errors:
        return None, errors
    order = sorted(pages, key=lambda name: [int(n) for n in pages[name]["en"]["order"].split(".")])
    parts, seen = [], {}
    for name in order:
        en, fr = pages[name]["en"], pages[name]["fr"]
        key = en["part_order"]
        if key not in seen:
            seen[key] = (en["part"], fr["part"])
            parts.append({"key": key, "en": en["part"], "fr": fr["part"]})
        elif seen[key] != (en["part"], fr["part"]):
            errors.append("%s.html: part %s is named %r elsewhere" % (name, key, seen[key]))
    digest = hashlib.sha1()
    for name in order:
        for lang in manual_lib.LANGS:
            digest.update(manual_lib.read(os.path.join(manual_lib.MANUAL, lang, name + ".html")).encode("utf-8"))
    index = {
        "build": digest.hexdigest()[:12],
        "parts": parts,
        "pages": [
            {
                "id": name,
                "part": pages[name]["en"]["part_order"],
                "title": {lang: pages[name][lang]["title"] for lang in manual_lib.LANGS},
                "screens": pages[name]["en"]["screens"],
            }
            for name in order
        ],
    }
    search = {lang: {name: pages[name][lang]["text"] for name in order} for lang in manual_lib.LANGS}
    return (index, search), errors


def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def main():
    built, errors = build()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    index, search = built
    with open(os.path.join(manual_lib.MANUAL, "index.json"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps(index))
    for lang, words in search.items():
        with open(os.path.join(manual_lib.MANUAL, "search-%s.json" % lang), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(words, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("%d pages in %d parts, build %s" % (len(index["pages"]), len(index["parts"]), index["build"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
