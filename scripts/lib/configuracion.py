#!/usr/bin/env python3
"""Detección y edición de metadatos. No lee ni imprime claves LUKS."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

KEYSCRIPT = "/usr/local/sbin/desbloquear-raiz-tpm"


def ejecutar(*args):
    return subprocess.check_output(args, text=True).strip()


def ancestros_cifrados(arbol):
    encontrados = set()
    for nodo in arbol:
        if nodo.get("fstype") == "crypto_LUKS":
            encontrados.add(nodo["name"])
        encontrados.update(ancestros_cifrados(nodo.get("children", [])))
    return encontrados


def entrada_raiz(texto, uuid):
    coincidencias = []
    for linea in texto.splitlines():
        campos = linea.split("#", 1)[0].split()
        if len(campos) >= 2 and campos[1].lower() == f"uuid={uuid}".lower():
            if len(campos) != 4:
                raise ValueError("La entrada raíz debe tener cuatro campos en crypttab.")
            coincidencias.append(campos)
    if len(coincidencias) != 1:
        raise ValueError("Se requiere una única entrada raíz por UUID en crypttab.")
    campos = coincidencias[0]
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", campos[0]):
        raise ValueError("Nombre de mapeo no admitido.")
    if campos[2] != "none" or "luks" not in campos[3].split(","):
        raise ValueError("Se requiere raíz LUKS con campo de clave 'none'.")
    opciones = campos[3].split(",")
    if any(x.startswith(("tpm2-", "fido2-", "pkcs11-", "header=")) for x in opciones):
        raise ValueError("Hay otra integración de tokens o cabecera separada; revisar manualmente.")
    scripts = [x.split("=", 1)[1] for x in opciones if x.startswith("keyscript=")]
    if len(scripts) > 1 or (scripts and not scripts[0].startswith("/")):
        raise ValueError("Configuración de keyscript ambigua o relativa.")
    return campos, scripts[0] if scripts else ""


def detectar():
    raiz = ejecutar("findmnt", "-n", "-o", "SOURCE", "/").split("[", 1)[0]
    if not raiz.startswith("/dev/"):
        raise ValueError("La raíz debe estar montada desde un dispositivo de bloques.")
    arbol = json.loads(ejecutar("lsblk", "--json", "-s", "-p", "-o", "NAME,FSTYPE", raiz))
    discos = ancestros_cifrados(arbol["blockdevices"])
    if len(discos) != 1:
        raise ValueError("Se admite una única partición LUKS bajo la raíz; no se elegirá otro disco.")
    device = os.path.realpath(discos.pop())
    uuid = ejecutar("cryptsetup", "luksUUID", device)
    campos, script = entrada_raiz(Path("/etc/crypttab").read_text(), uuid)
    # La lectura JSON también comprueba que se trata de LUKS2.
    json.loads(ejecutar("cryptsetup", "luksDump", "--dump-json-metadata", device))
    return device, campos[0], script


def ranura_libre(metadatos):
    ocupadas = {int(n) for n in metadatos["keyslots"]}
    for numero in range(32):
        if numero not in ocupadas:
            return numero
    raise ValueError("No hay ranuras LUKS2 libres; no se eliminará ninguna.")


def objeto_libre(salida):
    ocupados = {int(h, 16) for h in re.findall(r"0x[0-9a-fA-F]{8}", salida)}
    # Rango de propietario: se excluye el primer identificador habitual.
    for numero in range(0x81000001, 0x81000100):
        if numero not in ocupados:
            return f"0x{numero:08x}"
    raise ValueError("No hay identificadores TPM libres en el rango de búsqueda.")


def validar_swap():
    # tmpfs puede usar swap; comprobar su respaldo antes de guardar una clave en /run.
    nombres = ejecutar("swapon", "--show", "--noheadings", "--raw", "--output", "NAME")
    for nombre in nombres.splitlines():
        dispositivo = os.path.realpath(nombre)
        if re.fullmatch(r"/dev/zram[0-9]+", dispositivo):
            continue
        if not dispositivo.startswith("/dev/"):
            dispositivo = ejecutar("findmnt", "-n", "-o", "SOURCE", "-T", nombre).split("[", 1)[0]
        arbol = json.loads(ejecutar("lsblk", "--json", "-s", "-p", "-o", "NAME,TYPE", dispositivo))

        def cifrado(nodos):
            return any(n.get("type") == "crypt" or cifrado(n.get("children", [])) for n in nodos)

        if not cifrado(arbol["blockdevices"]):
            raise ValueError("Hay swap sin cifrado verificable. Revisar antes de crear claves temporales.")


def actualizar_crypttab(texto, nombre):
    resultado = []
    cambios = 0
    for linea in texto.splitlines(keepends=True):
        contenido, marca, comentario = linea.rstrip("\n").partition("#")
        campos = contenido.split()
        if campos and campos[0] == nombre:
            if len(campos) != 4:
                raise ValueError("Entrada raíz no admitida.")
            opciones = [o for o in campos[3].split(",") if not o.startswith("keyscript=")]
            if "initramfs" not in opciones:
                opciones.append("initramfs")
            opciones.append(f"keyscript={KEYSCRIPT}")
            campos[3] = ",".join(opciones)
            linea = "\t".join(campos)
            if marca:
                linea += " #" + comentario
            linea += "\n"
            cambios += 1
        resultado.append(linea)
    if cambios != 1:
        raise ValueError("La entrada seleccionada no es única; no se modificará crypttab.")
    return "".join(resultado)


def main():
    accion = sys.argv[1]
    if accion == "detectar":
        for dato in detectar():
            print(dato)
    elif accion == "ranura":
        print(ranura_libre(json.loads(ejecutar("cryptsetup", "luksDump", "--dump-json-metadata", sys.argv[2]))))
    elif accion == "objeto":
        print(objeto_libre(ejecutar("tpm2_getcap", "-T", "device:/dev/tpmrm0", "handles-persistent")))
    elif accion == "crypttab":
        Path(sys.argv[4]).write_text(actualizar_crypttab(Path(sys.argv[2]).read_text(), sys.argv[3]))
    elif accion == "estado":
        Path(sys.argv[2]).write_text(json.dumps({"objeto_tpm": sys.argv[3], "ranura_luks": int(sys.argv[4])}, indent=2) + "\n")
    elif accion == "validar-swap":
        validar_swap()
    else:
        raise ValueError("Acción desconocida.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, IndexError, KeyError) as error:
        print(f"No se pudo completar la comprobación: {error}", file=sys.stderr)
        sys.exit(1)
