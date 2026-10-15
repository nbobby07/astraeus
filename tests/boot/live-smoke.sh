#!/usr/bin/env bash
# Read-only acceptance evidence from inside the live guest, also kept in its journal.
set -euo pipefail
[[ -d /sys/firmware/efi ]]
[[ $(uname -m) == x86_64 ]]
distroctl info --json
systemctl is-active --quiet NetworkManager.service
systemctl is-active --quiet live-keyring.service
# The final live filesystem must support public repository queries after ArchISO cleanup.
runuser -u live -- distroctl system packages installed --json |
    python3 -c 'import json,sys
v=json.load(sys.stdin)
assert v["schema_version"] == 1 and any(p["name"] == "distroctl" for p in v["packages"])'
for query in search details; do
    runuser -u live -- distroctl system packages "$query" kcalc --json |
        python3 -c 'import json,sys
v=json.load(sys.stdin)
assert v["schema_version"] == 1 and any(p["name"] == "kcalc" for p in v["packages"])'
done
printf '%s\n' '{"schema_version":1,"packages":["kcalc"],"gaming":[],"providers":{}}' |
    runuser -u live -- distroctl system plan --stdin --json |
    python3 -c 'import json,re,sys
v=json.load(sys.stdin)
assert v["schema_version"] == 1 and v["executable"] is False
assert re.fullmatch("sha256:[0-9a-f]{64}",v["plan_id"])
assert v["plan"]["management"]["after"]["applied"] == {"schema_version":1,"packages":["kcalc"],"gaming":[],"providers":{}}
assert any(p["name"] == "kcalc" and p["kind"] == "install" for p in v["plan"]["packages"]["changes"])
assert len(v["blockers"]) == 1 and "live sessions" in v["blockers"][0].lower()'
echo 'DISTRO_LIVE_MANAGEMENT_OK: ordinary-user installed search details resolved-plan apply-blocked'
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
