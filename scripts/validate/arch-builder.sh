#!/usr/bin/env bash
# Run only in a new disposable Arch guest with the phase0 9p share mounted.
set -Eeuo pipefail
[[ ${PHASE0_DISPOSABLE:-} == 1 && $EUID == 0 && -f /etc/arch-release ]]
label=${1:?Usage: PHASE0_DISPOSABLE=1 bash arch-builder.sh A-or-B}
[[ $label == A || $label == B ]]
share=/mnt/phase0
evidence="$share/evidence/$label"
mkdir -p "$evidence"
exec > >(tee "$evidence/build.log") 2>&1
trap 'result=$?; date -u +%FT%TZ > "$evidence/ended.txt"; printf "%s\n" "$result" > "$evidence/exit-code"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
date -u +%FT%TZ > "$evidence/started.txt"
[[ ! -e /build/operating-system ]]
mkdir -p /build
sha256sum "$share/source.tar.xz" | tee "$evidence/source-sha256.txt"
sha256sum "$0" > "$evidence/builder-script-sha256.txt"
tar -xJf "$share/source.tar.xz" -C /build
cd /build/operating-system
archive=$(python3 -c 'import tomllib; print(tomllib.load(open("distro/branding/project.toml","rb"))["build"]["archive_date"])')
python3 scripts/bootstrap.py verify-archive --output /build/archive
cat > /etc/pacman.conf <<EOF
[options]
Architecture = x86_64
CheckSpace
XferCommand = /usr/bin/curl -fL --retry 3 --retry-all-errors --connect-timeout 20 --max-time 300 -o %o %u
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Required
[core]
CacheServer = https://archive.archlinux.org/repos/$archive/\$repo/os/\$arch
Server = file:///build/archive
[extra]
CacheServer = https://archive.archlinux.org/repos/$archive/\$repo/os/\$arch
Server = file:///build/archive
EOF
pacman-key --init
pacman-key --populate archlinux
if [[ -d $share/package-cache ]]; then
    # Reuse only immutable upstream archives; pacman still verifies their signatures.
    cp -a "$share/package-cache/." /var/cache/pacman/pkg/
fi
pacman -Syyuu --noconfirm --needed base-devel archiso rust python git gnupg systemd-ukify sbsigntools efitools
pacman -S --noconfirm --needed $(cat distro/packages/calamares/build-packages.x86_64)
git init -b main
git status --short > "$evidence/git-status.txt"
git rev-parse HEAD > "$evidence/git-head.txt" 2>&1 || true
uname -a > "$evidence/kernel.txt"
cat /etc/os-release > "$evidence/os-release.txt"
cp /etc/pacman.conf "$evidence/pacman.conf"
pacman -Q > "$evidence/packages-before-build.txt"
python3 scripts/bootstrap.py verify-archive
useradd --create-home --shell /bin/bash builder
chown -R builder:builder /build/operating-system
epoch=$(python3 -c 'import tomllib; print(tomllib.load(open("distro/branding/project.toml","rb"))["build"]["source_date_epoch"])')
runuser -u builder -- env SOURCE_DATE_EPOCH="$epoch" PACKAGER='Distribution developers' \
    bash -c 'python3 scripts/bootstrap.py package --output .build/package && cd .build/package && makepkg --config /etc/makepkg.conf --cleanbuild --noconfirm'
runuser -u builder -- env SOURCE_DATE_EPOCH="$epoch" PACKAGER='Distribution developers' \
    bash -c 'cd .build/package/calamares && makepkg --config /etc/makepkg.conf --cleanbuild --noconfirm'
cp .build/package/calamares/*.pkg.tar.zst .build/package/
sha256sum .build/package/*.pkg.tar.zst > "$evidence/platform-package-sha256.txt"
if [[ $label == A ]]; then
    [[ ! -e $share/repo ]]
    runuser -u builder -- gpg --batch --pinentry-mode loopback --passphrase '' \
        --quick-generate-key 'Phase 0 disposable package signing' ed25519 sign 1d
    key=$(runuser -u builder -- gpg --batch --with-colons --list-keys | awk -F: '$1 == "fpr" {print $10; exit}')
    for package in /build/operating-system/.build/package/*.pkg.tar.zst; do
        runuser -u builder -- gpg --batch --local-user "$key" --detach-sign "$package"
    done
    runuser -u builder -- bash scripts/publish-repo.sh "$key" out/repo .build/package/*.pkg.tar.zst
    cp -a out/repo "$share/repo"
    printf '%s\n' "$key" > "$share/repository-fingerprint.txt"
else
    mkdir -p out
    cp -a "$share/repo" out/repo
fi
key=$(cat "$share/repository-fingerprint.txt")
# Both independent images consume identical signed repository bytes.
repo=/build/operating-system/out/repo
printf '%s\n' "python3 scripts/bootstrap.py iso --repo $repo --fingerprint $key --output /build/iso-build" > "$evidence/command.txt"
python3 scripts/bootstrap.py iso --repo "$repo" --fingerprint "$key" --output /build/iso-build
cp /build/iso-build/{builder-packages.txt,image-packages.txt,inputs.json} "$evidence/"
cp /build/iso-build/installed-packages.txt "$evidence/"
cp /build/iso-build/iso/* "$evidence/"
stat -c '%n %s bytes' "$evidence/"*.iso | tee "$evidence/iso-size.txt"
echo "BUILDER_${label}_SUCCESS"
