# Command reference

`.hunt` files are plain-text hunt scripts. Blank lines and lines beginning with `#` are ignored.

## Run a hunt

```powershell
python run_hunt.py <3DS_IP> <game.json> <hunt.hunt>
```

Optional runner flags:

```text
--memory-backend plugin|gdb
--log-file PATH
--trace-timing
--quiet
```

Ultra Sun and Ultra Moon profiles default to `plugin`.

## Input

```text
press A
press B for 200ms
press L R START for 150ms
hold LEFT
release LEFT
release_all
```

Supported digital buttons:

```text
A B X Y L R START SELECT UP DOWN LEFT RIGHT
```

## Timing

```text
delay 500
delay 500ms
delay 2s
sleep 1s
```

Bare duration numbers are milliseconds.

## Logging

```text
log "Starting hunt"
logfile "logs/my_hunt.txt"
```

Variables can be interpolated with `{name}`:

```text
set encounters 12
log "Encounter #{encounters}"
```

`logfile` appends; it does not overwrite an existing log.

## Variables

```text
set encounters 0
set target 100
set mode hunting

add encounters 5
subtract encounters 2
sub encounters 1
multiply encounters 3
mul encounters 2
divide encounters 2
div encounters 2
mod encounters 10
inc encounters
inc encounters 5
dec encounters
```

Numeric-looking values become numbers, `true`/`false` become booleans, and other values are strings.

## Shiny conditions

Party slots are numbered 1 through 6:

```text
if shiny party 6
    log "SHINY FOUND"
else
    log "Not shiny"
end
```

Wild/opponent checks:

```text
if shiny opponent
    log "SHINY FOUND"
end

if shiny wild
    log "SHINY FOUND"
end
```

`wild` is an alias for `opponent`. Negation is supported:

```text
if not shiny party 1
    log "Keep hunting"
end

if not shiny opponent
    log "Keep hunting"
end
```

## Variable conditions

Equality shorthand:

```text
if var mode hunting
    log "Hunting"
end
```

Explicit comparisons:

```text
if var encounters == 100
if var encounters != 100
if var encounters > 100
if var encounters >= 100
if var encounters < 100
if var encounters <= 100
```

Close each block with `end`; `else` is optional.

## Loops

```text
repeat 10
    press A
    delay 500ms
end
```

Infinite loop:

```text
repeat forever
    press A
    delay 1s
end
```

Loop control:

```text
break
continue
```

`break` exits the nearest repeat block. `continue` starts its next iteration.

## Soft reset

```text
restart_game
restart_game 10s
restart_game 10s 30s
```

Arguments are:

1. Settle delay after sending `L+R+START` (default `10s`).
2. Maximum time to wait for the memory backend to return (default `30s`).

With the Ultra-game plugin backend, the old plugin instance disappears during reset, Luma loads a fresh instance with the relaunched game, and the runner waits for the plugin to respond again.

## Stop

```text
stop
```

`Ctrl+C` can also be used as an emergency stop from the runner terminal.


## `restart_game` on Ultra Sun / Ultra Moon

With the 3GX plugin backend, `restart_game` performs a full HOME-menu close and relaunch of the currently selected Ultra game. It does **not** send L+R+START. The sequence is HOME → X → A (confirm Close) → wait for the old plugin to stop → A (relaunch) → wait for the new plugin. This is intentional because USUM soft resets have a known history of destabilizing Luma InputRedirection/networking.


## Input reliability

InputRedirection uses UDP and does not acknowledge individual controller packets. The runner therefore repeats state transitions. A bare `press A` uses a 180 ms pressed state and at least 150 ms of release-state packets. `press A for 250ms` still uses the requested 250 ms pressed duration, followed by the reliable release phase. `hold`, `release`, `release_all`, and HOME-menu restart inputs also retransmit their state transitions.

Empty or invalid PK7 slots are never shiny. In particular, species `0` with PID `0x00000000` and XOR `0` evaluates as `shiny=False`.
