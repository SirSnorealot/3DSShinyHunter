from __future__ import annotations

from dataclasses import dataclass
import shlex
import time


class ScriptError(RuntimeError):
    pass


@dataclass
class Node:
    op: str
    args: list[str]
    body: list["Node"] | None = None
    else_body: list["Node"] | None = None
    line: int = 0


def _duration(value: str) -> float:
    value = value.strip().lower()
    try:
        if value.endswith("ms"):
            return float(value[:-2]) / 1000.0
        if value.endswith("s"):
            return float(value[:-1])
        return float(value) / 1000.0  # bare numbers = ms
    except ValueError as exc:
        raise ScriptError(f"Invalid duration: {value}") from exc


def _parse_value(value: str):
    """Parse integers/floats; leave all other values as strings."""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
        return int(value, 0)
    except ValueError:
        return value


def _number(value, *, line: int, name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScriptError(f"Line {line}: variable {name!r} is not numeric")
    return value


def _clean_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def parse_script(text: str) -> list[Node]:
    root: list[Node] = []
    stack: list[tuple[Node | None, list[Node]]] = [(None, root)]

    for line_no, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        try:
            parts = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise ScriptError(f"Line {line_no}: {exc}") from exc

        if not parts:
            continue

        op = parts[0].lower()
        args = parts[1:]

        if op == "end":
            if len(stack) == 1:
                raise ScriptError(f"Line {line_no}: unexpected 'end'")
            stack.pop()
            continue

        if op == "else":
            if len(stack) == 1 or stack[-1][0] is None:
                raise ScriptError(f"Line {line_no}: unexpected 'else'")
            owner = stack[-1][0]
            if owner.op != "if":
                raise ScriptError(f"Line {line_no}: 'else' only belongs to 'if'")
            stack.pop()
            owner.else_body = []
            stack.append((owner, owner.else_body))
            continue

        node = Node(op=op, args=args, line=line_no)

        if op in ("repeat", "if"):
            node.body = []
            stack[-1][1].append(node)
            stack.append((node, node.body))
        else:
            stack[-1][1].append(node)

    if len(stack) != 1:
        owner = stack[-1][0]
        raise ScriptError(f"Unclosed block starting on line {owner.line if owner else '?'}")

    return root


class _BreakLoop(Exception):
    pass


class _ContinueLoop(Exception):
    pass


class HuntRunner:
    def __init__(self, ctx):
        self.ctx = ctx

    def run(self, nodes: list[Node]) -> None:
        try:
            self._run_block(nodes, in_loop=False)
        finally:
            self.ctx.input.release_all()

    def _condition(self, args: list[str], line: int) -> bool:
        negate = False
        if args and args[0].lower() == "not":
            negate = True
            args = args[1:]

        if len(args) == 3 and args[0].lower() == "shiny" and args[1].lower() == "party":
            value = self.ctx.party_slot_is_shiny(int(args[2]))

        elif len(args) == 2 and args[0].lower() == "shiny" and args[1].lower() in ("opponent", "wild"):
            value = self.ctx.opponent_is_shiny()

        elif args and args[0].lower() == "var":
            if len(args) == 3:
                # Backwards-compatible shorthand: if var mode hunting
                name, expected_text = args[1], args[2]
                if name not in self.ctx.vars:
                    raise ScriptError(f"Line {line}: undefined variable {name!r}")
                actual = self.ctx.vars[name]
                expected = _parse_value(expected_text)
                value = actual == expected

            elif len(args) == 4:
                name, operator, expected_text = args[1], args[2], args[3]
                if name not in self.ctx.vars:
                    raise ScriptError(f"Line {line}: undefined variable {name!r}")
                actual = self.ctx.vars[name]
                expected = _parse_value(expected_text)

                if operator == "==":
                    value = actual == expected
                elif operator == "!=":
                    value = actual != expected
                elif operator in (">", ">=", "<", "<="):
                    actual_num = _number(actual, line=line, name=name)
                    expected_num = _number(expected, line=line, name="comparison value")
                    if operator == ">":
                        value = actual_num > expected_num
                    elif operator == ">=":
                        value = actual_num >= expected_num
                    elif operator == "<":
                        value = actual_num < expected_num
                    else:
                        value = actual_num <= expected_num
                else:
                    raise ScriptError(
                        f"Line {line}: unsupported comparison operator {operator!r}"
                    )
            else:
                raise ScriptError(
                    f"Line {line}: use 'if var NAME VALUE' or "
                    f"'if var NAME OP VALUE'"
                )
        else:
            raise ScriptError(
                f"Line {line}: condition must be 'shiny party N', "
                f"'shiny opponent', 'shiny wild', their 'not' forms, "
                f"or a variable comparison"
            )

        return not value if negate else value

    def _run_block(self, nodes: list[Node], in_loop: bool) -> None:
        for node in nodes:
            op = node.op
            a = node.args

            if op == "press":
                if not a:
                    raise ScriptError(f"Line {node.line}: press requires button(s)")
                duration = 0.18
                buttons = a
                # Optional: press A B for 250ms
                if len(a) >= 2 and a[-2].lower() == "for":
                    duration = _duration(a[-1])
                    buttons = a[:-2]
                self.ctx.input.press([b.upper() for b in buttons], duration=duration)

            elif op == "hold":
                if not a:
                    raise ScriptError(f"Line {node.line}: hold requires button(s)")
                self.ctx.input.hold(*[b.upper() for b in a])

            elif op == "release":
                if not a:
                    raise ScriptError(f"Line {node.line}: release requires button(s)")
                self.ctx.input.release(*[b.upper() for b in a])

            elif op == "release_all":
                self.ctx.input.release_all()

            elif op in ("delay", "sleep"):
                if len(a) != 1:
                    raise ScriptError(f"Line {node.line}: delay requires one duration")
                self.ctx.wait(_duration(a[0]))

            elif op == "restart_game":
                if len(a) > 2:
                    raise ScriptError(
                        f"Line {node.line}: restart_game [SETTLE_DELAY] [TIMEOUT]"
                    )
                settle = _duration(a[0]) if len(a) >= 1 else 10.0
                timeout = _duration(a[1]) if len(a) >= 2 else 30.0
                self.ctx.restart_game(settle, timeout)

            elif op == "log":
                self.ctx.log(" ".join(a))

            elif op == "logfile":
                if len(a) != 1:
                    raise ScriptError(f"Line {node.line}: logfile PATH")
                self.ctx.set_log_file(self.ctx.interpolate(a[0]))

            elif op == "set":
                if len(a) < 2:
                    raise ScriptError(f"Line {node.line}: set NAME VALUE")
                raw = " ".join(a[1:])
                self.ctx.vars[a[0]] = _parse_value(self.ctx.interpolate(raw))

            elif op in ("add", "subtract", "sub", "multiply", "mul", "divide", "div", "mod"):
                if len(a) != 2:
                    raise ScriptError(f"Line {node.line}: {op} NAME VALUE")
                name, raw_amount = a
                if name not in self.ctx.vars:
                    raise ScriptError(f"Line {node.line}: undefined variable {name!r}")
                current = _number(self.ctx.vars[name], line=node.line, name=name)
                amount = _number(
                    _parse_value(self.ctx.interpolate(raw_amount)),
                    line=node.line,
                    name="amount",
                )

                if op == "add":
                    result = current + amount
                elif op in ("subtract", "sub"):
                    result = current - amount
                elif op in ("multiply", "mul"):
                    result = current * amount
                elif op in ("divide", "div"):
                    if amount == 0:
                        raise ScriptError(f"Line {node.line}: division by zero")
                    result = current / amount
                else:
                    if amount == 0:
                        raise ScriptError(f"Line {node.line}: modulo by zero")
                    result = current % amount

                self.ctx.vars[name] = _clean_number(result)

            elif op in ("inc", "dec"):
                if len(a) not in (1, 2):
                    raise ScriptError(f"Line {node.line}: {op} NAME [AMOUNT]")
                name = a[0]
                if name not in self.ctx.vars:
                    raise ScriptError(f"Line {node.line}: undefined variable {name!r}")
                current = _number(self.ctx.vars[name], line=node.line, name=name)
                amount = 1 if len(a) == 1 else _number(
                    _parse_value(self.ctx.interpolate(a[1])),
                    line=node.line,
                    name="amount",
                )
                result = current + amount if op == "inc" else current - amount
                self.ctx.vars[name] = _clean_number(result)

            elif op == "if":
                branch = node.body if self._condition(a, node.line) else (node.else_body or [])
                self._run_block(branch or [], in_loop=in_loop)

            elif op == "repeat":
                if len(a) != 1:
                    raise ScriptError(f"Line {node.line}: repeat N|forever")
                if a[0].lower() == "forever":
                    iterator = iter(int, 1)  # infinite iterator
                else:
                    try:
                        iterator = range(int(a[0]))
                    except ValueError as exc:
                        raise ScriptError(f"Line {node.line}: invalid repeat count") from exc

                for _ in iterator:
                    try:
                        self._run_block(node.body or [], in_loop=True)
                    except _ContinueLoop:
                        continue
                    except _BreakLoop:
                        break

            elif op == "break":
                if not in_loop:
                    raise ScriptError(f"Line {node.line}: break outside loop")
                raise _BreakLoop()

            elif op == "continue":
                if not in_loop:
                    raise ScriptError(f"Line {node.line}: continue outside loop")
                raise _ContinueLoop()

            elif op == "stop":
                self.ctx.log("[HUNT] stop")
                return

            else:
                raise ScriptError(f"Line {node.line}: unknown command {op!r}")
