#!/bin/sh
# Install the pinned Trivy into the project (docs/DECISIONS.md §90).
#
# `make image` is a gate only while everyone runs the same scanner, so the
# version and each platform's archive digest are pinned here, taken from the
# release's published trivy_<version>_checksums.txt. An archive whose digest
# differs is refused before anything is extracted.
#
# Usage: install_trivy.sh <version> <dest-dir>
# TRIVY_BASE_URL overrides the release location (the suite points it at a
# local archive to prove the refusal).
set -eu

version=$1
dest=$2

[ "$version" = "0.70.0" ] || { echo "no pinned digests for Trivy $version" >&2; exit 1; }

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) asset=macOS-ARM64 digest=68e543c51dcc96e1c344053a4fde9660cf602c25565d9f09dc17dd41e13b838a ;;
  Darwin-x86_64) asset=macOS-64bit digest=52d531452b19e7593da29366007d02a810e1e0080d02f9cf6a1afb46c35aaa93 ;;
  Linux-x86_64) asset=Linux-64bit digest=8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9 ;;
  Linux-aarch64 | Linux-arm64) asset=Linux-ARM64 digest=2f6bb988b553a1bbac6bdd1ce890f5e412439564e17522b88a4541b4f364fc8d ;;
  *) echo "no pinned Trivy archive for $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

base=${TRIVY_BASE_URL:-https://github.com/aquasecurity/trivy/releases/download/v$version}
archive="trivy_${version}_${asset}.tar.gz"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl -fsSL -o "$work/$archive" "$base/$archive"
actual=$(shasum -a 256 "$work/$archive" | cut -d' ' -f1)
if [ "$actual" != "$digest" ]; then
  echo "Trivy archive digest $actual is not the pinned $digest; refusing it" >&2
  exit 1
fi

tar -xzf "$work/$archive" -C "$work" trivy
mkdir -p "$dest"
mv "$work/trivy" "$dest/trivy"
"$dest/trivy" --version | sed -n 1p
