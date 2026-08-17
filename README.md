# 3DSShinyHunter

3DSShinyHunter is a Python framework for automating shiny-hunting workflows on real Nintendo 3DS hardware.

It uses:

- **Luma3DS GDB** for reading game RAM.
- **Rosalina InputRedirection** for controller input.
- **Game profiles** for process names and game-specific RAM layouts.
- A compact **`.hunt` scripting language** for hunt logic.

The project is intentionally split so that connection/input code is reusable, while RAM layouts and hunt scripts remain game-specific.

## Why hunts are game-specific

A hunt script belongs to a specific game because different Pokémon games can have different:

- Process names.
- RAM layouts.
- Encounter structures.
- Battle-state addresses.
- Menu timings.
- Reset sequences.
- Overworld behavior.

For that reason, hunts are grouped under:

```text
hunts/<game_id>/
```

For example:

```text
hunts/ultra_moon/
```

A future ultra_moon hunt would live under:

```text
hunts/ultra_moon/
```

## Requirements

- Python 3.10+
- A Nintendo 3DS running Luma3DS
- Luma GDB enabled
- Rosalina InputRedirection enabled
- The 3DS and PC on the same network

## Running a hunt

From the project root:

```powershell
python run_hunt.py 192.168.1.50 games/ultra_moon.json hunts/demo/party_shiny_demo.hunt
```

Replace `192.168.1.50` with your 3DS IP address.

### Input test

```powershell
python run_hunt.py 192.168.1.50 games/ultra_moon.json hunts/demo/input_demo.hunt
```

### Loop / branching test

```powershell
python run_hunt.py 192.168.1.50 games/ultra_moon.json hunts/demo/loop_demo.hunt
```

Use `Ctrl+C` as an emergency stop.

The runner attempts to:

- Release all controller inputs.
- Resume the game if it was paused by GDB.
- Close both network connections cleanly.


## Ultra Moon opponent RAM

Ultra Moon's primary opponent Pokémon is configured at:

```text
0x3254F4AC
```

Additional known Gen VII battle addresses are stored in `games/ultra_moon.json`:

```text
Primary opponent:          0x3254F4AC
Double-battle opponent 2:  0x32663BF0
SOS last-called helper:    0x30039888
SOS previous helpers:      0x3002F9A0
```

While already in a wild battle:

```text
if shiny opponent
    log "SHINY FOUND"
else
    log "Not shiny"
end
```

`shiny wild` is an alias, and negation is supported:

```text
if not shiny opponent
    log "Keep hunting"
end
```

Test:

```powershell
python run_hunt.py 192.168.1.50 games/ultra_moon.json hunts/demo/opponent_shiny_demo.hunt
```

# `.hunt` language

`.hunt` files are plain-text hunt scripts.

Blank lines and lines beginning with `#` are ignored.

## Button presses

```text
press A
press B for 200ms
press L R START for 150ms
```

Multiple buttons on the same `press` line are sent as a chord.

Supported digital buttons:

```text
A B X Y
L R
START SELECT
UP DOWN LEFT RIGHT
```

## Held input

```text
hold LEFT
delay 750ms
release LEFT
```

Release every currently held button:

```text
release_all
```

## Delays

```text
delay 500
delay 500ms
delay 2s
sleep 1s
```

Bare numbers are milliseconds.

## Logging

```text
log "Starting hunt"
```

## Party shiny checks

```text
if shiny party 1
    log "Slot 1 is shiny"
else
    log "Slot 1 is not shiny"
end
```

Negation:

```text
if not shiny party 1
    log "Keep hunting"
end
```

Party slots are numbered `1` through `6`.

When a shiny check runs, 3DSShinyHunter:

1. Interrupts the game through Luma GDB.
2. Reads the configured party slot.
3. Decrypts the PK7 structure.
4. Calculates Gen VII shiny XOR.
5. Resumes the game.
6. Returns true or false to the hunt script.

## Loops

Repeat a fixed number of times:

```text
repeat 10
    press A
    delay 500ms
end
```

Run indefinitely:

```text
repeat forever
    press A
    delay 1s
end
```

Inside a loop:

```text
break
continue
```

Example:

```text
repeat forever
    press A
    delay 1s

    if shiny party 1
        log "SHINY FOUND"
        break
    else
        log "Not shiny"
    end

    delay 500ms
end
```

## Variables

Version 0.1 includes simple string variables:

```text
set mode hunting

if var mode hunting
    log "Hunt mode active"
end
```

This is intentionally minimal for now.

# Game profiles

Game profiles live under:

```text
games/
```

Each profile contains game-specific configuration.

Example:

```json
{
  "id": "pokemon_ultra_moon",
  "name": "Pokémon Ultra Moon",
  "generation": 7,
  "connection": {
    "gdb_port": 4000,
    "input_port": 4950
  },
  "process": {
    "name": "momiji",
    "pid": null
  },
  "party": {
    "base": "0x33F7FA44",
    "slot_stride": 484,
    "core_size": 232
  },
  "opponent": {
    "base": "0x3254F4AC",
    "core_size": 232
  },
  "addresses": {
    "wild_opponent": "0x3254F4AC"
  }
}
```

The `addresses` section is reserved for named game-specific RAM locations such as:

```json
{
  "addresses": {
    "wild_opponent": "0x...",
    "battle_state": "0x..."
  }
}
```

That will let hunt scripts use semantic commands while the actual RAM addresses stay in the profile.

