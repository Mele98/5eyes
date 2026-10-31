"""Minimal SQLite-DDL parser for exactly the supported CHECK value-list forms.

UPGRADE-PATH-CHECK-DRIFT-001 (residual 1): the previous regex only recognised
``CHECK(col IN (...))`` and silently ignored every other form, including
``CHECK(col IS NULL OR col IN (...))`` that the reference schema itself uses.

This module replaces the regex heuristic with a real tokenizer (string
literals with ``''`` escapes, ``"..."``/```...```/``[...]`` quoted identifiers,
``--`` and ``/* */`` comments, balanced parentheses) and a closed grammar.

Supported CHECK forms (outer redundant parentheses allowed)::

    CHECK ( <col> IN ( 'a', 'b', ... ) )
    CHECK ( <col> IS NULL OR <col> IN ( 'a', 'b', ... ) )      -- same <col>

Every CHECK whose expression contains ``IN (`` followed by a string literal
but does not match one of these forms is reported as :class:`UnsupportedCheck`
-- the caller must treat it as ``manual_migration_required`` and never widen
it heuristically. CHECKs without a string-literal IN list (``x >= 0``,
``x IN (0, 1)``, ``json_valid(x)``) are not subject of the value-list
contract and are ignored.

In SQLite a CHECK passes when its expression is NULL, so both supported forms
already admit NULL; they differ only in spelling. Widening keeps the spelling
of the existing database and only appends literals.
"""
from __future__ import annotations

from dataclasses import dataclass

_WORD_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_WORD_CHARS = _WORD_START | set("0123456789$")
_IDENT_QUOTES = {'"': '"', "`": "`", "[": "]"}


class DdlParseError(ValueError):
    """DDL cannot be tokenized safely (unterminated literal/comment, parens)."""


@dataclass(frozen=True)
class Token:
    kind: str  # word | qident | string | number | punct
    text: str  # raw source text
    start: int
    end: int  # exclusive

    @property
    def keyword(self) -> str | None:
        return self.text.upper() if self.kind == "word" else None

    @property
    def identifier(self) -> str | None:
        if self.kind == "word":
            return self.text.lower()
        if self.kind == "qident":
            close = _IDENT_QUOTES[self.text[0]]
            inner = self.text[1:-1]
            if close != "]":
                inner = inner.replace(close * 2, close)
            return inner.lower()
        return None

    @property
    def string_value(self) -> str:
        return self.text[1:-1].replace("''", "'")


@dataclass(frozen=True)
class SupportedCheck:
    column: str
    nullable_form: bool
    literals: tuple[str, ...]  # raw literal text, e.g. "'video'"
    insert_at: int  # source offset right after the last literal

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(_literal_value(literal) for literal in self.literals)


@dataclass(frozen=True)
class UnsupportedCheck:
    columns: frozenset[str]
    text: str


@dataclass(frozen=True)
class TableDdl:
    name: str
    start: int
    end: int  # exclusive, after the closing parenthesis
    checks: tuple[SupportedCheck | UnsupportedCheck, ...]


def _literal_value(literal: str) -> str:
    return literal[1:-1].replace("''", "'")


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            close = sql.find("*/", index + 2)
            if close < 0:
                raise DdlParseError("unterminated block comment")
            index = close + 2
            continue
        if char == "'":
            cursor = index + 1
            while True:
                quote = sql.find("'", cursor)
                if quote < 0:
                    raise DdlParseError("unterminated string literal")
                if quote + 1 < length and sql[quote + 1] == "'":
                    cursor = quote + 2
                    continue
                break
            tokens.append(Token("string", sql[index:quote + 1], index, quote + 1))
            index = quote + 1
            continue
        if char in _IDENT_QUOTES:
            close_char = _IDENT_QUOTES[char]
            cursor = index + 1
            while True:
                close = sql.find(close_char, cursor)
                if close < 0:
                    raise DdlParseError("unterminated quoted identifier")
                if close_char != "]" and close + 1 < length and sql[close + 1] == close_char:
                    cursor = close + 2
                    continue
                break
            tokens.append(Token("qident", sql[index:close + 1], index, close + 1))
            index = close + 1
            continue
        if char in _WORD_START:
            cursor = index + 1
            while cursor < length and sql[cursor] in _WORD_CHARS:
                cursor += 1
            tokens.append(Token("word", sql[index:cursor], index, cursor))
            index = cursor
            continue
        if char.isdigit():
            cursor = index + 1
            while cursor < length and (sql[cursor].isalnum() or sql[cursor] == "."):
                cursor += 1
            tokens.append(Token("number", sql[index:cursor], index, cursor))
            index = cursor
            continue
        tokens.append(Token("punct", char, index, index + 1))
        index += 1
    return tokens


def _matching(tokens: list[Token], open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(tokens)):
        text = tokens[index].text if tokens[index].kind == "punct" else ""
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
            if depth == 0:
                return index
    raise DdlParseError("unbalanced parentheses")


def _is_punct(token: Token, text: str) -> bool:
    return token.kind == "punct" and token.text == text


def _strip_outer_parens(expr: list[Token]) -> list[Token]:
    while len(expr) >= 2 and _is_punct(expr[0], "(") and _matching(expr, 0) == len(expr) - 1:
        expr = expr[1:-1]
    return expr


def _match_in_list(expr: list[Token]) -> tuple[str, list[Token]] | None:
    """``<ident> IN ( 'a' [, 'b' ...] )`` covering the whole token list."""
    if len(expr) < 5 or expr[0].identifier is None or expr[0].keyword in _RESERVED:
        return None
    if expr[1].keyword != "IN" or not _is_punct(expr[2], "(") or not _is_punct(expr[-1], ")"):
        return None
    if _matching(expr, 2) != len(expr) - 1:
        return None
    body = expr[3:-1]
    literals = body[0::2]
    separators = body[1::2]
    if not literals or len(literals) != len(separators) + 1:
        return None
    if any(token.kind != "string" for token in literals):
        return None
    if any(not _is_punct(token, ",") for token in separators):
        return None
    return expr[0].identifier, literals


_RESERVED = {"NOT", "NULL", "IS", "OR", "AND", "IN", "CHECK", "CASE", "WHEN"}


def _classify(expr: list[Token], source: str) -> SupportedCheck | UnsupportedCheck | None:
    has_string_in_list = any(
        token.keyword == "IN"
        and index + 2 < len(expr)
        and _is_punct(expr[index + 1], "(")
        and expr[index + 2].kind == "string"
        for index, token in enumerate(expr)
    )
    if not has_string_in_list:
        return None
    inner = _strip_outer_parens(expr)
    direct = _match_in_list(inner)
    if direct is not None:
        column, literals = direct
        return SupportedCheck(column, False, tuple(t.text for t in literals), literals[-1].end)
    if (
        len(inner) > 4
        and inner[0].identifier is not None
        and inner[0].keyword not in _RESERVED
        and inner[1].keyword == "IS"
        and inner[2].keyword == "NULL"
        and inner[3].keyword == "OR"
    ):
        nullable = _match_in_list(_strip_outer_parens(inner[4:]))
        if nullable is not None and nullable[0] == inner[0].identifier:
            column, literals = nullable
            return SupportedCheck(column, True, tuple(t.text for t in literals), literals[-1].end)
    columns = frozenset(
        token.identifier for token in expr
        if token.identifier is not None and token.keyword not in _RESERVED
    )
    return UnsupportedCheck(columns, source[expr[0].start:expr[-1].end])


def _checks_in(tokens: list[Token], source: str) -> tuple[SupportedCheck | UnsupportedCheck, ...]:
    found: list[SupportedCheck | UnsupportedCheck] = []
    for index, token in enumerate(tokens):
        if token.keyword != "CHECK":
            continue
        if index + 1 >= len(tokens) or not _is_punct(tokens[index + 1], "("):
            raise DdlParseError("CHECK without parenthesised expression")
        close = _matching(tokens, index + 1)
        classified = _classify(tokens[index + 2:close], source)
        if classified is not None:
            found.append(classified)
    return tuple(found)


def parse_create_tables(sql: str) -> list[TableDdl]:
    """All ``CREATE TABLE`` statements of a script (or one stored DDL)."""
    tokens = tokenize(sql)
    tables: list[TableDdl] = []
    index = 0
    while index < len(tokens):
        if tokens[index].keyword != "CREATE":
            index += 1
            continue
        cursor = index + 1
        if cursor < len(tokens) and tokens[cursor].keyword in {"TEMP", "TEMPORARY"}:
            cursor += 1
        if cursor >= len(tokens) or tokens[cursor].keyword != "TABLE":
            index += 1
            continue
        cursor += 1
        if (
            cursor + 2 < len(tokens)
            and tokens[cursor].keyword == "IF"
            and tokens[cursor + 1].keyword == "NOT"
            and tokens[cursor + 2].keyword == "EXISTS"
        ):
            cursor += 3
        if cursor >= len(tokens) or tokens[cursor].identifier is None:
            raise DdlParseError("CREATE TABLE without table name")
        name = tokens[cursor].identifier
        cursor += 1
        if cursor + 1 < len(tokens) and _is_punct(tokens[cursor], "."):
            name = tokens[cursor + 1].identifier or name
            cursor += 2
        if cursor >= len(tokens) or not _is_punct(tokens[cursor], "("):
            index = cursor  # CREATE TABLE ... AS SELECT: not subject
            continue
        close = _matching(tokens, cursor)
        body = tokens[cursor:close + 1]
        tables.append(TableDdl(
            name, tokens[index].start, tokens[close].end, _checks_in(body, sql),
        ))
        index = close + 1
    return tables


def parse_table_ddl(table_sql: str) -> TableDdl:
    tables = parse_create_tables(table_sql)
    if len(tables) != 1:
        raise DdlParseError(f"expected exactly one CREATE TABLE, found {len(tables)}")
    return tables[0]
