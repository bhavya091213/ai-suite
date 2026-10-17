"""Expression language, filters and evaluator behind ``installer.core.render``.

Grammar (lowest to highest precedence)::

    expr     := or_expr ( "|" filter )*
    or_expr  := and_expr ( "or" and_expr )*
    and_expr := not_expr ( "and" not_expr )*
    not_expr := "not" not_expr | compare
    compare  := primary ( ("==" | "!=") primary )*
    primary  := path | "double quoted string" | integer | "(" expr ")"
    filter   := name [ "(" literal ( "," literal )* ")" ]

``path`` is a dotted name; an all-digit segment indexes a list or tuple. The block-structure
parser (``parse_blocks``) turns the renderer's tag tokens into a node tree. Parsed expressions
are plain tuples (``("path", "a.b")``, ``("and", left, right)``, ...) so they can be cached
and shared. The evaluator never mutates the context and never raises for an unknown path: it
yields ``None`` and records a ``"<source>:<line>: unknown value <path>"`` warning.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

Node = Tuple
Token = Tuple[Optional[str], Any]
BlockToken = Tuple[str, str, int]  # ("text"|"var"|"block", value, original line)

_KEYWORDS = ("not", "and", "or", "in")
_CLOSERS = ("elif", "else", "endif", "endfor")
_FOR_RE = re.compile(r"for\s+([A-Za-z_]\w*)\s+in\s+(.+)$", re.S)
_TOKEN_RE = re.compile(
    r'\s*(?:(==|!=|[()|,])|("(?:[^"\\]|\\.)*")|(-?\d+)(?![\w.])|([A-Za-z_]\w*(?:\.\w+)*))')


class RenderError(Exception):
    """A template could not be parsed or rendered, or a tree could not be mirrored."""


# ------------------------------------------------------------------ values

def resolve(container: Any, segments: Sequence[str]) -> Tuple[bool, Any]:
    """Walk ``segments`` through mappings and sequences. ``(found, value)``; never raises."""
    value = container
    for segment in segments:
        if isinstance(value, Mapping) and segment in value:
            value = value[segment]
        elif isinstance(value, (list, tuple)) and segment.isdigit() and int(segment) < len(value):
            value = value[int(segment)]
        else:
            return False, None
    return True, value


def to_text(value: Any) -> str:
    """Output form of a value: None -> "", bools -> true/false, lists -> ", " joined."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(to_text(v) for v in value)
    return str(value)


def short_count(number: int) -> str:
    """100000 -> "100k", 1500000 -> "1.5M", 999 -> "999"."""
    for divisor, suffix in ((1000000, "M"), (1000, "k")):
        if abs(number) >= divisor:
            return f"{round(number / divisor, 2):g}{suffix}"
    return str(number)


# ------------------------------------------------------------------ filters

def _filter_tilde(value: Any, args: Tuple, home: str) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(_filter_tilde(v, args, home) for v in value)
    root = home.rstrip("/")
    if root and isinstance(value, str) and (value == root or value.startswith(root + "/")):
        return "~" + value[len(root):]
    return value


def _filter_k(value: Any, args: Tuple, home: str) -> Any:
    try:
        return short_count(int(value))
    except (TypeError, ValueError):
        return value


def _filter_join(value: Any, args: Tuple, home: str) -> Any:
    separator = str(args[0]) if args else ", "
    if isinstance(value, (list, tuple)):
        return separator.join(to_text(v) for v in value)
    return to_text(value)


def _filter_default(value: Any, args: Tuple, home: str) -> Any:
    return value if value else args[0]


# name -> (function, minimum arguments, maximum arguments)
FILTERS: Mapping[str, Tuple[Callable[[Any, Tuple, str], Any], int, int]] = {
    "tilde": (_filter_tilde, 0, 0),
    "k": (_filter_k, 0, 0),
    "join": (_filter_join, 0, 1),
    "default": (_filter_default, 1, 1),
}


# ------------------------------------------------------------------ parser

def _unescape(body: str) -> str:
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def tokenize_expr(expr: str, where: str) -> List[Token]:
    """Split an expression into ``(kind, value)`` tokens: op, str, int, kw or path."""
    tokens: List[Token] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if match is None:
            if not expr[pos:].strip():
                break
            raise RenderError(f"{where}: bad expression near {expr[pos:].strip()!r}")
        pos = match.end()
        if match.group(1):
            tokens.append(("op", match.group(1)))
        elif match.group(2):
            tokens.append(("str", _unescape(match.group(2)[1:-1])))
        elif match.group(3):
            tokens.append(("int", int(match.group(3))))
        else:
            word = match.group(4)
            tokens.append(("kw", word) if word in _KEYWORDS else ("path", word))
    return tokens


class _Parser:
    """Recursive descent over the token list (see the module docstring for the grammar)."""

    def __init__(self, tokens: List[Token], where: str) -> None:
        self.tokens, self.index, self.where = tokens, 0, where

    def peek(self) -> Token:
        return self.tokens[self.index] if self.index < len(self.tokens) else (None, None)

    def take(self) -> Token:
        token = self.peek()
        self.index += 1
        return token

    def accept(self, kind: str, value: str) -> bool:
        if self.peek() == (kind, value):
            self.index += 1
            return True
        return False

    def parse(self) -> Node:
        if not self.tokens:
            raise RenderError(f"{self.where}: empty expression")
        node = self.expression()
        if self.index != len(self.tokens):
            raise RenderError(f"{self.where}: unexpected {self.tokens[self.index][1]!r}")
        return node

    def expression(self) -> Node:
        node = self.disjunction()
        while self.accept("op", "|"):
            node = self.filter_call(node)
        return node

    def filter_call(self, node: Node) -> Node:
        kind, name = self.take()
        if kind != "path" or "." in name:
            raise RenderError(f"{self.where}: expected a filter name after '|'")
        if name not in FILTERS:
            raise RenderError(f"{self.where}: unknown filter {name!r}")
        args = self.arguments() if self.accept("op", "(") else ()
        _, low, high = FILTERS[name]
        if not low <= len(args) <= high:
            raise RenderError(f"{self.where}: filter {name!r} takes {low}-{high} argument(s), got {len(args)}")
        return ("filter", node, name, args)

    def arguments(self) -> Tuple:
        args: List[Any] = []
        while not self.accept("op", ")"):
            if args and not self.accept("op", ","):
                raise RenderError(f"{self.where}: expected ')' after filter arguments")
            kind, value = self.take()
            if kind not in ("str", "int"):
                raise RenderError(f"{self.where}: filter arguments must be strings or integers")
            args.append(value)
        return tuple(args)

    def disjunction(self) -> Node:
        node = self.conjunction()
        while self.accept("kw", "or"):
            node = ("or", node, self.conjunction())
        return node

    def conjunction(self) -> Node:
        node = self.negation()
        while self.accept("kw", "and"):
            node = ("and", node, self.negation())
        return node

    def negation(self) -> Node:
        if self.accept("kw", "not"):
            return ("not", self.negation())
        return self.comparison()

    def comparison(self) -> Node:
        node = self.primary()
        while self.peek() in (("op", "=="), ("op", "!=")):
            op = self.take()[1]
            node = ("eq" if op == "==" else "ne", node, self.primary())
        return node

    def primary(self) -> Node:
        kind, value = self.take()
        if kind == "op" and value == "(":
            node = self.expression()
            if not self.accept("op", ")"):
                raise RenderError(f"{self.where}: expected ')'")
            return node
        if kind in ("str", "int"):
            return ("lit", value)
        if kind == "path":
            return ("path", value)
        if kind is None:
            raise RenderError(f"{self.where}: unexpected end of expression")
        raise RenderError(f"{self.where}: unexpected {value!r}")


def parse_expr(expr: str, where: str) -> Node:
    """Parse ``expr`` into a node tuple. Raises ``RenderError("<where>: ...")`` when malformed."""
    return _Parser(tokenize_expr(expr, where), where).parse()


# ------------------------------------------------------------------ evaluator

class Evaluator:
    """Evaluate parsed expressions against a context, collecting unknown-path warnings.

    ``scopes`` (innermost last) is passed per call as a tuple of mappings, so entering a
    ``for`` body is ``scopes + (frame,)`` and nothing is ever pushed or popped.
    """

    def __init__(self, context: Mapping, source: str) -> None:
        self.context, self.source = context, source
        self.warnings: List[str] = []
        found, home = resolve(context, ["env", "HOME"])
        self.home = str(home) if found and home else os.path.expanduser("~")

    def warn(self, line: int, message: str) -> None:
        text = f"{self.source}:{line}: {message}"
        if text not in self.warnings:
            self.warnings.append(text)

    def lookup(self, path: str, line: int, scopes: Sequence[Mapping]) -> Any:
        segments = path.split(".")
        for scope in reversed(scopes):
            if segments[0] in scope:
                found, value = resolve(scope, segments)
                break
        else:
            found, value = resolve(self.context, segments)
        if not found:
            self.warn(line, f"unknown value {path}")
        return value

    def evaluate(self, node: Node, line: int, scopes: Sequence[Mapping] = ()) -> Any:
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "path":
            return self.lookup(node[1], line, scopes)
        if kind == "not":
            return not self.evaluate(node[1], line, scopes)
        if kind == "filter":
            _, inner, name, args = node
            return FILTERS[name][0](self.evaluate(inner, line, scopes), args, self.home)
        left = self.evaluate(node[1], line, scopes)
        if kind == "and":
            return left and self.evaluate(node[2], line, scopes)
        if kind == "or":
            return left or self.evaluate(node[2], line, scopes)
        right = self.evaluate(node[2], line, scopes)
        return left == right if kind == "eq" else left != right

    def text(self, node: Node, line: int, scopes: Sequence[Mapping] = ()) -> str:
        """Evaluate and format for output."""
        return to_text(self.evaluate(node, line, scopes))


# ------------------------------------------------------------------ block parser

def _tag_parts(value: str) -> Tuple[str, str]:
    parts = value.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def _parse_body(tokens: List[BlockToken], index: int, stop: Tuple[str, ...],
                source: str) -> Tuple[List[Tuple], int]:
    """Parse nodes until a block tag named in ``stop`` (left unconsumed) or the end."""
    nodes: List[Tuple] = []
    while index < len(tokens):
        kind, value, line = tokens[index]
        where = f"{source}:{line}"
        if kind == "text":
            nodes.append(("text", value))
        elif kind == "var":
            nodes.append(("var", parse_expr(value, where), line))
        else:
            word = _tag_parts(value)[0]
            if word in stop:
                return nodes, index
            if word in _CLOSERS:
                raise RenderError(f"{where}: unexpected {{% {word} %}}")
            if word not in ("if", "for"):
                raise RenderError(f"{where}: unknown tag {{% {word} %}}")
            node, index = (_parse_if if word == "if" else _parse_for)(tokens, index, source)
            nodes.append(node)
            continue
        index += 1
    return nodes, index


def _parse_if(tokens: List[BlockToken], index: int, source: str) -> Tuple[Tuple, int]:
    open_line = tokens[index][2]
    branches: List[Tuple] = []
    while True:
        _, value, line = tokens[index]
        word, rest = _tag_parts(value)
        if word == "else":
            if rest:
                raise RenderError(f"{source}:{line}: {{% else %}} takes no expression")
            condition = None
        else:
            condition = parse_expr(rest, f"{source}:{line}")
        body, index = _parse_body(tokens, index + 1, ("elif", "else", "endif"), source)
        if index >= len(tokens):
            raise RenderError(f"{source}:{open_line}: unclosed {{% if %}}")
        branches.append((condition, tuple(body), line))
        closer, close_line = _tag_parts(tokens[index][1])[0], tokens[index][2]
        if closer == "endif":
            return ("if", tuple(branches), open_line), index + 1
        if condition is None:
            raise RenderError(f"{source}:{close_line}: {{% {closer} %}} after {{% else %}}")


def _parse_for(tokens: List[BlockToken], index: int, source: str) -> Tuple[Tuple, int]:
    _, value, open_line = tokens[index]
    where = f"{source}:{open_line}"
    match = _FOR_RE.match(value)
    if match is None:
        raise RenderError(f"{where}: malformed {{% for %}} (expected 'for <name> in <expr>')")
    expression = parse_expr(match.group(2), where)
    body, index = _parse_body(tokens, index + 1, ("endfor",), source)
    if index >= len(tokens):
        raise RenderError(f"{where}: unclosed {{% for %}}")
    return ("for", match.group(1), expression, tuple(body), open_line), index + 1


def parse_blocks(tokens: List[BlockToken], source: str) -> List[Tuple]:
    """Turn tag tokens into a node tree: ``text``, ``var``, ``if`` and ``for`` nodes.

    Raises ``RenderError("<source>:<line>: ...")`` for unknown, unbalanced or malformed tags.
    """
    return _parse_body(tokens, 0, (), source)[0]
