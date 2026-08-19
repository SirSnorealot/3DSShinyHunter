#!/usr/bin/env bash
set -u

[[ -f /etc/profile.d/devkit-env.sh ]] && source /etc/profile.d/devkit-env.sh
export DEVKITPRO="${DEVKITPRO:-/opt/devkitpro}"
export DEVKITARM="${DEVKITARM:-$DEVKITPRO/devkitARM}"
export PATH="$DEVKITARM/bin:$DEVKITPRO/tools/bin:$PATH"

fail=0
check_cmd() {
    local name="$1"
    if command -v "$name" >/dev/null 2>&1; then
        printf '[OK]   %-20s %s\n' "$name" "$(command -v "$name")"
    else
        printf '[FAIL] %-20s not found\n' "$name"
        fail=1
    fi
}
check_file() {
    local file="$1"
    if [[ -f "$file" ]]; then
        printf '[OK]   %s\n' "$file"
    else
        printf '[FAIL] %s not found\n' "$file"
        fail=1
    fi
}

printf 'WSL distro: %s\n' "${WSL_DISTRO_NAME:-not-wsl}"
printf 'DEVKITPRO: %s\n' "$DEVKITPRO"
printf 'DEVKITARM: %s\n\n' "$DEVKITARM"

check_cmd dkp-pacman
check_cmd arm-none-eabi-gcc
check_cmd arm-none-eabi-g++
check_cmd 3gxtool
check_file "$DEVKITPRO/libctrpf/lib/libctrpf.a"
check_file "$DEVKITPRO/libctru/lib/libctru.a"

if command -v dkp-pacman >/dev/null 2>&1; then
    printf '\nInstalled packages:\n'
    dkp-pacman -Q libctrpf 2>/dev/null || { echo '[FAIL] libctrpf package missing'; fail=1; }
    dkp-pacman -Q 3gxtool 2>/dev/null || { echo '[FAIL] 3gxtool package missing'; fail=1; }
fi

printf '\n'
if (( fail )); then
    echo '3DS toolchain check FAILED.'
    exit 1
else
    echo '3DS toolchain check PASSED.'
fi


echo
echo "CTRPF header layout:"
for f in \
    "$DEVKITPRO/libctrpf/include/CTRPluginFramework.hpp" \
    "$DEVKITPRO/libctrpf/include/types.h" \
    "$DEVKITPRO/libctrpf/include/CTRPluginFramework/Graphics/Color.hpp"
do
    if [[ -f "$f" ]]; then
        echo "[OK]   $f"
    else
        echo "[MISS] $f"
    fi
done

echo "[INFO] Project fallback header: plugin/ultra_moon/Includes/types.h"
