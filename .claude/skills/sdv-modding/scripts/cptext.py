"""Insert into JSON files (content.json, i18n, SID packs) WITHOUT reformatting them.

Content Patcher/SMAPI JSON allows // and /* */ comments and trailing commas, so round-tripping through json.dump would destroy
the author's comments and layout. These helpers find the right closing bracket with a comment- and string-aware scan and splice
text in, keeping everything else byte-for-byte (comments, indentation, trailing-comma style).
"""
from __future__ import annotations

import json
import re

from sdvlib import loads_tolerant

NL = "\n"


def _blank(s: str) -> str:
    return "".join(ch if ch == NL else " " for ch in s)


def mask(text: str) -> tuple[str, str]:
    """Return (code, shape), both the same length as text.
    code: comments blanked. shape: comments blanked and the inside of every string replaced by 'x' (safe for bracket matching)."""
    code, shape = [], []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            code.append(c)
            if c == "\\" and i + 1 < n:
                code.append(text[i + 1]); shape.append("x"); shape.append("x"); i += 2; continue
            if c == '"':
                in_str = False; shape.append('"')
            else:
                shape.append("x")
            i += 1; continue
        if c == '"':
            in_str = True; code.append(c); shape.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find(NL, i); j = n if j == -1 else j
            code.append(_blank(text[i:j])); shape.append(_blank(text[i:j])); i = j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); j = n if j == -1 else j + 2
            code.append(_blank(text[i:j])); shape.append(_blank(text[i:j])); i = j; continue
        code.append(c); shape.append(c); i += 1
    return "".join(code), "".join(shape)


def _match_close(shape: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(shape)):
        if shape[i] in "[{":
            depth += 1
        elif shape[i] in "]}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unclosed bracket")


def _unit(text: str) -> str:
    return "\t" if (NL + "\t") in text else "  "


def _indent_block(s: str, indent: str) -> str:
    lines = s.splitlines()
    return lines[0] + "".join(NL + indent + ln for ln in lines[1:])


def _leading_ws(s: str) -> str:
    return re.match(r"[ \t]*", s).group(0)


def _insert(text: str, open_idx: int, item_text: str) -> str:
    """Append item_text as a new last element of the array/object opened at open_idx, leaving everything else untouched."""
    code, shape = mask(text)
    close_idx = _match_close(shape, open_idx)
    last = max((i for i in range(open_idx + 1, close_idx) if not shape[i].isspace()), default=None)
    close_line = text.rfind(NL, 0, close_idx) + 1
    close_alone = not text[close_line:close_idx].strip()          # the closing bracket sits on its own line
    open_line = text.rfind(NL, 0, open_idx) + 1
    base = _leading_ws(text[close_line:close_idx]) if close_alone else _leading_ws(text[open_line:])
    indent = base + _unit(text)
    item = _indent_block(item_text, indent)
    if last is None:                                              # empty container (maybe only comments)
        if close_alone:
            return text[:close_line] + indent + item + NL + text[close_line:]
        return text[:close_idx] + NL + indent + item + NL + base + text[close_idx:]
    eol = text.find(NL, last)
    pos = close_idx if eol == -1 or eol > close_idx else eol      # end of the last element's line, before its trailing comment
    tail = NL + base if pos == close_idx else ""
    if shape[last] == ",":                                        # the file uses trailing commas: keep that style
        return text[:pos] + NL + indent + item + "," + tail + text[pos:]
    return text[:last + 1] + "," + text[last + 1:pos] + NL + indent + item + tail + text[pos:]


def _find_open(text: str, key: str | None) -> int:
    code, shape = mask(text)
    if key is None:
        i = shape.find("{")
        if i < 0:
            raise ValueError("no root object")
        return i
    for m in re.finditer(r'"%s"\s*:\s*([\[{])' % re.escape(key), code):
        if shape[m.start()] == '"':                               # a real key, not text inside a string
            return m.end() - 1
    raise ValueError(f'key "{key}" not found')


def insert_in_array(text: str, key: str, item) -> str:
    """Append an object/string to the array under "key" (first match), e.g. "Changes" or "Sprites"."""
    item_text = item if isinstance(item, str) else json.dumps(item, indent=_unit(text), ensure_ascii=False)
    return _insert(text, _find_open(text, key), item_text)


def insert_in_object(text: str, entries: dict, key: str | None = None) -> str:
    """Add "k": v members to the root object (or the object under "key")."""
    for k, v in entries.items():
        member = json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, indent=_unit(text), ensure_ascii=False)
        text = _insert(text, _find_open(text, key), member)
    return text


def has_include(text: str, from_file: str) -> bool:
    try:
        data = loads_tolerant(text)
    except Exception:
        return False
    want = from_file.replace("\\", "/")
    for ch in (data.get("Changes") or []):
        if isinstance(ch, dict) and ch.get("Action") == "Include":
            if want in [p.strip().replace("\\", "/") for p in str(ch.get("FromFile", "")).split(",")]:
                return True
    return False


def add_include(text: str, from_file: str) -> str:
    if has_include(text, from_file):
        return text
    line = '{ "Action": "Include", "FromFile": ' + json.dumps(from_file.replace("\\", "/")) + " }"
    return insert_in_array(text, "Changes", line)
