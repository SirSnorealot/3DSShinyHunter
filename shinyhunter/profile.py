from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


def _int_value(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(value, 0)


@dataclass
class PartyConfig:
    base: int
    slot_stride: int
    core_size: int = 232


@dataclass
class GameProfile:
    id: str
    name: str
    process_name: str
    process_id: int | None
    gdb_port: int
    input_port: int
    generation: int
    party: PartyConfig | None
    addresses: dict[str, int]

    @classmethod
    def load(cls, path: str | Path) -> "GameProfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        party_raw = raw.get("party")
        party = None
        if party_raw:
            party = PartyConfig(
                base=_int_value(party_raw["base"]),
                slot_stride=_int_value(party_raw["slot_stride"]),
                core_size=_int_value(party_raw.get("core_size", 232)),
            )

        addresses = {
            key: _int_value(value) for key, value in raw.get("addresses", {}).items()
        }

        return cls(
            id=raw["id"],
            name=raw["name"],
            process_name=raw["process"]["name"],
            process_id=_int_value(raw["process"].get("pid")),
            gdb_port=int(raw.get("connection", {}).get("gdb_port", 4000)),
            input_port=int(raw.get("connection", {}).get("input_port", 4950)),
            generation=int(raw["generation"]),
            party=party,
            addresses=addresses,
        )
