#!/bin/sh
# Build the noarch RPM with plain rpmbuild (no Sailfish SDK needed).
# Usage: tools/build-rpm.sh   -> RPMS/noarch/harbour-twofold-*.rpm
set -e
cd "$(dirname "$0")/.."
SRC=$(pwd)
NAME=harbour-twofold
VERSION=$(sed -n 's/^Version:[[:space:]]*//p' rpm/$NAME.spec | tr -d '\r')
TOP=$(mktemp -d)
trap 'rm -rf "$TOP"' EXIT

mkdir -p "$TOP/SOURCES" "$TOP/SPECS" "$TOP/stage/$NAME-$VERSION"
tar -C "$SRC" --exclude=__pycache__ --exclude=RPMS --exclude=.git --exclude=tests \
    -cf - . | tar -C "$TOP/stage/$NAME-$VERSION" -xf -
tar -C "$TOP/stage" -cjf "$TOP/SOURCES/$NAME-$VERSION.tar.bz2" "$NAME-$VERSION"
tr -d '\r' < rpm/$NAME.spec > "$TOP/SPECS/$NAME.spec"

rpmbuild --define "_topdir $TOP" --define "_rpmdir $SRC/RPMS" -bb "$TOP/SPECS/$NAME.spec"
ls -l "$SRC"/RPMS/noarch/
