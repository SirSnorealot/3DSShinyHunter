from __future__ import annotations

from .pokemon import parse_pk7


class HuntContext:
    def __init__(self, profile, rsp, input_client, verbose=True, log_file=None, trace_timing=False):
        self.profile = profile
        self.rsp = rsp
        self.input = input_client
        self.verbose = verbose
        self.vars: dict[str, object] = {}
        self.trace_timing = trace_timing
        self.log_file = None
        if log_file:
            self.set_log_file(log_file)

    def set_log_file(self, path) -> None:
        from pathlib import Path

        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = target

    def interpolate(self, text: str) -> str:
        import re

        pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

        def replace(match):
            name = match.group(1)
            if name not in self.vars:
                raise RuntimeError(f"Undefined variable in message: {name}")
            return str(self.vars[name])

        return pattern.sub(replace, text)

    def log(self, message: str) -> None:
        message = self.interpolate(message)
        print(message)
        if self.log_file is not None:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")


    def wait(self, seconds: float) -> None:
        elapsed = self.input.wait(seconds)
        if self.trace_timing:
            self.log(f"[TIMING] delay requested={seconds:.3f}s actual={elapsed:.3f}s")

    def read_party_slot(self, slot: int) -> dict:
        party = self.profile.party
        if party is None:
            raise RuntimeError(f"{self.profile.name} has no party layout configured")
        if not 1 <= slot <= 6:
            raise ValueError("Party slot must be 1..6")

        address = party.base + (slot - 1) * party.slot_stride
        raw = self.rsp.read_memory(address, party.core_size)
        pkm = parse_pk7(raw)
        pkm["slot"] = slot
        pkm["address"] = address
        return pkm

    def party_slot_is_shiny(self, slot: int) -> bool:
        pkm = self.read_party_slot(slot)
        if self.verbose:
            self.log(
                f"[CHECK] party[{slot}] species={pkm['species']} "
                f"PID=0x{pkm['pid']:08X} xor={pkm['shiny_xor']} "
                f"shiny={pkm['shiny']}"
            )
        return bool(pkm["shiny"])

    def read_opponent(self) -> dict:
        opponent = self.profile.opponent
        if opponent is None:
            raise RuntimeError(
                f"{self.profile.name} has no opponent layout configured"
            )

        raw = self.rsp.read_memory(opponent.base, opponent.core_size)
        pkm = parse_pk7(raw)
        pkm["address"] = opponent.base
        pkm["present"] = pkm["species"] != 0
        return pkm

    def opponent_is_shiny(self) -> bool:
        pkm = self.read_opponent()
        if self.verbose:
            self.log(
                f"[CHECK] opponent species={pkm['species']} "
                f"PID=0x{pkm['pid']:08X} xor={pkm['shiny_xor']} "
                f"shiny={pkm['shiny']} "
                f"address=0x{pkm['address']:08X}"
            )
        if not pkm["present"]:
            return False
        return bool(pkm["shiny"])

