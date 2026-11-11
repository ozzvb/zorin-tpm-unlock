#!/usr/bin/env python3
"""Primera configuración de datos LUKS2 existentes; genera fragmentos privados para revisar."""
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from configuracion import detectar, ranura_libre

PENDIENTE = Path("/root/tpm-datos-pendiente")


def consulta(*args):
    return subprocess.check_output(args, text=True).strip()


def orden(*args):
    subprocess.run(args, check=True)


def escape_fstab(texto):
    return texto.replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011").replace("#", "\\043")


def main():
    if sys.argv[1:] == ["--help"]:
        print(__doc__)
        print("Solicita los discos y el destino. Añade claves sin borrar las anteriores.")
        print("No formatea ni monta. No edita crypttab o fstab; genera fragmentos privados.")
        return
    if sys.argv[1:] or os.geteuid() != 0 or not sys.stdin.isatty():
        raise ValueError("Ejecuta con sudo, sin argumentos y desde una terminal.")
    os.umask(0o077)
    for herramienta in ("cryptsetup", "lsblk", "blkid", "findmnt"):
        if shutil.which(herramienta) is None:
            raise ValueError(f"Falta la dependencia: {herramienta}")
    with open("/run/tpm-luks-zorin.lock", "w") as bloqueo:
        fcntl.flock(bloqueo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preparar()


def preparar():
    raiz, _, _ = detectar()
    if PENDIENTE.exists() or PENDIENTE.is_symlink():
        raise ValueError("Ya existe una preparación privada pendiente. Revísala antes de repetir.")
    print("Esta operación añade claves a discos de datos YA cifrados y con sistema de archivos.")
    print("Los miembros de un mismo Btrfs se preparan juntos; los sistemas independientes, por separado.")
    orden("lsblk", "-p", "-o", "NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS")
    cantidad = int(input("Número de particiones LUKS que forman este sistema de archivos: "))
    if not 1 <= cantidad <= 16:
        raise ValueError("Cantidad fuera del alcance de este asistente.")
    crypttab = Path("/etc/crypttab").read_text()
    destinos = consulta("findmnt", "--fstab", "--json", "--list", "-o", "TARGET")
    registrados = {fila["target"] for fila in json.loads(destinos).get("filesystems", [])}
    discos = []
    for numero in range(cantidad):
        ruta = Path(input(f"Ruta absoluta de la partición LUKS {numero + 1}: ").strip())
        if not ruta.is_absolute() or not ruta.is_block_device():
            raise ValueError("Se requiere una ruta absoluta a un dispositivo de bloques.")
        ruta = ruta.resolve()
        if str(ruta) == raiz or any(d["dispositivo"] == str(ruta) for d in discos):
            raise ValueError("No se admite la raíz ni repetir un dispositivo.")
        arbol = json.loads(consulta("lsblk", "--json", "-p", "-o", "NAME,TYPE,MOUNTPOINTS", str(ruta)))

        def en_uso(nodos):
            return any(n.get("type") == "crypt" or any(n.get("mountpoints") or []) or en_uso(n.get("children", [])) for n in nodos)

        if en_uso(arbol["blockdevices"]):
            raise ValueError("El disco está abierto o montado. No se preparará por duplicado.")
        uuid = consulta("cryptsetup", "luksUUID", str(ruta))
        if not re.fullmatch(r"[0-9a-fA-F-]+", uuid):
            raise ValueError("Identificador LUKS no reconocido.")
        for linea in crypttab.splitlines():
            campos = linea.split("#", 1)[0].split()
            if len(campos) >= 2:
                fuente = campos[1]
                if fuente.lower() == f"UUID={uuid}".lower() or (fuente.startswith("/") and os.path.realpath(fuente) == str(ruta)):
                    raise ValueError("El disco ya está registrado en crypttab; utiliza la revisión de datos.")
        metadata = json.loads(consulta("cryptsetup", "luksDump", "--dump-json-metadata", str(ruta)))
        nombre = "datos_" + uuid.replace("-", "").lower()
        clave = Path("/etc/cryptsetup-keys.d") / (nombre + ".key")
        if os.path.lexists(clave) or os.path.lexists("/dev/mapper/" + nombre):
            raise ValueError("El nombre local generado ya está en uso; revisar antes de continuar.")
        discos.append({"dispositivo": str(ruta), "uuid": uuid, "nombre": nombre,
                       "clave": str(clave), "ranura": ranura_libre(metadata)})
    destino = Path(input("Ruta absoluta del directorio donde montar los datos: ").strip())
    if not destino.is_absolute() or str(destino) == "/" or destino.is_symlink():
        raise ValueError("Destino de montaje no admitido.")
    destino = destino.resolve()
    if str(destino) in registrados or os.path.ismount(destino):
        raise ValueError("El destino ya está registrado o montado.")
    if any(destino == Path(p) or Path(p) in destino.parents for p in ("/etc", "/usr", "/boot", "/dev", "/proc", "/sys", "/run", "/root")):
        raise ValueError("El destino está dentro de un directorio reservado del sistema.")
    if destino.exists() and (not destino.is_dir() or any(destino.iterdir())):
        raise ValueError("El destino debe ser un directorio vacío.")
    print("Se añadirán claves nuevas a las particiones indicadas; se conservarán las anteriores.")
    if input("Para continuar escribe CONFIGURAR: ").strip() != "CONFIGURAR":
        raise ValueError("Operación cancelada.")
    for disco in discos:
        print("Comprueba la contraseña de DESCIFRADO de:", disco["dispositivo"])
        orden("cryptsetup", "open", "--type", "luks", "--test-passphrase", disco["dispositivo"])

    # A partir de aquí puede quedar una preparación parcial. No borrar claves al fallar.
    PENDIENTE.mkdir(mode=0o700)
    (PENDIENTE / "estado.json").write_text(json.dumps({"discos": discos, "destino": str(destino)}, indent=2) + "\n")
    shutil.copy2("/etc/crypttab", PENDIENTE / "crypttab.original")
    shutil.copy2("/etc/fstab", PENDIENTE / "fstab.original")
    directorio_claves = Path("/etc/cryptsetup-keys.d")
    if directorio_claves.is_symlink():
        raise ValueError("El directorio de claves no puede ser un enlace simbólico.")
    if directorio_claves.exists():
        atributos = directorio_claves.stat()
        if atributos.st_uid != 0 or atributos.st_mode & 0o077:
            raise ValueError("El directorio de claves existente requiere propietario root y permisos privados.")
    else:
        directorio_claves.mkdir(mode=0o700)
    tipos = []
    ids_fs = []
    for disco in discos:
        orden("cryptsetup", "luksHeaderBackup", disco["dispositivo"], "--header-backup-file", str(PENDIENTE / (disco["nombre"] + ".img")))
        fd = os.open(disco["clave"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as archivo:
            archivo.write(secrets.token_bytes(64))
        print("Autoriza la ranura nueva con la contraseña de:", disco["dispositivo"])
        orden("cryptsetup", "luksAddKey", "--new-key-slot", str(disco["ranura"]), disco["dispositivo"], disco["clave"])
        orden("cryptsetup", "open", "--type", "luks", "--test-passphrase", "--key-slot", str(disco["ranura"]), "--key-file", disco["clave"], disco["dispositivo"])
        orden("cryptsetup", "open", "--type", "luks", "--key-file", disco["clave"], disco["dispositivo"], disco["nombre"])
        mapper = "/dev/mapper/" + disco["nombre"]
        tipos.append(consulta("blkid", "-s", "TYPE", "-o", "value", mapper))
        ids_fs.append(consulta("blkid", "-s", "UUID", "-o", "value", mapper))
    if len(set(tipos)) != 1 or tipos[0] not in {"btrfs", "ext4", "xfs"}:
        raise ValueError("Los dispositivos no contienen un sistema de archivos compatible único.")
    if cantidad > 1 and (tipos[0] != "btrfs" or len(set(ids_fs)) != 1):
        raise ValueError("Varios miembros solo se admiten para el mismo sistema Btrfs.")
    opciones = ["defaults", "nofail", "noatime", "x-systemd.device-timeout=120s"]
    if tipos[0] == "btrfs":
        subvolumen = input("Subvolumen Btrfs existente que deseas montar; vacío usa el predeterminado: ").strip()
        if subvolumen:
            if any(c.isspace() for c in subvolumen) or any(c in subvolumen for c in ",#\\"):
                raise ValueError("El nombre del subvolumen requiere configuración manual.")
            opciones.append("subvol=" + subvolumen)
        if cantidad > 1:
            for disco in discos:
                opciones.extend(["device=/dev/mapper/" + disco["nombre"], "x-systemd.requires=/dev/mapper/" + disco["nombre"]])
    fragmento = "".join(f"{d['nombre']} UUID={d['uuid']} {d['clave']} luks,nofail,x-systemd.device-timeout=60s\n" for d in discos)
    (PENDIENTE / "crypttab.fragmento").write_text(fragmento)
    (PENDIENTE / "fstab.fragmento").write_text(f"/dev/mapper/{discos[0]['nombre']} {escape_fstab(str(destino))} {tipos[0]} {','.join(opciones)} 0 0\n")
    destino.mkdir(parents=True, exist_ok=True)
    print("Preparación completa. Claves guardadas en la raíz cifrada; no se han mostrado.")
    print("Fragmentos y respaldos privados en:", PENDIENTE)
    print("Revisa los fragmentos e incorpóralos según el paso de primera configuración de datos del manual.")
    print("No se han editado crypttab ni fstab. Los mapeos nuevos quedan abiertos, sin montar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrumpido. Si se creó la preparación privada, conserva sus claves y revisa su estado antes de repetir.", file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        print(f"Se detuvo la preparación: {error}", file=sys.stderr)
        print("Si existe /root/tpm-datos-pendiente, puede haber cambios parciales. No borres sus claves ni repitas sin revisar.", file=sys.stderr)
        sys.exit(1)
