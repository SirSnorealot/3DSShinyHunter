#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This script must be run inside Ubuntu/WSL." >&2
    exit 1
fi

step() { printf '\n[setup] %s\n' "$*"; }

step "Installing Ubuntu prerequisites..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl wget git make python3 xz-utils bzip2

# Some older devkitPro tooling expects /etc/mtab to resolve to the live mount
# table. Most current Ubuntu/WSL installs already provide this correctly, but
# repair it if it is absent. This mirrors the known-working WSL decomp setup.
if [[ ! -e /etc/mtab ]]; then
    step "Creating WSL /etc/mtab compatibility link..."
    sudo ln -s /proc/self/mounts /etc/mtab
fi

# devkitPro's current Debian/Ubuntu installation method is an apt bootstrap
# script hosted at apt.devkitpro.org. Do not scrape GitHub release assets: the
# current pacman release does not expose the Linux installer as a .deb asset.
if ! command -v dkp-pacman >/dev/null 2>&1; then
    step "Installing devkitPro pacman from the official apt repository..."
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' EXIT

    # apt.devkitpro.org currently returns HTTP 403 to wget's default user
    # agent on some Ubuntu 24.04 / WSL2 systems.  A devkitPro pacman issue
    # documents that using a browser-like UA works, and that the bootstrap
    # script's own wget calls need the same treatment.  WGETRC applies the UA
    # to both this download and every wget spawned by the bootstrap script.
    cat > "$tmpdir/wgetrc" <<'WGETRC'
user_agent = Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36
WGETRC

    export WGETRC="$tmpdir/wgetrc"
    wget -O "$tmpdir/install-devkitpro-pacman" \
        https://apt.devkitpro.org/install-devkitpro-pacman
    chmod +x "$tmpdir/install-devkitpro-pacman"

    # sudo normally resets environment variables, so explicitly pass WGETRC
    # through to the root bootstrap process.
    sudo env WGETRC="$tmpdir/wgetrc" "$tmpdir/install-devkitpro-pacman"
else
    step "devkitPro pacman is already installed: $(command -v dkp-pacman)"
fi

if ! command -v dkp-pacman >/dev/null 2>&1; then
    echo "[setup] ERROR: dkp-pacman is still unavailable after installation." >&2
    exit 1
fi

step "Synchronizing devkitPro package databases..."
sudo dkp-pacman -Sy --noconfirm

step "Installing Nintendo 3DS development toolchain..."
sudo dkp-pacman -S --needed --noconfirm 3ds-dev

# CTRPluginFramework/3gxtool are distributed by ThePixellizerOSS. Their Linux
# instructions add these repositories to devkitPro's own pacman.conf.
conf=/opt/devkitpro/pacman/etc/pacman.conf
if [[ ! -f "$conf" ]]; then
    echo "[setup] ERROR: expected devkitPro pacman config at $conf" >&2
    exit 1
fi

step "Configuring CTRPluginFramework package repositories..."
if ! grep -Fxq '[thepixellizeross-lib]' "$conf"; then
    printf '\n[thepixellizeross-lib]\nServer = https://thepixellizeross.gitlab.io/packages/any\nSigLevel = Optional\n' \
        | sudo tee -a "$conf" >/dev/null
fi
if ! grep -Fxq '[thepixellizeross-linux]' "$conf"; then
    printf '\n[thepixellizeross-linux]\nServer = https://thepixellizeross.gitlab.io/packages/x86_64/linux\nSigLevel = Optional\n' \
        | sudo tee -a "$conf" >/dev/null
fi

step "Synchronizing CTRPluginFramework repositories..."
sudo dkp-pacman -Sy --noconfirm

step "Installing CTRPluginFramework and 3gxtool..."
sudo dkp-pacman -S --needed --noconfirm libctrpf 3gxtool

# devkit-env normally installs /etc/profile.d/devkit-env.sh. Source it when
# available and also provide safe explicit fallbacks for WSL interactive shells.
if [[ -f /etc/profile.d/devkit-env.sh ]]; then
    # shellcheck disable=SC1091
    source /etc/profile.d/devkit-env.sh
fi

export DEVKITPRO="${DEVKITPRO:-/opt/devkitpro}"
export DEVKITARM="${DEVKITARM:-$DEVKITPRO/devkitARM}"
export PATH="$DEVKITARM/bin:$DEVKITPRO/tools/bin:$PATH"

if ! grep -q '# 3DSShinyHunter devkitPro environment' "$HOME/.bashrc"; then
    cat >> "$HOME/.bashrc" <<'BASHRC'

# 3DSShinyHunter devkitPro environment
if [ -f /etc/profile.d/devkit-env.sh ]; then
    . /etc/profile.d/devkit-env.sh
fi
export DEVKITPRO="${DEVKITPRO:-/opt/devkitpro}"
export DEVKITARM="${DEVKITARM:-$DEVKITPRO/devkitARM}"
export PATH="$DEVKITARM/bin:$DEVKITPRO/tools/bin:$PATH"
BASHRC
fi

step "Verifying installation..."
printf 'DEVKITPRO=%s\n' "$DEVKITPRO"
printf 'DEVKITARM=%s\n' "$DEVKITARM"
printf 'dkp-pacman: %s\n' "$(command -v dkp-pacman || echo MISSING)"
printf 'arm-none-eabi-g++: %s\n' "$(command -v arm-none-eabi-g++ || echo MISSING)"
printf '3gxtool: %s\n' "$(command -v 3gxtool || echo MISSING)"

dkp-pacman -Q 3ds-dev 2>/dev/null || true
dkp-pacman -Q libctrpf
dkp-pacman -Q 3gxtool

if [[ ! -x "$DEVKITARM/bin/arm-none-eabi-g++" ]]; then
    echo "[setup] ERROR: devkitARM compiler was not installed correctly." >&2
    exit 1
fi
if ! command -v 3gxtool >/dev/null 2>&1; then
    echo "[setup] ERROR: 3gxtool was not installed correctly." >&2
    exit 1
fi
if [[ ! -f "$DEVKITPRO/libctrpf/lib/libctrpf.a" ]]; then
    echo "[setup] ERROR: libctrpf.a was not found under $DEVKITPRO/libctrpf/lib/." >&2
    exit 1
fi

printf '\n[setup] 3DS WSL toolchain is ready.\n'
printf '[setup] Run: source ~/.bashrc\n'
printf '[setup] Then: ./tools/wsl/check_3ds_env.sh\n'
