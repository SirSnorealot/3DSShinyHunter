# 3DSShinyHunter

3DSShinyHunter is a Python framework for automating shiny-hunting workflows on real Nintendo 3DS hardware running Luma3DS. It combines Rosalina InputRedirection with game-specific memory backends and a small `.hunt` scripting language. Written with the help of AI.

The project keeps reusable connection/input/script logic under `shinyhunter/`, game RAM layouts under `games/`, hunt scripts under `hunts/`, and 3GX memory plugins under `plugin/`.

## Supported Ultra games

Pokémon **Ultra Sun** and **Ultra Moon** should use the included **3GX plugins** for normal hunting. The plugins avoid repeated Luma GDB attachment during long hunts and provide a small, read-only PK7 memory bridge to the Python runner.

The distributed Ultra plugins are intended for **North American copies**:

| Game | Profile | North American title ID |
|---|---|---|
| Pokémon Ultra Sun | `games/ultra_sun.json` | `00040000001B5000` |
| Pokémon Ultra Moon | `games/ultra_moon.json` | `00040000001B5100` |

Both Ultra profiles default to the plugin memory backend. GDB is retained as an optional development/debugging backend.

For Ultra Sun/Ultra Moon, `restart_game` uses a **full HOME-menu close and relaunch**, not the in-game L+R+START soft reset. This keeps each encounter on a fresh title/plugin instance and avoids a known Luma InputRedirection failure mode associated with repeated USUM soft resets.

## Requirements

- Python 3.10+ on the PC
- Nintendo 3DS with modern Luma3DS
- Rosalina InputRedirection enabled
- Luma Plugin Loader enabled for the Ultra-game plugin backend
- PC and 3DS on the same network

## Quick start

Prebuilt versions of the Ultra plugins are included. For **Pokémon Ultra Sun** and **Pokémon Ultra Moon**, install and enable the matching 3GX plugin before running a hunt. These prebuilt plugins are for **North American copies**.

### Install the Ultra plugins

Copy the plugin that matches your game to the exact title-ID folder on the 3DS SD card:

| Game | Source file | SD destination |
|---|---|---|
| Ultra Sun | `plugin/ultra_sun/3DSShinyHunter-UltraSun.3gx` | `sd:/luma/plugins/00040000001B5000/3DSShinyHunter-UltraSun.3gx` |
| Ultra Moon | `plugin/ultra_moon/3DSShinyHunter-UltraMoon.3gx` | `sd:/luma/plugins/00040000001B5100/3DSShinyHunter-UltraMoon.3gx` |

Keep each plugin in its own title-ID folder. Luma loads a game-specific `.3gx` from the folder matching the launched title.

### Enable the Luma Plugin Loader

After copying the plugin to the SD card:

1. Boot the 3DS normally.
2. Press **L + D-Pad Down + Select** to open the Rosalina menu.
3. Move to **Plugin Loader**.
4. Press **A** and make sure it shows **[Enabled]**.
5. Exit Rosalina.
6. Launch Ultra Sun or Ultra Moon normally.

The Plugin Loader setting stays enabled until you turn it off, so this normally only needs to be done once.

When the correct 3DSShinyHunter plugin loads, it starts the read-only memory bridge used by the Python runner. If the runner cannot contact the plugin, first verify the game-specific `.3gx` is in the exact title-ID folder above and that **Plugin Loader** is enabled.

If you want to build the plugins from source, full WSL setup/build instructions are in **[BUILD.md](BUILD.md)**.

Then run a hunt from the project root, replacing the IP with your 3DS address.

Ultra Sun example:

```powershell
python run_hunt.py 192.168.1.50 games/ultra_sun.json hunts/ultra_sun/partner_cap_pikachu.hunt
```

Ultra Moon example:

```powershell
python run_hunt.py 192.168.1.50 games/ultra_moon.json hunts/ultra_moon/partner_cap_pikachu.hunt
```

Use `Ctrl+C` as an emergency stop.

## Hunt scripts

Hunts are plain-text `.hunt` files and are normally organized by game:

```text
hunts/<game_id>/
```

They support button presses, delays, loops, variables, logging, soft resets, party shiny checks, and wild/opponent shiny checks. The complete language and runner reference is in **[COMMANDS.md](COMMANDS.md)**.

