#!/usr/bin/env bash
# Publish only to a new local directory. Uses the operator's GPG signing identity.
set -euo pipefail
if (( $# < 3 )) || [[ ! $1 =~ ^[A-F0-9]{40}$ ]]; then
    echo 'Usage: bash scripts/publish-repo.sh PRIMARY_FINGERPRINT NEW_OUTPUT PACKAGE...' >&2
    exit 2
fi
key=$1
output=$2
shift 2
[[ ! -e $output ]] || { echo 'Output already exists; use a new directory.' >&2; exit 1; }
mkdir -p -- "$output"
output=$(realpath -- "$output")
for package in "$@"; do
    [[ $package == *.pkg.tar.zst && -f $package && -f $package.sig ]]
    # VALIDSIG includes the primary fingerprint when a signing subkey is used.
    gpg --batch --status-fd 1 --verify "$package.sig" "$package" \
        | awk -v key="$key" '$2 == "VALIDSIG" && ($3 == key || $NF == key) {ok=1} END {exit !ok}'
    [[ ! -e $output/$(basename -- "$package") ]]
    cp -- "$package" "$package.sig" "$output/"
done
gpg --batch --armor --export "$key" > "$output/repository-key.asc"
[[ -s $output/repository-key.asc ]]
repo-add --sign --key "$key" --include-sigs "$output/distro.db.tar.gz" "$output/"*.pkg.tar.zst
(
    cd -- "$output"
    sha256sum -- *.pkg.tar.zst *.pkg.tar.zst.sig distro.db.tar.gz distro.db.tar.gz.sig repository-key.asc > SHA256SUMS
)
echo "Signed local repository: $output"
