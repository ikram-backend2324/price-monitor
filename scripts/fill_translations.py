"""Fill locale/{ru,uz}/LC_MESSAGES/django.po from scripts/translations.py and compile .mo files.

Usage (after `python manage.py makemessages -l ru -l uz -l en`):
    python scripts/fill_translations.py

Uses polib, so .mo files can be compiled even on machines without GNU gettext.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from translations import T  # noqa: E402


def main() -> int:
    missing: set[str] = set()
    for idx, lang in enumerate(("ru", "uz")):
        path = ROOT / "locale" / lang / "LC_MESSAGES" / "django.po"
        po = polib.pofile(str(path))
        po.metadata["Language"] = lang
        po.metadata["Content-Type"] = "text/plain; charset=UTF-8"
        if lang == "ru":
            po.metadata["Plural-Forms"] = (
                "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);"
            )
        else:
            po.metadata["Plural-Forms"] = "nplurals=2; plural=(n != 1);"
        for entry in po:
            if entry.msgid in T:
                entry.msgstr = T[entry.msgid][idx]
                if "fuzzy" in entry.flags:
                    entry.flags.remove("fuzzy")
            else:
                missing.add(entry.msgid)
        po.save(str(path))
        po.save_as_mofile(str(path.with_suffix(".mo")))
    en = ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"
    if en.exists():
        polib.pofile(str(en)).save_as_mofile(str(en.with_suffix(".mo")))
    for msgid in sorted(missing):
        print(f"MISSING: {msgid!r}")
    print(f"done, {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
