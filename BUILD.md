# Build and plugin installation

This document covers the WSL 3DS toolchain, building the 3GX plugins, and installing them on a console.

## Why the Ultra games use plugins

For **Pokémon Ultra Sun** and **Pokémon Ultra Moon**, 3DSShinyHunter should use the included 3GX memory plugins instead of Luma GDB for normal hunts. Repeated debugger attachment can be unstable during long Pokémon hunts; the plugins run inside the game process and expose only the allow-listed PK7 records needed by the hunt engine.

The distributed Ultra plugins in this project are intended for **North American copies** of the games.

| Game | North American title ID | Plugin file |
|---|---|---|
| Pokémon Ultra Sun | `00040000001B5000` | `3DSShinyHunter-UltraSun.3gx` |
| Pokémon Ultra Moon | `00040000001B5100` | `3DSShinyHunter-UltraMoon.3gx` |

Both profiles default to `memory_backend: plugin`. GDB remains available as a development/debugging backend via `--memory-backend gdb`.

## WSL setup

The project can stay in its Windows folder and be accessed through `/mnt/c/...`. A dedicated Ubuntu WSL distro is recommended.

Run the one-time setup from the project root inside WSL:

```bash
./tools/wsl/setup_3ds.sh
```

Then reload the environment and verify it:

```bash
source ~/.bashrc
./tools/wsl/check_3ds_env.sh
```

The WSL environment provides devkitARM, libctru, libctrpf, and 3gxtool. Toolchain binaries are intentionally not stored in this repository.

## Build all plugins

There is one build command for every plugin in the repository:

```bash
./tools/wsl/build_plugins.sh
```

The script stages each plugin into native Linux temporary storage before compiling, avoiding `/mnt/c` clock-skew/9p build problems, then copies the resulting `.3gx` back into the Windows project.

Expected outputs:

```text
plugin/ultra_sun/3DSShinyHunter-UltraSun.3gx
plugin/ultra_moon/3DSShinyHunter-UltraMoon.3gx
```

## Install on the SD card

Copy each plugin into the matching **North American title-ID folder** on the 3DS SD card.

### Pokémon Ultra Sun (North America)

```text
sd:/luma/plugins/00040000001B5000/3DSShinyHunter-UltraSun.3gx
```

### Pokémon Ultra Moon (North America)

```text
sd:/luma/plugins/00040000001B5100/3DSShinyHunter-UltraMoon.3gx
```

Do not put both plugins in the same title-ID directory.

## Enable Luma Plugin Loader

On the 3DS:

1. Open Rosalina with `L + D-Pad Down + Select`.
2. Enable **Plugin Loader**.
3. Launch the matching Ultra game.

The plugin should display an OSD notification that 3DSShinyHunter is listening on UDP port `4951`.

## Test the plugin backend

Ultra Sun:

```powershell
python run_hunt.py 192.168.1.50 games/ultra_sun.json hunts/demo/party_shiny_demo.hunt
```

Ultra Moon:

```powershell
python run_hunt.py 192.168.1.50 games/ultra_moon.json hunts/demo/party_shiny_demo.hunt
```

Replace `192.168.1.50` with the 3DS IP. A successful run prints `Memory backend: plugin` and `[PLUGIN]` for RAM reads.

## Plugin RAM map

Ultra Sun and Ultra Moon use the same USUM Gen VII addresses in this project:

```text
Party base:                    0x33F7FA44
Party slot stride:             484 bytes
PK7 core size:                 232 bytes
Primary wild opponent:         0x3254F4AC
Double-battle opponent slot 2: 0x32663BF0
SOS last-called helper:        0x30039888
SOS previous helpers:          0x3002F9A0
```

The game-side bridge is intentionally read-only and only allows the configured PK7-sized regions.

### Soft-reset lifecycle

The Ultra plugins use CTRPluginFramework's current `OnProcessExit()` callback during a title reset. The callback is deliberately non-blocking: it sets an exit flag, stops the UDP receive loop, and calls `shutdown()` only to wake `recvfrom()`. It does **not** call `threadJoin`, `socExit`, `free`, or other teardown routines while Horizon is destroying the game process. The plugin main loop polls the exit flag every 50 ms and returns, leaving process resources for the operating system to reclaim with the title.
