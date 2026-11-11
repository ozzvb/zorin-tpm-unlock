#!/bin/sh
set -e
case "${1-}" in
    prereqs) echo ''; exit 0 ;;
esac
. /usr/share/initramfs-tools/hook-functions
copy_exec /usr/bin/tpm2-initramfs-tool
copy_exec /lib/cryptsetup/askpass
lib=$(ldconfig -p | awk '$1 == "libtss2-tcti-device.so.0" { print $NF; exit }')
[ -n "$lib" ] && [ -r "$lib" ]
copy_exec "$lib"
copy_exec /usr/local/sbin/desbloquear-raiz-tpm
# Si están integrados en el kernel no hace falta copiarlos.
manual_add_modules tpm_crb tpm_tis
