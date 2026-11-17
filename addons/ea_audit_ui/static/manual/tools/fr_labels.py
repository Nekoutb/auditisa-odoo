"""Finds the French screen text of an English label, so a French help page names it exactly.

    python fr_labels.py "Engagement record" "+ New engagement"   # English label -> French text
    python fr_labels.py --fr "Fiche de la mission"                # is this French text on a screen?
    python fr_labels.py --check fr/materiality.html               # bold labels not found on any screen

The words come from every add-on's i18n/fr.po and from the bilingual working-paper definitions.
"""
import sys

import manual_lib


def main(argv):
    pairs = manual_lib.ui_pairs()
    if argv[:1] == ["--check"]:
        known = manual_lib.known_texts(fr for _en, fr in pairs)
        for path in argv[1:]:
            for label in manual_lib.bold_labels(manual_lib.read(path)):
                if not manual_lib.label_known(label, known):
                    print("%s: not on a screen: %s" % (path, label))
        return 0
    if argv[:1] == ["--fr"]:
        known = manual_lib.known_texts(fr for _en, fr in pairs)
        for text in argv[1:]:
            print("%s: %s" % ("yes" if manual_lib.label_known(text, known) else "NO", text))
        return 0
    for label in argv:
        wanted = manual_lib.normalize(label)
        exact = sorted({fr for en, fr in pairs if manual_lib.normalize(en) == wanted})
        print("== %s" % label)
        if exact:
            for fr in exact:
                print("   %s" % fr)
            continue
        near = sorted({(en, fr) for en, fr in pairs if wanted and wanted in manual_lib.normalize(en) and len(en) < 120})
        for en, fr in near[:12]:
            print("   ~ %s  =>  %s" % (en, fr))
        if not near:
            print("   (not found: an Odoo screen of its own, or not a label)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
