#!/usr/bin/env bash
# Read-only acceptance evidence from inside the live guest, also kept in its journal.
set -euo pipefail
[[ -d /sys/firmware/efi ]]
[[ $(uname -m) == x86_64 ]]
distroctl info --json
systemctl is-active --quiet NetworkManager.service
systemctl is-active --quiet live-keyring.service
for ((attempt = 0; attempt < 120; attempt++)); do
    for session in $(loginctl show-user live --property=Sessions --value 2>/dev/null); do
        if [[ $(loginctl show-session "$session" --property=Type --value) == wayland &&
              $(loginctl show-session "$session" --property=Class --value) == user &&
              $(loginctl show-session "$session" --property=Active --value) == yes ]] &&
           pgrep -u live -x plasmashell >/dev/null &&
           [[ -S /run/user/1000/pipewire-0 && -S /run/user/1000/pulse/native ]]; then
            echo 'DISTRO_BOOT_OK: uefi plasma wayland pipewire networkmanager distroctl'
            exit 0
        fi
    done
    sleep 2
done
echo 'DISTRO_BOOT_FAILED: live Wayland desktop/audio did not become ready' >&2
exit 1
