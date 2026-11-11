#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if [[ "${1-}" == --help ]]; then
    echo 'Diagnóstico local de la raíz LUKS y prueba de la integración instalada por este proyecto.'
    echo 'No modifica LUKS ni objetos persistentes. La salida puede contener metadatos privados.'
    exit 0
fi
[[ $# == 0 && $EUID -eq 0 ]] || { echo 'Ejecuta con sudo y sin argumentos.' >&2; exit 1; }
[[ $(findmnt -n -o FSTYPE /run) == tmpfs ]]
work=$(mktemp -d /run/tpm-luks-diagnostico.XXXXXXXX)
trap 'rm -f -- "$work/deteccion" "$work/liberada"; rmdir -- "$work"' EXIT
python3 "$base/scripts/lib/configuracion.py" detectar > "$work/deteccion"
python3 "$base/scripts/lib/configuracion.py" validar-swap
mapfile -t datos < "$work/deteccion"
printf 'Raíz LUKS detectada: %s\nMapeo: %s\n' "${datos[0]}" "${datos[1]}"
mokutil --sb-state
echo 'Objetos TPM persistentes (identificadores públicos):'
tpm2_getcap -T device:/dev/tpmrm0 handles-persistent
echo 'Política calculada con SHA256/PCR 7 actual:'
tpm2_createpolicy -T device:/dev/tpmrm0 --policy-pcr -g sha256 -l sha256:7 -L /dev/null
actual=${datos[2]-}
if [[ "$actual" != /usr/local/sbin/desbloquear-raiz-tpm || ! -x "$actual" ]]; then
    echo 'La raíz todavía no utiliza la integración de este proyecto.'
    exit 2
fi
echo 'Probando liberación de clave y acceso LUKS; la clave no se muestra:'
if "$actual" --no-fallback > "$work/liberada" && \
    cryptsetup open --type luks --test-passphrase --key-file "$work/liberada" "${datos[0]}"; then
    echo 'Correcto en esta sesión. El arranque debe verificarse por separado.'
else
    echo 'Falló la prueba. Conserva el acceso mediante contraseña y consulta README.md.' >&2
    exit 1
fi
