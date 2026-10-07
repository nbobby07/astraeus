#!/usr/bin/env bash
# Copy to a private fixture directory. Complete the two finalization hooks after integration.
# The host invokes this only INSIDE its disposable guest, never on the host.
set -euo pipefail
[[ $EUID == 0 && -e /dev/virtio-ports/org.astraeus.validation && $(systemd-detect-virt) == kvm ]]
guest=/mnt/astraeus-validation/phase2-guest.py
state=/var/lib/astraeus-validation
case "${1:?action required}" in
    prepare)
        [[ $(pacman -Q astraeus-validation-fixture) == 'astraeus-validation-fixture 1-1' ]]
        distroctl update --dry-run --json | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert any(c.get("name")=="astraeus-validation-fixture" and c.get("to")=="2-1" for c in p["packages"]["changes"]), "missing signed fixture upgrade"
'
        ;;
    update)
        distroctl update 2>&1 | tee /var/log/astraeus-validation-update.log
        ;;
    arm)
        fault=${2:?fault required}
        rm -f /var/log/astraeus-validation-fault
        if [[ $fault == payload || $fault == space ]]; then
            python3 "$guest" fault "$fault"
            exit
        fi
        case "$fault" in package|health|service|interruption) ;; *) exit 2 ;; esac
        mkdir -p /etc/pacman.d/hooks
        if [[ $fault == package ]]; then
            python3 "$guest" fault package
            exit
        fi
        if [[ $fault == interruption ]]; then
            rm -f /var/log/astraeus-validation-barrier
            printf '%s\n' '#!/bin/bash' 'set -eu' 'touch /var/log/astraeus-validation-barrier' 'sync' 'sleep 3600' > "$state/inject.sh"
            when=PreTransaction
        else
            printf '%s\n' '#!/bin/bash' 'set -eu' "python3 $guest fault $fault" > "$state/inject.sh"
            when=PostTransaction
        fi
        cat > /etc/pacman.d/hooks/00-astraeus-validation.hook <<EOF
[Trigger]
Operation = Upgrade
Type = Package
Target = astraeus-validation-fixture
[Action]
Description = Disposable validation fault
When = $when
Exec = /bin/bash $state/inject.sh
EOF
        ;;
    reconcile)
        # Native updater recovers durable intent under its lock; expected to refuse another update.
        if distroctl update; then
            echo 'Interrupted update unexpectedly allowed a successful update' >&2
            exit 1
        fi
        ;;
    recover)
        [[ -d /run/archiso && -e /dev/virtio-ports/org.astraeus.validation ]]
        target=${2:?snapshot required}
        root=/dev/vda2
        if cryptsetup isLuks --type luks2 "$root"; then
            # Operator unlocks interactively; credentials never enter the command channel.
            [[ -b /dev/mapper/root ]]
            root=/dev/mapper/root
        fi
        mkdir -p /mnt/astraeus /mnt/astraeus-esp
        mount -t btrfs -o subvolid=5 "$root" /mnt/astraeus
        trap 'code=$?; umount /mnt/astraeus-esp || code=1; umount /mnt/astraeus || code=1; exit "$code"' EXIT
        mount -t vfat /dev/vda1 /mnt/astraeus-esp
        distroctl rollback "$target" --dry-run --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
        distroctl rollback "$target" --execute --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
        ;;
    confirm-boot|finalize-rollback)
        printf 'Missing product integration: %s\n' "$1" >&2
        exit 77
        ;;
    *) printf 'Unknown validation action: %s\n' "$1" >&2; exit 2 ;;
esac
