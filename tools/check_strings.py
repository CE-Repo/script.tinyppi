#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Check the add-on's string tables against each other and against their users.

Fails on:

- a language file whose string ids are not exactly those of en_gb, or whose
  msgid for an id is not en_gb's -- a source text changed in one file only;
- an id that appears twice in one file;
- a string id that settings.xml, a skin file or the Python code asks for and
  en_gb does not define.  In the Python, any number from 30000 to 33999 is
  taken for a string id: the add-on's strings are the only numbers it has in
  that range.

Reports without failing:

- strings a language has not translated yet; Kodi shows those in English.

Run from the repository root:

    python3 tools/check_strings.py
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGUAGES = os.path.join(ROOT, "resources", "language")
REFERENCE = "resource.language.en_gb"

# Where a .po entry's strings start, and the continuation lines after them.
_KEYWORD = re.compile(r'^(msgctxt|msgid|msgstr)\s+"(.*)"\s*$')
_CONTINUATION = re.compile(r'^"(.*)"\s*$')
_CONTEXT_ID = re.compile(r"^#(\d+)$")

_SETTINGS_IDS = re.compile(r'(?:label|help)="(\d+)"|<heading>(\d+)</heading>')
_SKIN_IDS = re.compile(r"\$ADDON\[script\.tinyppi (\d+)\]")
_PYTHON_IDS = re.compile(r"(?<![\w.])(3[0-3]\d{3})(?![\w.])")

_ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"


def _report(kind: str, path: str, message: str) -> None:
    where = os.path.relpath(path, ROOT)
    if _ON_GITHUB:
        print(f"::{kind} file={where}::{message}")
    else:
        print(f"{kind.upper()}: {where}: {message}")


def read_po(path: str) -> tuple[dict[int, tuple[str, str]], list[int]]:
    """``{id: (msgid, msgstr)}`` for one file, and the ids seen twice."""
    entries: dict[int, tuple[str, str]] = {}
    duplicates: list[int] = []
    current: dict[str, str] = {}
    field = ""

    def flush() -> None:
        match = _CONTEXT_ID.match(current.get("msgctxt", ""))
        if match and "msgid" in current:
            string_id = int(match.group(1))
            if string_id in entries:
                duplicates.append(string_id)
            entries[string_id] = (current["msgid"], current.get("msgstr", ""))

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            keyword = _KEYWORD.match(line)
            if keyword:
                field, text = keyword.groups()
                if field == "msgctxt":
                    flush()
                    current = {}
                current[field] = text
                continue
            continuation = _CONTINUATION.match(line)
            if continuation and field:
                current[field] += continuation.group(1)
                continue
            field = ""
    flush()
    return entries, duplicates


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def referenced_ids() -> dict[int, str]:
    """Every string id the add-on asks for, with one file that asks for it."""
    found: dict[int, str] = {}

    settings = os.path.join(ROOT, "resources", "settings.xml")
    for match in _SETTINGS_IDS.finditer(_text(settings)):
        string_id = int(match.group(1) or match.group(2))
        # Below 30000 is Kodi's own table, not this add-on's.
        if string_id >= 30000:
            found.setdefault(string_id, settings)

    for path in glob.glob(os.path.join(ROOT, "resources", "skins", "**", "*.xml"),
                          recursive=True):
        for match in _SKIN_IDS.finditer(_text(path)):
            found.setdefault(int(match.group(1)), path)

    python = glob.glob(os.path.join(ROOT, "resources", "lib", "**", "*.py"),
                       recursive=True) + [os.path.join(ROOT, "main.py")]
    for path in python:
        for match in _PYTHON_IDS.finditer(_text(path)):
            found.setdefault(int(match.group(1)), path)
    return found


def main() -> int:
    reference_path = os.path.join(LANGUAGES, REFERENCE, "strings.po")
    reference, duplicates = read_po(reference_path)
    errors = 0

    for string_id in duplicates:
        _report("error", reference_path, f"#{string_id} is defined twice")
        errors += 1

    for string_id, path in sorted(referenced_ids().items()):
        if string_id not in reference:
            _report("error", path, f"string #{string_id} is used but not "
                                   f"defined in {REFERENCE}")
            errors += 1

    for path in sorted(glob.glob(os.path.join(LANGUAGES, "*", "strings.po"))):
        if path == reference_path:
            continue
        entries, duplicates = read_po(path)
        for string_id in duplicates:
            _report("error", path, f"#{string_id} is defined twice")
            errors += 1
        for string_id in sorted(reference.keys() - entries.keys()):
            _report("error", path, f"#{string_id} is missing")
            errors += 1
        for string_id in sorted(entries.keys() - reference.keys()):
            _report("error", path, f"#{string_id} is not in {REFERENCE}")
            errors += 1

        untranslated = []
        for string_id, (msgid, msgstr) in sorted(entries.items()):
            if string_id not in reference:
                continue
            if msgid != reference[string_id][0]:
                _report("error", path, f"#{string_id} has a msgid other than "
                                       f"{REFERENCE}'s: {msgid!r}")
                errors += 1
            elif msgid and not msgstr:
                untranslated.append(string_id)
        if untranslated:
            shown = ", ".join(f"#{string_id}" for string_id in untranslated[:10])
            more = f" and {len(untranslated) - 10} more" if len(untranslated) > 10 else ""
            _report("warning", path, f"{len(untranslated)} untranslated "
                                     f"string(s): {shown}{more}")

    print(f"{len(reference)} strings in {REFERENCE}; {errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
