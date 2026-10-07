#!/usr/bin/env bash
# Run as the installed desktop user. Usage: bash installed-smoke.sh none|LUKS2
set -euo pipefail
expected=${1:?Specify none or LUKS2}
[[ $expected == none || $expected == LUKS2 ]]
[[ $EUID != 0 && $XDG_SESSION_TYPE == wayland && $XDG_CURRENT_DESKTOP == *KDE* ]]
[[ -d /sys/firmware/efi ]]
out=$(mktemp -d "$HOME/installation-evidence.XXXXXX")
exec > >(tee "$out/health.log") 2>&1
date -u +%FT%TZ
uname -a
distroctl status | tee "$out/status.txt"
distroctl status --json > "$out/status.json"
python3 - "$out/status.json" "$expected" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
assert s['filesystem']['root_type']=='btrfs',s
assert s['filesystem']['encryption']==sys.argv[2],s
assert s['boot']['firmware']=='UEFI',s
assert s['boot']['bootloader'].startswith('systemd-boot'),s
assert s['boot']['stub'].startswith('systemd-stub'),s
assert '/EFI/Linux/' in s['boot']['uki_path'].replace('\\','/'),s
assert s['desktop']['session_type']=='wayland',s
PY
systemctl is-active NetworkManager.service sddm.service
nmcli general
getent hosts archive.archlinux.org
curl --fail --location --connect-timeout 20 --max-time 60 --output /dev/null https://archive.archlinux.org/
systemctl --user is-active pipewire.service pipewire-pulse.service wireplumber.service
pgrep -u "$USER" -x plasmashell
command -v ghostty konsole
systemctl --failed --no-legend --plain | tee "$out/failed-system.txt"
systemctl --user --failed --no-legend --plain | tee "$out/failed-user.txt"
[[ ! -s $out/failed-system.txt && ! -s $out/failed-user.txt ]]
findmnt --real | tee "$out/mounts.txt"
cat /etc/fstab | tee "$out/fstab.txt"
echo "DISTRO_INSTALL_OK: uefi uki $expected btrfs sddm plasma wayland network audio status"
echo "Evidence: $out"
