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
        elif len(args) == 3 and args[0].lower() == "var":
            name, expected = args[1], args[2]
            value = str(self.ctx.vars.get(name, "")).lower() == expected.lower()
        else:
            raise ScriptError(
                f"Line {line}: condition must be 'shiny party N', "
                f"'not shiny party N', or 'var NAME VALUE'"
            )

        return not value if negate else value

    def _run_block(self, nodes: list[Node], in_loop: bool) -> None:
        for node in nodes:
            op = node.op
            a = node.args

            if op == "press":
                if not a:
                    raise ScriptError(f"Line {node.line}: press requires button(s)")
                duration = 0.10
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
                # Keep re-sending held controller state during waits.
                self.ctx.input.pump(_duration(a[0]))

            elif op == "log":
                self.ctx.log(" ".join(a))

            elif op == "set":
                if len(a) < 2:
                    raise ScriptError(f"Line {node.line}: set NAME VALUE")
                self.ctx.vars[a[0]] = " ".join(a[1:])

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
