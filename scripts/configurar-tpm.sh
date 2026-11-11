#!/usr/bin/env bash
# Configuración y renovación con contraseña manual como vía de recuperación.
set -Eeuo pipefail
set +x
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
helper="$base/scripts/lib/configuracion.py"
renovar=0
case "${1-}" in
    '') ;;
    --renovar) renovar=1 ;;
    --help)
        printf '%s\n' 'Configura el desbloqueo TPM de la raíz LUKS2 detectada.' \
            'Sin opciones: conserva una configuración de este proyecto si funciona.' \
            '--renovar: crea una vinculación nueva incluso si la actual funciona.' \
            'Requiere sudo y una terminal interactiva. Consulta README.md.'
        exit 0 ;;
    *) echo 'Opción desconocida. Consulta --help.' >&2; exit 1 ;;
esac
[[ $# -le 1 ]] || exit 1
[[ $EUID -eq 0 && -t 0 ]] || { echo 'Ejecuta con sudo desde una terminal.' >&2; exit 1; }
for tool in cryptsetup tpm2-initramfs-tool tpm2_getcap python3 update-initramfs findmnt lsblk swapon mokutil flock ldconfig cmp install; do
    command -v "$tool" >/dev/null || { echo "Falta la dependencia: $tool" >&2; exit 1; }
done
exec 9>/run/tpm-luks-zorin.lock
flock -n 9 || { echo 'Ya hay otra ejecución del proyecto.' >&2; exit 1; }
[[ -c /dev/tpmrm0 ]] || { echo 'No existe el dispositivo TPM2 requerido.' >&2; exit 1; }
[[ $(findmnt -n -o FSTYPE /run) == tmpfs ]] || { echo '/run debe estar en tmpfs.' >&2; exit 1; }
mokutil --sb-state | grep -q '^SecureBoot enabled$' || { echo 'Se requiere Secure Boot activado.' >&2; exit 1; }
[[ -f /usr/share/initramfs-tools/hooks/cryptroot && -x /lib/cryptsetup/askpass ]]
ldconfig -p | grep 'libtss2-tcti-device.so.0' >/dev/null

targets=(/etc/crypttab /usr/local/sbin/desbloquear-raiz-tpm /etc/initramfs-tools/hooks/desbloquear-raiz-tpm /etc/tpm-luks-zorin/estado.json)
for target in "${targets[@]}"; do
    [[ ! -L "$target" ]] || { echo "Se rechaza un destino con enlace simbólico: $target" >&2; exit 1; }
done
work=$(mktemp -d /run/tpm-luks-zorin.XXXXXXXX)
backup=
changed=0
attempted=0
finished=0
cleanup() {
    local status=$? i
    trap - EXIT INT TERM
    if (( ! finished )); then
        echo "Se detuvo la operación (código $status)." >&2
        if (( changed )); then
            local restored=1
            for i in "${!targets[@]}"; do
                if [[ -f "$backup/$i.ausente" ]]; then
                    rm -f -- "${targets[$i]}" || restored=0
                else
                    cp -p -- "$backup/$i.original" "${targets[$i]}" || restored=0
                fi
            done
            if (( restored )); then
                echo 'Archivos anteriores restaurados; regenerando initramfs...' >&2
                update-initramfs -u -k all || echo 'FALLO la regeneración: no reinicies; revisa el error.' >&2
            else
                echo 'FALLO la restauración: no reinicies; revisa el respaldo.' >&2
            fi
        fi
        echo 'Las ranuras y objetos anteriores se conservan.' >&2
        if (( attempted )); then
            echo 'Puede quedar un objeto o una ranura nuevos sin usar. Revisa antes de repetir.' >&2
        fi
    fi
    rm -f -- "$work/clave" "$work/liberada" "$work/deteccion" "$work/crypttab" "$work/keyscript" "$work/estado.json"
    rmdir -- "$work"
    [[ -z "$backup" ]] || printf 'Respaldo privado: %s\n' "$backup"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

python3 "$helper" detectar > "$work/deteccion"
python3 "$helper" validar-swap
mapfile -t datos < "$work/deteccion"
device=${datos[0]}
nombre=${datos[1]}
actual=${datos[2]-}
printf 'Se configurará únicamente la raíz cifrada: %s (%s).\n' "$device" "$nombre"
if (( ! renovar )) && [[ "$actual" == "${targets[1]}" && -x "$actual" ]]; then
    if "$actual" --no-fallback > "$work/liberada" && \
        cryptsetup open --type luks --test-passphrase --key-file "$work/liberada" "$device"; then
        echo 'La configuración del proyecto ya funciona en esta sesión. No se ha modificado.'
        finished=1
        exit 0
    fi
fi

slot=$(python3 "$helper" ranura "$device")
handle=$(python3 "$helper" objeto)
printf 'Se usarán una ranura libre (%s) y un objeto TPM libre (%s).\n' "$slot" "$handle"
echo 'Introduce la contraseña de DESCIFRADO para comprobar que el acceso manual funciona.'
cryptsetup open --type luks --test-passphrase "$device"

[[ ! -L /root/tpm-luks-respaldos && ! -L /etc/tpm-luks-zorin ]]
install -d -o root -g root -m 0700 /root/tpm-luks-respaldos
backup=$(mktemp -d /root/tpm-luks-respaldos/operacion.XXXXXXXX)
for i in "${!targets[@]}"; do
    if [[ -e "${targets[$i]}" ]]; then
        cp -p -- "${targets[$i]}" "$backup/$i.original"
    else
        touch "$backup/$i.ausente"
    fi
done
printf '%s\n' "${targets[@]}" > "$backup/destinos.txt"
cryptsetup luksHeaderBackup "$device" --header-backup-file "$backup/cabecera-luks.img"
python3 "$helper" estado "$backup/operacion.json" "$handle" "$slot"

# Revalidación: seal puede reemplazar un objeto ocupado. No se permite hacerlo.
[[ $(python3 "$helper" objeto) == "$handle" ]] || { echo 'Cambió la ocupación del TPM.' >&2; exit 1; }
[[ $(python3 "$helper" ranura "$device") == "$slot" ]] || { echo 'Cambió la ocupación de LUKS.' >&2; exit 1; }
attempted=1
tpm2-initramfs-tool seal --persistent "$handle" --pcrs 7 --banks SHA256 \
    --tcti device:/dev/tpmrm0 > "$work/clave"
[[ -s "$work/clave" ]]
tpm2-initramfs-tool unseal --persistent "$handle" --pcrs 7 --banks SHA256 \
    --tcti device:/dev/tpmrm0 > "$work/liberada"
cmp -s "$work/clave" "$work/liberada"
echo 'Introduce de nuevo la contraseña de DESCIFRADO para autorizar la ranura nueva.'
cryptsetup luksAddKey --new-key-slot "$slot" "$device" "$work/clave"
cryptsetup open --type luks --test-passphrase --key-slot "$slot" --key-file "$work/liberada" "$device"

python3 "$helper" crypttab /etc/crypttab "$nombre" "$work/crypttab"
sed "s/@OBJETO_TPM@/$handle/g" "$base/plantillas/desbloquear-raiz-tpm.sh.in" > "$work/keyscript"
sh -n "$work/keyscript"
python3 "$helper" estado "$work/estado.json" "$handle" "$slot"
changed=1
install -d -o root -g root -m 0700 /etc/tpm-luks-zorin
install -o root -g root -m 0755 "$work/keyscript" "${targets[1]}"
install -o root -g root -m 0755 "$base/plantillas/hook-tpm-initramfs.sh" "${targets[2]}"
install -o root -g root -m 0600 "$work/crypttab" "${targets[0]}"
install -o root -g root -m 0600 "$work/estado.json" "${targets[3]}"
"${targets[1]}" --no-fallback > "$work/liberada"
cryptsetup open --type luks --test-passphrase --key-slot "$slot" --key-file "$work/liberada" "$device"
update-initramfs -u -k all
finished=1
echo 'Configuración aplicada. La clave TPM desbloquea LUKS en esta sesión.'
echo 'Queda comprobar un reinicio manual. Si se pide contraseña, usa la habitual.'
echo 'Tras arrancar correctamente, conserva el respaldo en almacenamiento privado externo.'
