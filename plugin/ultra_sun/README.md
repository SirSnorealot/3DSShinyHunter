# Pokémon Ultra Sun plugin

Read-only 3GX PK7 memory bridge for the **North American Pokémon Ultra Sun** build used by 3DSShinyHunter.

- Output: `3DSShinyHunter-UltraSun.3gx`
- North American title ID / install folder: `00040000001B5000`
- UDP port: `4951`
- RAM map: shared USUM Gen VII party/opponent layout

Build and installation instructions are in [`../../BUILD.md`](../../BUILD.md).
The wire format is documented in [`PROTOCOL.md`](PROTOCOL.md).

## Luma requirement

This plugin uses UDP sockets and is built with `UsePrivateMemory: true`. Use Luma3DS 13.3.3 or newer; 13.4+ is recommended. If the plugin fails at startup, the OSD now reports each networking initialization stage.
