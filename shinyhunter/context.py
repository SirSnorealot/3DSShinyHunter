from __future__ import annotations

from .pokemon import parse_pk7


class HuntContext:
    def __init__(self, profile, memory, input_client, verbose=True, log_file=None, trace_timing=False):
        self.profile = profile
        self.memory = memory
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
        if self.verbose:
            self.log(
                f"[{self.memory.label}] Reading party slot {slot} RAM"
            )
        raw = self.memory.read_memory(address, party.core_size)
        if self.verbose:
            self.log(f"[{self.memory.label}] Party RAM read complete")
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
                f"valid={pkm['valid']} shiny={pkm['shiny']}"
            )
        return bool(pkm["shiny"])

    def read_opponent(self) -> dict:
        opponent = self.profile.opponent
        if opponent is None:
            raise RuntimeError(
                f"{self.profile.name} has no opponent layout configured"
            )

        if self.verbose:
            self.log(f"[{self.memory.label}] Reading opponent RAM")
        raw = self.memory.read_memory(opponent.base, opponent.core_size)
        if self.verbose:
            self.log(f"[{self.memory.label}] Opponent RAM read complete")
        pkm = parse_pk7(raw)
        pkm["address"] = opponent.base
        return pkm

    def opponent_is_shiny(self) -> bool:
        pkm = self.read_opponent()
        if self.verbose:
            self.log(
                f"[CHECK] opponent species={pkm['species']} "
                f"PID=0x{pkm['pid']:08X} xor={pkm['shiny_xor']} "
                f"valid={pkm['valid']} shiny={pkm['shiny']} "
                f"address=0x{pkm['address']:08X}"
            )
        if not pkm["present"]:
            return False
        return bool(pkm["shiny"])

    def restart_game(self, settle_seconds: float = 10.0, reconnect_timeout: float = 30.0) -> None:
        """Restart the game and wait for the selected memory backend to return.

        USUM with the 3GX backend deliberately uses a HOME-menu close/relaunch
        instead of the game's L+R+START soft reset. Luma has a long-standing
        USUM/InputRedirection failure mode around repeated in-game soft resets,
        and a full title relaunch also guarantees a fresh plugin/network state.
        """
        if self.memory.kind != "plugin":
            self.log(
                f"[RESTART] Preparing soft reset; memory backend={self.memory.kind}"
            )
            self.input.release_all()
            self.log("[RESTART] Released all controller inputs")
            self.memory.before_restart()
            self.log(f"[RESTART] {self.memory.label} backend prepared for restart")
            self.log("[RESTART] Sending L+R+START soft-reset chord")
            self.input.press(["L", "R", "START"], duration=0.150, after=0.100)
            self.log("[RESTART] Soft-reset chord sent")
            self.log(f"[RESTART] Waiting {settle_seconds:.3f}s for title restart")
            self.wait(settle_seconds)
            self.log(f"[RESTART] Waiting for {self.memory.label} backend to become ready")
            ready = self.memory.wait_ready(timeout=reconnect_timeout)
            self.log(f"[RESTART] {self.memory.label} backend ready: {ready}")
            return

        self.log("[RESTART] USUM plugin mode: full HOME-menu title relaunch")
        self.input.release_all()
        self.log("[RESTART] Released all controller inputs")
        self.memory.before_restart()

        self.log("[RESTART] Pressing HOME through InputRedirection special-button bit")
        self.input.press_home(duration=0.250, after=0.300)
        self.wait(2.0)

        self.log("[RESTART] HOME Menu: pressing X to close the suspended title")
        self.input.press(["X"], duration=0.200, after=0.200)
        self.wait(1.0)

        self.log("[RESTART] HOME Menu: pressing A to confirm Close")
        self.input.press(["A"], duration=0.200, after=0.200)

        self.log("[RESTART] Waiting for old plugin instance to disappear")
        self.memory.wait_stopped(timeout=12.0)
        self.log("[RESTART] Old plugin instance stopped")

        # Give HOME Menu a moment to finish title teardown and restore the
        # selected software icon before launching it again.
        self.wait(1.5)
        self.log("[RESTART] HOME Menu: pressing A to relaunch the selected title")
        self.input.press(["A"], duration=0.200, after=0.250)

        self.log(f"[RESTART] Waiting {settle_seconds:.3f}s for title startup")
        self.wait(settle_seconds)

        self.log("[RESTART] Waiting for new PLUGIN instance to become ready")
        ready = self.memory.wait_ready(timeout=reconnect_timeout)
        self.log(f"[RESTART] New PLUGIN instance ready: {ready}")
