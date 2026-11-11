#!/usr/bin/env python3
"""Revisar o volver a iniciar servicios y montajes existentes, sin leer claves."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from configuracion import detectar


def consulta(*args):
    return subprocess.check_output(args, text=True).strip()


def estado(unidad):
    resultado = subprocess.run(["systemctl", "is-active", unidad], text=True, capture_output=True)
    return resultado.stdout.strip() or "desconocido"


def comprobar_bus():
    # Evita informar unidades inactivas cuando no hay acceso al gestor del sistema.
    consulta("systemctl", "show", "--property=Version", "--value")


def unidad_crypt(nombre):
    return consulta("systemd-escape", "--template=systemd-cryptsetup@.service", nombre)


def unidad_mount(destino):
    return consulta("systemd-escape", "--path", "--suffix=mount", destino)


def configuracion_datos(raiz):
    entradas = []
    for linea in Path("/etc/crypttab").read_text().splitlines():
        campos = linea.split("#", 1)[0].split()
        if not campos or campos[0] == raiz:
            continue
        if len(campos) != 4 or not re.fullmatch(r"[A-Za-z0-9_.+-]+", campos[0]):
            raise ValueError("Hay una entrada de datos en crypttab que requiere revisión manual.")
        if "noauto" in campos[3].split(","):
            continue
        if "luks" not in campos[3].split(","):
            continue
        entradas.append(campos)
    return entradas


def todas_las_filas(filas):
    for fila in filas:
        yield fila
        yield from todas_las_filas(fila.get("children", []))


def montajes_datos(nombres):
    fstab = json.loads(consulta("findmnt", "--fstab", "--json", "--list", "-o", "SOURCE,TARGET,FSTYPE,OPTIONS"))
    filas = list(todas_las_filas(fstab.get("filesystems", [])))
    seleccion = []
    pendientes = []
    mapeos = {f"/dev/mapper/{nombre}" for nombre in nombres}
    for fila in filas:
        opciones = fila.get("options") or ""
        if "noauto" in opciones.split(","):
            continue
        referencias = {fila.get("source", "")}
        referencias.update(opcion.split("=", 1)[1] for opcion in opciones.split(",")
                            if opcion.startswith(("device=", "x-systemd.requires=")))
        if referencias & mapeos:
            seleccion.append(fila)
        elif "bind" in opciones.split(",") or "rbind" in opciones.split(","):
            pendientes.append(fila)
    # Añadir solo binds cuya fuente esté en un montaje de datos ya identificado.
    while pendientes:
        nuevas = []
        for fila in pendientes:
            fuente = fila.get("source", "")
            if any(fuente == m["target"] or fuente.startswith(m["target"].rstrip("/") + "/") for m in seleccion):
                nuevas.append(fila)
        if not nuevas:
            break
        for fila in nuevas:
            seleccion.append(fila)
            pendientes.remove(fila)
    return seleccion


def comprobar_clave(ruta):
    if not ruta.startswith("/"):
        return False, "requiere una clave de archivo local; revisar manualmente"
    archivo = Path(ruta)
    if archivo.is_symlink():
        return False, "la clave es un enlace simbólico; revisar manualmente"
    try:
        datos = archivo.stat()
    except FileNotFoundError:
        return False, "no existe el archivo de clave"
    if not stat.S_ISREG(datos.st_mode) or datos.st_size == 0:
        return False, "archivo de clave vacío o no regular"
    if datos.st_uid != 0 or stat.S_IMODE(datos.st_mode) & 0o077:
        return False, "la clave debe ser de root y sin acceso para grupo u otros"
    return True, "archivo presente y permisos privados; contenido no leído"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recuperar", action="store_true", help="recargar systemd e iniciar servicios y montajes existentes que estén inactivos; no reiniciar los activos")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("Ejecuta con sudo. La salida local puede contener metadatos privados.")
    comprobar_bus()
    _, raiz, _ = detectar()
    entradas = configuracion_datos(raiz)
    montajes = montajes_datos([entrada[0] for entrada in entradas])
    print("Diagnóstico local: no se leen ni muestran las claves. No publiques esta salida sin revisarla.")
    if args.recuperar:
        # No se crean unidades duplicadas ni se editan crypttab o fstab.
        subprocess.run(["systemctl", "daemon-reload"], check=True)
    fallos = 0
    for nombre, _, clave, _ in entradas:
        unidad = unidad_crypt(nombre)
        activo = estado(unidad)
        valida, detalle = comprobar_clave(clave)
        print(f"{unidad}: {activo}; {detalle}")
        if not valida:
            fallos += 1
        if activo != "active":
            if args.recuperar and valida:
                subprocess.run(["systemctl", "start", unidad], check=True)
                activo = estado(unidad)
            if activo != "active":
                fallos += 1
    if args.recuperar and fallos:
        raise ValueError("Hay servicios o claves sin resolver; no se intentarán montar los datos.")
    for fila in montajes:
        unidad = unidad_mount(fila["target"])
        activo = estado(unidad)
        if activo != "active" and args.recuperar:
            subprocess.run(["systemctl", "start", unidad], check=True)
            activo = estado(unidad)
        print(f"{unidad}: {activo}")
        if activo != "active":
            fallos += 1
    if not entradas:
        print("No se encontraron entradas LUKS de datos automáticas distintas de la raíz.")
    elif not montajes:
        print("No se encontraron montajes fstab asociados a los mapeos detectados.")
        fallos += 1
    if fallos:
        print("Se necesita revisión. Consulta la sección de discos de datos del manual.", file=sys.stderr)
        return 1
    print("Los servicios y montajes detectados están activos; esto no verifica la integridad del contenido.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        print(f"No se pudo completar la revisión: {error}", file=sys.stderr)
        sys.exit(1)
