#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ -f /etc/profile.d/devkit-env.sh ]]; then
    # shellcheck disable=SC1091
    source /etc/profile.d/devkit-env.sh
fi

: "${DEVKITPRO:?DEVKITPRO is not set. Run tools/wsl/setup_3ds.sh first.}"
: "${DEVKITARM:?DEVKITARM is not set. Run tools/wsl/setup_3ds.sh first.}"
command -v 3gxtool >/dev/null || { echo '[ERROR] 3gxtool not found' >&2; exit 1; }
[[ -f "$DEVKITPRO/libctrpf/lib/libctrpf.a" ]] || { echo "[ERROR] $DEVKITPRO/libctrpf/lib/libctrpf.a not found" >&2; exit 1; }
[[ -f "$DEVKITPRO/libctru/lib/libctru.a" ]] || { echo "[ERROR] $DEVKITPRO/libctru/lib/libctru.a not found" >&2; exit 1; }

# plugin_id|output filename
PLUGINS=(
    "ultra_sun|3DSShinyHunter-UltraSun.3gx"
    "ultra_moon|3DSShinyHunter-UltraMoon.3gx"
)

build_one() {
    local plugin_id="$1"
    local target="$2"
    local plugin="$ROOT/plugin/$plugin_id"

    [[ -d "$plugin" ]] || { echo "[ERROR] Missing plugin directory: $plugin" >&2; return 1; }
    [[ -f "$plugin/Includes/types.h" ]] || { echo "[ERROR] $plugin/Includes/types.h is missing" >&2; return 1; }

    local build_root staged
    build_root="$(mktemp -d -t "3dsshinyhunter-${plugin_id}.XXXXXX")"
    staged="$build_root/$plugin_id"
    mkdir -p "$staged"

    # Build on native Linux storage to avoid /mnt/c 9p clock skew and timestamp races.
    cp -R "$plugin/." "$staged/"
    find "$staged" -type f -exec touch {} +
    rm -rf "$staged/Build" "$staged"/*.elf "$staged"/*.3gx

    printf '\n[build] %-12s %s\n' 'Plugin:' "$plugin_id"
    printf '[build] %-12s %s\n' 'Source:' "$plugin"
    printf '[build] %-12s %s\n' 'Staging:' "$staged"

    (
        cd "$staged"
        make clean
        make -j1
    )

    if [[ ! -f "$staged/$target" ]]; then
        echo "[ERROR] Build completed without producing $target" >&2
        rm -rf "$build_root"
        return 1
    fi

    cp -f "$staged/$target" "$plugin/$target"
    touch "$plugin/$target"
    rm -rf "$build_root"
    printf '[build] Built: %s\n' "$plugin/$target"
}

printf '[build] Project:    %s\n' "$ROOT"
printf '[build] Source FS:  %s\n' "$(df -T "$ROOT" | tail -1 | awk '{print $2}')"
printf '[build] libctrpf:   %s\n' "$DEVKITPRO/libctrpf"
printf '[build] devkitARM:  %s\n' "$DEVKITARM"

for entry in "${PLUGINS[@]}"; do
    IFS='|' read -r plugin_id target <<< "$entry"
    build_one "$plugin_id" "$target"
done

printf '\n[build] All plugins built successfully.\n'
