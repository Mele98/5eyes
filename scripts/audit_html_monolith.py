"""Inventory snapshot generator for the 5eyes_v2.html monolith.

Sprint U-35: before splitting the large HTML file into modules, capture a
deterministic inventory of DOM ids, inline event handlers, JS declarations,
CSS selectors, modal structures, and section-like containers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "audits" / "2026-06-02-monolith-inventory.json"

_JS_PATTERNS = (
    ("function", re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")),
    (
        "const",
        re.compile(
            r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
            r"(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
        ),
    ),
    (
        "let",
        re.compile(
            r"\blet\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
            r"(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
        ),
    ),
    (
        "var",
        re.compile(
            r"\bvar\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
            r"(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
        ),
    ),
    (
        "window",
        re.compile(r"\bwindow\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"),
    ),
)


@dataclass(frozen=True)
class Element:
    tag: str
    attrs: dict[str, str]
    line: int
    col: int


class MonolithParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.elements: list[Element] = []
        self.style_blocks: list[dict[str, Any]] = []
        self.script_blocks: list[dict[str, Any]] = []
        self._current_raw_tag: str | None = None
        self._current_raw_start: tuple[int, int] | None = None
        self._current_raw_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line, col = self.getpos()
        normalized_attrs = {
            str(name).lower(): "" if value is None else str(value)
            for name, value in attrs
        }
        self.elements.append(Element(tag=str(tag).lower(), attrs=normalized_attrs, line=line, col=col))
        if tag.lower() in {"style", "script"}:
            self._current_raw_tag = tag.lower()
            self._current_raw_start = (line, col)
            self._current_raw_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if self._current_raw_tag != tag.lower():
            return
        text = "".join(self._current_raw_chunks)
        line, col = self._current_raw_start or (0, 0)
        block = {"line": line, "col": col, "text": text}
        if self._current_raw_tag == "style":
            self.style_blocks.append(block)
        else:
            self.script_blocks.append(block)
        self._current_raw_tag = None
        self._current_raw_start = None
        self._current_raw_chunks = []

    def handle_data(self, data: str) -> None:
        if self._current_raw_tag:
            self._current_raw_chunks.append(data)


def build_inventory(html_path: Path = DEFAULT_HTML) -> dict[str, Any]:
    html_path = Path(html_path)
    text = html_path.read_text(encoding="utf-8")
    parser = MonolithParser()
    parser.feed(text)

    ids = _collect_ids(parser.elements)
    event_handlers = _collect_event_handlers(parser.elements)
    modal_structures = _collect_modal_structures(parser.elements)
    sub_sections = _collect_sub_sections(parser.elements)
    css_selectors = _collect_css_selectors(parser.style_blocks)
    js_functions = _collect_js_functions(parser.script_blocks)

    inventory = {
        "inventory_version": 1,
        "source_path": _repo_relative(html_path),
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_size_bytes": len(text.encode("utf-8")),
        "counts": {
            "ids": len(ids),
            "event_handlers": len(event_handlers),
            "js_functions": len(js_functions),
            "css_selectors": len(css_selectors),
            "modal_structures": len(modal_structures),
            "sub_sections": len(sub_sections),
            "style_blocks": len(parser.style_blocks),
            "script_blocks": len(parser.script_blocks),
        },
        "ids": ids,
        "event_handlers": event_handlers,
        "js_functions": js_functions,
        "css_selectors": css_selectors,
        "modal_structures": modal_structures,
        "sub_sections": sub_sections,
    }
    return inventory


def _collect_ids(elements: list[Element]) -> list[dict[str, Any]]:
    rows = []
    for el in elements:
        element_id = el.attrs.get("id")
        if not element_id:
            continue
        rows.append({
            "id": element_id,
            "tag": el.tag,
            "class": el.attrs.get("class", ""),
            "line": el.line,
        })
    return sorted(rows, key=lambda row: (row["id"], row["line"], row["tag"]))


def _collect_event_handlers(elements: list[Element]) -> list[dict[str, Any]]:
    rows = []
    for el in elements:
        for attr, value in el.attrs.items():
            if not attr.startswith("on"):
                continue
            rows.append({
                "handler": attr,
                "tag": el.tag,
                "id": el.attrs.get("id", ""),
                "class": el.attrs.get("class", ""),
                "value": _compact(value),
                "line": el.line,
            })
    return sorted(rows, key=lambda row: (row["handler"], row["id"], row["line"], row["value"]))


def _collect_modal_structures(elements: list[Element]) -> list[dict[str, Any]]:
    rows = []
    for el in elements:
        element_id = el.attrs.get("id", "")
        class_name = el.attrs.get("class", "")
        role = el.attrs.get("role", "")
        is_modal = (
            "modal" in _tokens(class_name)
            or "modal" in element_id.lower()
            or element_id.lower().startswith("m-")
            or role.lower() == "dialog"
        )
        if not is_modal:
            continue
        rows.append({
            "id": element_id,
            "tag": el.tag,
            "class": class_name,
            "role": role,
            "line": el.line,
        })
    return sorted(rows, key=lambda row: (row["id"], row["line"], row["class"]))


def _collect_sub_sections(elements: list[Element]) -> list[dict[str, Any]]:
    rows = []
    for el in elements:
        element_id = el.attrs.get("id", "")
        class_name = el.attrs.get("class", "")
        class_tokens = _tokens(class_name)
        looks_like_section = (
            element_id.startswith(("sec-", "asec-", "subsec-", "admin-sec-"))
            or "sub-section" in class_tokens
            or "admin-section" in class_tokens
            or el.tag == "section"
        )
        if not looks_like_section:
            continue
        rows.append({
            "id": element_id,
            "tag": el.tag,
            "class": class_name,
            "line": el.line,
        })
    return sorted(rows, key=lambda row: (row["id"], row["line"], row["tag"]))


def _collect_css_selectors(style_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for block in style_blocks:
        css = _strip_css_comments(block["text"])
        offset_line = int(block["line"])
        for selector, rel_line in _iter_css_selectors(css):
            key = (selector, offset_line + rel_line)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"selector": selector, "line": offset_line + rel_line})
    return sorted(rows, key=lambda row: (row["selector"], row["line"]))


def _iter_css_selectors(css: str):
    depth = 0
    token_start = 0
    line = 0
    at_rule_stack: list[str] = []
    i = 0
    while i < len(css):
        ch = css[i]
        if ch == "\n":
            line += 1
        if ch == "{":
            prelude = css[token_start:i].strip()
            if prelude.startswith("@"):
                at_rule_stack.append(prelude.split(None, 1)[0].lower())
            elif depth == len(at_rule_stack):
                for selector in _split_selectors(prelude):
                    if selector:
                        yield selector, line
            depth += 1
            token_start = i + 1
        elif ch == "}":
            depth = max(0, depth - 1)
            if at_rule_stack and depth < len(at_rule_stack):
                at_rule_stack.pop()
            token_start = i + 1
        i += 1


def _split_selectors(prelude: str) -> list[str]:
    selectors = []
    current = []
    paren_depth = 0
    for ch in prelude:
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        if ch == "," and paren_depth == 0:
            selectors.append(" ".join("".join(current).split()))
            current = []
        else:
            current.append(ch)
    if current:
        selectors.append(" ".join("".join(current).split()))
    return [s for s in selectors if s and not s.startswith("@")]


def _collect_js_functions(script_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for block in script_blocks:
        text = block["text"]
        base_line = int(block["line"])
        for declaration_type, pattern in _JS_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1)
                line = base_line + text[:match.start()].count("\n")
                key = (name, declaration_type, line)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "name": name,
                    "declaration": declaration_type,
                    "line": line,
                })
    return sorted(rows, key=lambda row: (row["name"], row["line"], row["declaration"]))


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _tokens(class_name: str) -> set[str]:
    return {token.strip().lower() for token in str(class_name or "").split() if token.strip()}


def _compact(value: str, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _repo_relative(path: Path) -> str:
    return str(Path(path).resolve().relative_to(REPO_ROOT)).replace("\\", "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true", help="Print JSON instead of writing the output file.")
    args = parser.parse_args(argv)

    inventory = build_inventory(args.input)
    rendered = json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.stdout:
        print(rendered, end="")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {_repo_relative(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
