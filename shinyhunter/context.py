from __future__ import annotations

from .pokemon import parse_pk7


class HuntContext:
    def __init__(self, profile, rsp, input_client, verbose=True):
        self.profile = profile
        self.rsp = rsp
        self.input = input_client
        self.verbose = verbose
        self.vars: dict[str, object] = {}

    def log(self, message: str) -> None:
        print(message)

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
