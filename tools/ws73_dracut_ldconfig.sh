#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# DRACUT_LDCONFIG helper: keep dracut as the ordinary user. Only its private
# initramfs cache operation needs chroot inside an unprivileged user namespace.
set -eu
if [ "$#" = 1 ] && [ "$1" = -pN ]; then
    exec /usr/sbin/ldconfig -pN
fi
if [ "$#" != 4 ] || [ "$1" != -r ] || [ "$3" != -f ] || [ "$4" != /etc/ld.so.conf ]; then
    echo 'Unsupported dracut ldconfig arguments' >&2
    exit 2
fi
case "$2" in
    /*) ;;
    *) echo 'Absolute private initramfs directory required' >&2; exit 2 ;;
esac
[ -d "$2" ] && [ -f "$2/etc/ld.so.conf" ] || exit 2
exec /usr/bin/unshare --user --map-root-user -- /usr/sbin/ldconfig "$@"
