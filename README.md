# zorin-tpm-unlock

Guía en español para configurar por primera vez el desbloqueo automático de la raíz LUKS2 con TPM 2.0 en Zorin OS y el montaje posterior de los discos de datos. Incluye scripts de preparación, comprobación y recuperación.

El recorrido empieza con una instalación que todavía pide la contraseña de descifrado al arrancar. Termina cuando la raíz se abre mediante TPM y, si se configura la parte opcional, los datos se desbloquean y montan mediante systemd. La recuperación ante cambios de firmware se explica después de la primera configuración.

Los comandos de esta guía son instrucciones de uso. No contienen contraseñas, claves, identificadores de discos ni rutas de una persona. Los scripts detectan los valores del equipo o los solicitan en la terminal; los archivos privados resultantes se guardan fuera del repositorio.

## Recorrido de primera configuración

| Paso | Objetivo | Cuándo continuar |
| --- | --- | --- |
| 1. Preparar el sistema | Tener Zorin con raíz ya cifrada y acceso por contraseña. | Puedes arrancar usando tu contraseña de descifrado. |
| 2. Abrir la guía y la terminal | Trabajar desde la carpeta que contiene los archivos. | La terminal está en la carpeta del README. |
| 3. Instalar las herramientas | Disponer de las dependencias de TPM e initramfs. | La instalación de paquetes termina correctamente. |
| 4. Revisar los requisitos | Confirmar raíz compatible, TPM, Secure Boot, espacio y swap. | Las comprobaciones no presentan errores. |
| 5. Configurar la raíz | Crear una clave TPM adicional conservando la contraseña. | El script y la regeneración del arranque terminan correctamente. |
| 6. Probar la raíz | Confirmar el acceso en la sesión y después de reiniciar. | El arranque abre la raíz automáticamente. |
| 7. Preparar los datos, opcional | Crear las claves y registrar servicios y montajes. | Los servicios y montajes de datos están activos. |
| 8. Verificar el conjunto | Probar otro arranque y conservar respaldos privados. | Puedes acceder al sistema y a los datos esperados. |

## Paso 1. Preparar el sistema y conservar el acceso manual

Esta guía parte de **Zorin OS 18.1 instalado con la raíz cifrada mediante LUKS2**, una única partición LUKS bajo la raíz y arranque basado en `initramfs-tools`. Puede haber LVM dentro del cifrado. No necesitas haber configurado previamente ningún objeto TPM, keyscript o servicio de datos.

Si todavía no has instalado Zorin, consulta la [guía oficial de instalación](https://help.zorin.com/docs/getting-started/install-zorin-os/), que describe el cifrado y LVM en las funciones avanzadas de instalación. Elegir borrar e instalar elimina los datos del disco seleccionado: respáldalos y verifica el destino antes de instalar. Los scripts de este proyecto no instalan Zorin ni convierten una raíz sin cifrar en una raíz cifrada.

Antes de seguir, arranca al menos una vez usando la contraseña de descifrado y consérvala fuera del equipo. Esa contraseña abre el disco; la contraseña de inicio de sesión abre tu sesión del escritorio. Pueden ser distintas. El desbloqueo por TPM no elimina la necesidad de una contraseña de recuperación.

La parte opcional de discos de datos parte de volúmenes **ya cifrados con LUKS2 y con sus sistemas de archivos creados**. No se incluyen operaciones de particionado, formateo ni creación de RAID. Para Btrfs con varios miembros, el sistema de archivos debe existir previamente y se deben preparar juntos todos sus miembros necesarios.

## Paso 2. Abrir la carpeta correcta

Descarga y extrae el repositorio, o utiliza tu copia local. Abre la carpeta que contiene `README.md`, `scripts` y `plantillas`. Desde el gestor de archivos, abre una terminal en esa carpeta y mantenla como directorio de trabajo durante el recorrido.

Escribe únicamente los comandos de los bloques de terminal. Los párrafos explicativos no son comandos. Cuando `sudo` pida contraseña, escríbela aunque no aparezcan caracteres en pantalla. No ejecutes los scripts con `bash -x` ni grabes las solicitudes de contraseñas.

Si tu desbloqueo ya funciona, no necesitas repetir la primera configuración; consulta las secciones de comprobación y recuperación.

## Paso 3. Instalar las herramientas

Ejecuta:

```bash
sudo apt update
sudo apt install cryptsetup cryptsetup-initramfs initramfs-tools tpm2-initramfs-tool tpm2-tools libtss2-tcti-device0 mokutil python3 util-linux
```

`cryptsetup` administra LUKS; `cryptsetup-initramfs` lo integra en el arranque; `tpm2-initramfs-tool` sella y libera la clave; `tpm2-tools` permite consultar el TPM. Las demás herramientas comprueban el arranque y los dispositivos. El script de configuración no instala paquetes por su cuenta.

Si los datos usan Btrfs, instala además:

```bash
sudo apt install btrfs-progs
```

## Paso 4. Comprobar antes de cambiar la configuración

Revisa el esquema de discos y el espacio disponible:

```bash
lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINTS
findmnt /
df -h / /boot
```

Debe existir una partición `crypto_LUKS` bajo el dispositivo que contiene `/`. No elijas un disco solo por su orden o nombre corto. Los scripts detectan el que respalda la raíz y se detienen si el esquema es ambiguo.

Comprueba Secure Boot y la comunicación con TPM 2.0:

```bash
mokutil --sb-state
sudo tpm2_getcap -T device:/dev/tpmrm0 properties-fixed
```

Secure Boot debe estar activado y el comando del TPM debe finalizar correctamente. Si falla, revisa el firmware y el soporte de hardware antes de continuar. No cambies sus certificados ni borres el TPM para superar una comprobación.

Comprueba la detección de la raíz y el respaldo de swap:

```bash
sudo python3 scripts/lib/configuracion.py detectar
sudo python3 scripts/lib/configuracion.py validar-swap
```

La primera orden identifica la partición LUKS y su mapeo; también muestra el keyscript si ya existía. La segunda termina sin salida si no encuentra una swap insegura. `/run` debe ser tmpfs; la swap debe estar desactivada, en zram o sobre almacenamiento cifrado verificable. El instalador vuelve a comprobarlo antes de guardar una clave temporal.

La entrada raíz de `/etc/crypttab` debe existir, usar UUID, tener tipo `luks` y campo de clave `none`. Una instalación compatible suele proporcionar esa entrada. Si la detección la rechaza, revisa el formato de tu instalación; no añadas valores inventados ni copies la configuración de otro equipo.

**Continúa únicamente cuando estas comprobaciones terminen correctamente.** Las salidas son información local y pueden contener identificadores: no las guardes en el repositorio público.

## Paso 5. Configurar el desbloqueo de la raíz por primera vez

Ejecuta:

```bash
sudo bash scripts/configurar-tpm.sh
```

El instalador busca una ranura LUKS y un identificador TPM libres, verifica la contraseña manual, crea respaldos, sella una clave nueva con SHA256/PCR 7 y añade una ranura para ella. Después instala el script de arranque, su hook y la entrada correspondiente de crypttab, y regenera los initramfs.

Durante el proceso introduce la contraseña de descifrado cuando se solicite. El script la comprueba antes de crear claves y la vuelve a solicitar para autorizar la nueva ranura. Las ranuras y objetos anteriores se conservan.

Espera a que termine la regeneración del arranque. Si muestra un error, no pases al reinicio: consulta la sección de errores. Guarda la ubicación del respaldo privado que informa el script y conserva una copia externa privada de la cabecera y de la configuración.

## Paso 6. Comprobar y reiniciar

Prueba primero dentro de la sesión:

```bash
sudo bash scripts/diagnosticar.sh
```

El diagnóstico libera la clave sin mostrarla y comprueba que abre LUKS. Si termina correctamente, guarda el trabajo y reinicia manualmente con la contraseña de descifrado disponible. El script nunca reinicia por su cuenta.

El resultado esperado es que el disco raíz se abra sin solicitar esa contraseña. El escritorio puede seguir solicitando la contraseña de inicio de sesión. Si vuelve a pedir la del disco, introdúcela para entrar y consulta la recuperación; no borres ranuras ni objetos.

No pases a preparar discos adicionales hasta comprobar este primer reinicio.

## Paso 7. Configurar por primera vez los discos de datos, opcional

Omite este paso si solo tienes el disco del sistema. Si tus discos de datos **ya están registrados** en crypttab y fstab, utiliza directamente la revisión del final de este paso; no prepares claves por duplicado.

### 7.1. Identificar el sistema de archivos que vas a registrar

Cada ejecución prepara un sistema de archivos independiente. Si está distribuido entre varias particiones cifradas Btrfs, incluye todos sus miembros necesarios en la misma ejecución. No agrupes discos de sistemas de archivos independientes. Debes conocer las contraseñas de descifrado actuales.

Cierra las aplicaciones que usan esos datos y deja los dispositivos de este paso cerrados y sin montar. El asistente rechaza la raíz, dispositivos repetidos, discos ya abiertos, entradas ya registradas y destinos ocupados.

### 7.2. Preparar claves y archivos de configuración privados

Ejecuta:

```bash
sudo python3 scripts/preparar-datos.py
```

El asistente muestra el inventario local y solicita las rutas reales de las particiones, la cantidad de miembros y el directorio de montaje. Después de confirmar los datos, verifica las contraseñas, respalda las cabeceras, genera claves de archivo dentro de la raíz cifrada y las añade a ranuras libres. Comprueba el acceso con esas claves y abre los mapeos para detectar el sistema de archivos. No formatea ni monta.

Se admiten ext4, XFS y Btrfs existentes. Varios miembros deben pertenecer al mismo Btrfs. Si solicita un subvolumen Btrfs, indica solo uno que ya exista; dejarlo vacío utiliza el predeterminado. No se crean subvolúmenes.

Las claves quedan bajo `/etc/cryptsetup-keys.d` con permisos privados. Los fragmentos y respaldos se guardan en `/root/tpm-datos-pendiente`, fuera del repositorio. Si se interrumpe la preparación, puede haber claves o ranuras nuevas: conserva esos archivos y revisa el estado antes de repetir.

### 7.3. Revisar e incorporar las entradas

Consulta los fragmentos generados; contienen los valores reales del equipo y las rutas de claves, no sus contenidos:

```bash
sudo cat /root/tpm-datos-pendiente/crypttab.fragmento
sudo cat /root/tpm-datos-pendiente/fstab.fragmento
```

Abre los archivos persistentes:

```bash
sudoedit /etc/crypttab
sudoedit /etc/fstab
```

Añade al final de cada archivo **solo** el contenido del fragmento correspondiente. Conserva las entradas existentes, incluida la raíz. No copies los fragmentos al repositorio ni dupliques líneas. El asistente no incorpora automáticamente esas entradas para que puedas revisarlas primero.

En crypttab, cada línea relaciona un volumen con su clave dentro de la raíz cifrada. En fstab, la línea relaciona el mapeo con su punto de montaje. Para Btrfs con varios miembros, el fragmento incluye las referencias y dependencias necesarias para esperar los mapeos seleccionados.

Comprueba la configuración de montajes:

```bash
sudo findmnt --verify --verbose
```

Corrige cualquier error antes de continuar. No añadas todavía montajes bind ni dependencias de aplicaciones: primero verifica los datos base.

### 7.4. Activar las unidades generadas y comprobar los datos

Ejecuta:

```bash
sudo python3 scripts/revisar-datos.py --recuperar
sudo python3 scripts/revisar-datos.py
```

La primera orden recarga systemd e inicia las unidades necesarias. La segunda consulta el resultado. Los servicios se generan desde crypttab y los montajes desde fstab: no necesitas crear un servicio personalizado ni habilitar copias de las unidades generadas.

Comprueba que puedes acceder a los archivos en el destino que elegiste. Un servicio `active (exited)` puede ser correcto: el dispositivo quedó abierto. Un montaje `active (mounted)` indica que está montado. Esos estados no comprueban la integridad de los datos ni sustituyen revisar su contenido.

Conserva una copia externa privada de las claves y respaldos. Tras completar la configuración y comprobar el montaje, archiva la preparación local para poder registrar otro sistema de archivos independiente:

```bash
archivo_privado=$(sudo mktemp -d /root/tpm-datos-configurados.XXXXXXXX)
sudo mv -- /root/tpm-datos-pendiente "$archivo_privado/"
```

Ese movimiento conserva los respaldos; no mueve las claves utilizadas por crypttab. Repite el paso 7 únicamente para otros sistemas de archivos todavía sin registrar.

## Paso 8. Verificar el arranque completo y cerrar la primera configuración

Guarda el trabajo y reinicia manualmente. Comprueba que la raíz se desbloquee mediante TPM y que los discos de datos esperados estén disponibles. Después ejecuta:

```bash
sudo bash scripts/diagnosticar.sh
sudo python3 scripts/revisar-datos.py
```

Si no tienes discos de datos, omite la segunda orden. La primera configuración termina cuando has verificado el reinicio, el acceso real a tus archivos y la disponibilidad externa de las contraseñas y respaldos privados.

Solo después configura montajes bind o servicios de aplicaciones que utilicen esos datos. Sus dependencias deben esperar al montaje de origen; la sección de referencia explica esa relación.

Las secciones siguientes son consulta técnica y recuperación. **No es necesario ejecutar una renovación de TPM para completar una primera configuración que ya funciona.**

## Contenido

| Archivo | Función |
| --- | --- |
| `scripts/configurar-tpm.sh` | Configurar o renovar el desbloqueo de la raíz detectada. |
| `scripts/diagnosticar.sh` | Consultar el estado y probar el acceso sin mostrar la clave. |
| `scripts/preparar-datos.py` | Preparar por primera vez claves y fragmentos privados para los discos de datos. |
| `scripts/revisar-datos.py` | Revisar los servicios de descifrado y montajes de datos; iniciar los inactivos cuando se solicita. |
| `scripts/lib/configuracion.py` | Detectar la raíz, seleccionar recursos libres y editar su entrada de configuración. |
| `plantillas/desbloquear-raiz-tpm.sh.in` | Plantilla del script que libera la clave o solicita contraseña. |
| `plantillas/hook-tpm-initramfs.sh` | Incorporar al arranque las herramientas y bibliotecas necesarias. |

No se distribuyen claves, contraseñas, cabeceras LUKS, salidas de terminal ni identificadores de un equipo. Las plantillas son archivos de instalación; sus parámetros se resuelven localmente.

## Referencia: cómo funciona

LUKS cifra los datos con una clave interna. Sus ranuras permiten autorizar el acceso mediante distintas contraseñas o claves. Añadir una ranura no vuelve a cifrar todo el disco. El instalador conserva las ranuras anteriores y añade otra para el TPM. [Referencia de cryptsetup](https://manpages.ubuntu.com/manpages/noble/man8/cryptsetup-luksAddKey.8.html).

El TPM conserva un objeto persistente que contiene la nueva clave sellada. Para liberarla debe cumplirse la política SHA256/PCR 7 con la que se creó. Un identificador de objeto y el hash de su política son metadatos; no son la clave de descifrado.

PCR 7 refleja la política de Secure Boot, incluyendo cambios en sus bases y certificados. Una actualización de `dbx`, la base de firmas revocadas, puede cambiar esa medición aunque Secure Boot siga activado. Un hash antiguo de política no permite reconstruir el estado anterior. [Referencia de PCR y políticas](https://www.freedesktop.org/software/systemd/man/255/systemd-cryptenroll.html).

Durante el arranque ocurre lo siguiente:

1. El firmware inicia la cadena de arranque y realiza sus mediciones.
2. El initramfs carga las herramientas necesarias para acceder al disco raíz.
3. El `keyscript` solicita la clave al TPM.
4. Si la política coincide, entrega la clave a cryptsetup por la salida estándar.
5. Si el TPM falla, solicita la contraseña mediante `askpass`.
6. Una vez abierta la raíz, el sistema continúa su arranque normal.

La opción `keyscript` pertenece a la implementación de crypttab utilizada por los scripts de initramfs de Debian/Ubuntu. No debe confundirse con el soporte de tokens de systemd. Este proyecto usa esa ruta deliberadamente. [Referencia de crypttab](https://manpages.ubuntu.com/manpages/noble/man5/crypttab.5.html).

Los volúmenes de datos pueden tener claves guardadas dentro de la raíz cifrada. Sus servicios se generan desde crypttab y los montajes desde fstab. Los scripts de configuración de TPM conservan esas entradas; el script de revisión de datos permite comprobarlas y volver a iniciar unidades inactivas. Si falla el desbloqueo de la raíz, también se retrasa la disponibilidad de las claves de datos.

### Compatibilidad y límites

- Una instalación existente con raíz LUKS2 y contraseña de descifrado conocida y funcional.
- Una única partición LUKS bajo la raíz. Puede contener LVM. Los esquemas con varios dispositivos cifrados bajo la raíz se rechazan.
- Una entrada única de la raíz en `/etc/crypttab`, referenciada mediante UUID, con cuatro campos, tipo `luks` y campo de clave `none`.
- TPM 2.0 accesible mediante `/dev/tpmrm0` y Secure Boot activado.
- `initramfs-tools`, `cryptsetup-initramfs` y `askpass` disponibles.
- Permisos administrativos y una terminal interactiva.
- Espacio libre en `/boot` para regenerar los initramfs y en la raíz para los respaldos.
- `/run` montado como tmpfs. La swap activa debe estar desactivada, en zram o respaldada por un dispositivo cifrado verificable.
- Una copia de seguridad independiente de los datos importantes y acceso a la contraseña fuera del equipo.

El script rechaza cabeceras separadas y opciones de integración con otros tokens. No migra configuraciones Clevis, dracut, UKI o desbloqueo TPM gestionado por systemd. No modifica la configuración del firmware ni instala actualizaciones de BIOS o de `dbx`.

La política usa únicamente PCR 7. No mide con ella el contenido completo del kernel y del initramfs. Este alcance favorece la continuidad ante ciertas actualizaciones, pero no equivale a verificar cada componente del arranque. Tampoco exige presencia física, PIN o contraseña cuando el desbloqueo automático funciona. La contraseña de inicio de sesión del escritorio es una protección distinta. Un atacante con acceso al sistema ya desbloqueado puede acceder a los datos según sus permisos.

## Referencia: cambios que realiza la configuración de TPM

Cuando necesita configurar o recuperar el acceso, realiza estas operaciones:

1. Comprueba requisitos, swap y ausencia de otra ejecución del proyecto.
2. Detecta la raíz y valida su entrada de crypttab y el formato LUKS2.
3. Busca una ranura LUKS libre y un identificador TPM libre en el rango de propietario usado por el proyecto.
4. Solicita la contraseña de descifrado para comprobar el acceso manual.
5. Respalda la cabecera LUKS y los archivos que va a modificar en un directorio privado bajo `/root/tpm-luks-respaldos`.
6. Crea una clave aleatoria con `tpm2-initramfs-tool` y la sella en un objeto nuevo con SHA256/PCR 7.
7. Libera esa clave y comprueba que coincide con la recién generada.
8. Solicita otra vez la contraseña de descifrado para autorizar una ranura nueva.
9. Prueba con esa ranura que la clave liberada por el TPM permite acceder a LUKS.
10. Instala el script y el hook, actualiza exclusivamente la entrada de la raíz en crypttab y guarda los metadatos de la operación.
11. Repite la prueba de acceso con el script instalado y regenera los initramfs de los kernels instalados.

La contraseña inicial de `sudo` autoriza la administración. Las otras solicitudes son la contraseña de descifrado. No se guardan en variables ni en archivos del proyecto. No ejecutes estos scripts con trazado `bash -x`, grabación de terminal ni herramientas que capturen secretos.

Los archivos instalados son:

| Ruta del sistema | Contenido |
| --- | --- |
| `/usr/local/sbin/desbloquear-raiz-tpm` | Script con el identificador TPM seleccionado y la alternativa de contraseña. |
| `/etc/initramfs-tools/hooks/desbloquear-raiz-tpm` | Hook que incorpora herramientas, bibliotecas y controladores al initramfs. |
| `/etc/crypttab` | Su entrada raíz pasa a utilizar el nuevo script y la opción `initramfs`. |
| `/etc/tpm-luks-zorin/estado.json` | Identificador TPM y ranura LUKS de la configuración más reciente. |
| `/root/tpm-luks-respaldos` | Respaldos privados y metadatos de cada operación. |

La clave temporal se guarda con permisos privados dentro de un directorio aleatorio de `/run`. Se elimina al terminar o al capturarse un error o una interrupción. Un corte abrupto o una señal no capturable pueden impedir esa limpieza; los datos de tmpfs desaparecen al reiniciar. La comprobación de swap evita usar una swap sin cifrado verificable para respaldar esos datos.

Conserva el respaldo de cabecera también en almacenamiento privado externo. Una copia guardada únicamente dentro del mismo disco no ayuda si este queda inaccesible. La cabecera no contiene la contraseña en claro, pero es material sensible y permite ataques fuera de línea contra sus ranuras.

## Referencia: servicios de los discos de datos

El desbloqueo de la raíz y el de los discos de datos son etapas diferentes. En este diseño, el TPM libera la clave de la raíz. Después, los archivos de claves disponibles dentro de esa raíz autorizan el acceso a los otros discos. No se necesita un objeto TPM independiente para cada disco de datos con este diseño.

Este diseño utiliza servicios `systemd-cryptsetup@.service` generados automáticamente desde `/etc/crypttab`. Para cada volumen, systemd abre el dispositivo LUKS usando el archivo indicado en esa configuración. El servicio generado incluye la dependencia necesaria para acceder al sistema de archivos que contiene la clave. No se necesita un servicio personalizado que duplique esas operaciones. [Generador de servicios de descifrado](https://www.freedesktop.org/software/systemd/man/255/systemd-cryptsetup-generator.html).

Las unidades `.mount` se generan desde `/etc/fstab`. En un sistema Btrfs con varios miembros cifrados, primero deben estar disponibles los mapeos requeridos y después montarse el sistema de archivos. Un montaje bind posterior debe esperar al montaje que contiene su directorio de origen. Esta secuencia evita utilizar un directorio vacío de la raíz cuando el volumen esperado todavía no se ha montado.

| Etapa | Responsable | Dependencia |
| --- | --- | --- |
| Abrir la raíz | Initramfs, keyscript y TPM; contraseña si falla | Política válida o contraseña manual. |
| Abrir volúmenes de datos | Servicios generados desde crypttab | Dispositivo presente y archivo de clave accesible. |
| Montar sistemas de archivos | Unidades generadas desde fstab | Mapeos requeridos disponibles; todos los miembros necesarios en Btrfs. |
| Montar directorios bind | Unidades generadas desde fstab | Montaje de origen disponible. |
| Iniciar aplicaciones que usan los datos | Su servicio o aplicación | Montaje de datos disponible. |

Las opciones de fstab relevantes son `x-systemd.requires=`, que crea una dependencia y orden respecto de otro dispositivo o unidad, y `x-systemd.requires-mounts-for=`, que espera los montajes necesarios para acceder a una ruta. Las opciones `device=` de Btrfs permiten indicar miembros adicionales. `nofail` permite continuar el arranque aunque ese montaje falle; no garantiza que los datos estén disponibles. Los tiempos de espera de dispositivo tampoco son comprobaciones de integridad. [Dependencias y opciones de montaje](https://www.freedesktop.org/software/systemd/man/255/systemd.mount.html).

No copies ni edites como configuración persistente los archivos de `/run/systemd/generator`: se vuelven a generar. Las fuentes persistentes son crypttab y fstab. Tampoco hace falta habilitar manualmente cada servicio generado ni crear un segundo servicio que ejecute los mismos montajes.

En los servicios de descifrado, el estado `active (exited)` es normal: la operación terminó y el mapeo permanece abierto. En las unidades de montaje, `active (mounted)` indica que el montaje está activo. No son procesos que deban permanecer ejecutándose continuamente.

### Revisar sin modificar

Desde la carpeta del manual:

```bash
sudo python3 scripts/revisar-datos.py
```

El script detecta la raíz y excluye su entrada de la revisión de datos. Lee los metadatos de crypttab y fstab, comprueba la existencia, propiedad y permisos de los archivos de claves mediante sus atributos, y consulta los estados de los servicios y montajes. **No abre ni imprime el contenido de las claves.** Omite entradas marcadas `noauto`.

Identifica los montajes asociados a los mapeos de datos y los bind cuyo origen está dentro de esos montajes. No modifica la configuración ni intenta reparar el sistema de archivos. La salida muestra nombres y rutas locales necesarios para el diagnóstico; revísala antes de compartirla y no la añadas al repositorio.

### Volver a iniciar los servicios y montajes existentes

Si la configuración y los archivos de claves siguen siendo correctos, solicita la recuperación de unidades inactivas:

```bash
sudo python3 scripts/revisar-datos.py --recuperar
```

Este modo recarga la configuración de systemd, inicia los servicios de datos inactivos, y solo cuando las claves y servicios revisados son válidos intenta iniciar los montajes asociados. Los montajes bind se procesan después de sus orígenes. Las unidades que ya están activas se conservan: no se desmontan discos, no se cierran mapeos y no se reinician servicios activos.

El script opera exclusivamente sobre la configuración ya existente. No restaura archivos de claves perdidos, no añade ranuras, no cambia UUID ni escribe entradas nuevas en crypttab o fstab. Los inicios de servicios pueden esperar hasta que venza el tiempo configurado para un dispositivo ausente. Si hay un error, se detiene y conserva las unidades que ya estaban o llegaron a estar activas.

### Recuperación según la etapa que falla

| Fallo | Revisión necesaria |
| --- | --- |
| La raíz solicita contraseña | Diagnosticar TPM y PCR; los discos de datos todavía no tienen disponibles sus claves. |
| Servicio de datos inactivo o fallido | Presencia del disco, correspondencia del dispositivo configurado y existencia y permisos del archivo de clave. |
| Clave de datos perdida o inválida | Recuperar su copia privada o usar otra credencial válida del volumen; renovar el TPM de la raíz no recrea esa clave. |
| Servicios activos y montaje Btrfs fallido | Miembros requeridos, dependencias, subvolumen y opciones de fstab. No forzar montaje degradado ni reparación automática. |
| Montaje bind fallido | Disponibilidad del montaje de origen y existencia del directorio configurado. |
| Aplicación que utiliza una ruta no montada | Detener la aplicación antes de escribir allí y corregir la dependencia de su servicio con el montaje necesario. |

Tras cambiar legítimamente crypttab o fstab se recarga systemd. Regenerar el initramfs corresponde cuando cambian componentes del desbloqueo temprano de la raíz; no sustituye la recarga y revisión de los montajes de datos.

Los archivos de claves de datos y las copias de crypttab y fstab deben respaldarse fuera del equipo en almacenamiento privado. No publiques esos archivos. Si la raíz resulta irrecuperable y solo ella contenía las claves de datos, reparar o sustituir su vínculo TPM no permitirá recuperar dichas claves.

## Recuperar después de un fallo del TPM

Si vuelve a pedirse la contraseña del disco, úsala para arrancar y ejecuta el diagnóstico. No borres el TPM ni las ranuras existentes para intentar solucionarlo.

El código TPM `0x99d` indica un fallo de comprobación de política. Cuando la política calculada con SHA256/PCR 7 difiere de la del objeto usado por el script, esa configuración no puede liberar la clave con el estado actual. Eso no demuestra por sí solo qué actualización causó la diferencia.

Para investigar cambios de firmware y Secure Boot:

```bash
sudo fwupdmgr get-history
sudo fwupdmgr get-devices
```

`fwupdmgr` puede ofrecer enviar informes y habilitar envíos futuros. Es una elección independiente del diagnóstico; no es necesario aceptarla para consultar el estado. Las salidas pueden incluir números de serie, identificadores y otros datos privados: no las añadas al repositorio.

Compara la versión actual de `dbx` con el historial. Un error histórico no demuestra que la versión actual siga siendo la anterior. Tampoco conviene repetir actualizaciones de firmware o cambiar claves de Secure Boot basándose solo en ese registro. La nota de fwupd sobre fallos al aplicar `dbx` describe un caso posible, no un diagnóstico universal. [Nota de fwupd](https://github.com/fwupd/fwupd/wiki/LVFS-Triaged-Issue:-dbx-does-not-apply-on-reboot).

Cuando el equipo ya esté en un estado de arranque conocido y legítimo, ejecuta otra vez:

```bash
sudo bash scripts/configurar-tpm.sh
```

Si la integración de este proyecto falla, el instalador crea una vinculación nueva con recursos libres y conserva la anterior. Para solicitar expresamente una vinculación nueva aunque la actual pase la prueba:

```bash
sudo bash scripts/configurar-tpm.sh --renovar
```

No renueves automáticamente al detectar cualquier diferencia: hacerlo aceptaría como confiable un estado que todavía no has revisado. Una actualización legítima de firmware, certificados o `dbx` puede requerir renovar; ejecutar solamente `update-initramfs` no modifica la política sellada de un objeto TPM existente.

## Errores y recuperación de una operación interrumpida

| Situación | Qué hacer |
| --- | --- |
| No hay TPM o Secure Boot está desactivado | Revisar hardware, firmware y soporte del sistema antes de cambiar el cifrado. |
| La raíz o crypttab son ambiguos | Revisar el esquema; el instalador se detiene sin elegir otro disco. |
| Un identificador TPM está ocupado | El instalador busca otro libre y lo comprueba de nuevo antes de crear el objeto. |
| No quedan recursos libres | Revisar los metadatos históricos; el proyecto no elimina objetos ni ranuras automáticamente. |
| Contraseña manual incorrecta | Se detiene antes de crear la clave. Comprobar la contraseña de descifrado, no la de escritorio. |
| Falla después de crear el objeto o añadir la ranura | Puede quedar material nuevo sin usar. Guardar el mensaje y revisar el respaldo antes de repetir. |
| Falla después de modificar los archivos | Intenta restaurar los cuatro archivos anteriores y regenerar los initramfs. Si informa de un fallo de restauración o regeneración, no reiniciar hasta revisarlo. |
| Corte de energía o señal no capturable | La restauración automática puede no ejecutarse. Arrancar con contraseña si es posible y revisar archivos, cabecera y estado desde el respaldo privado. |
| El sistema no arranca | Usar un entorno de recuperación compatible y la contraseña; montar la raíz y `/boot`, revisar el respaldo y regenerar el initramfs dentro del sistema recuperado. El procedimiento depende del esquema de particiones y no está automatizado. |

Dentro de cada respaldo, `destinos.txt` registra en orden los cuatro archivos afectados. Cada archivo numerado con sufijo `.original` guarda el contenido anterior; `.ausente` indica que ese destino no existía. `operacion.json` registra el identificador y la ranura seleccionados. `cabecera-luks.img` es la copia de la cabecera previa a añadir la ranura.

La restauración normal de configuración utiliza esos archivos y regenera el initramfs. No requiere restaurar una cabecera completa. Una restauración de cabecera LUKS solo corresponde a una recuperación planificada del disco correcto: puede invalidar cambios posteriores. No se proporciona un comando automático para ejecutarla ni para borrar ranuras u objetos.

Las renovaciones consumen recursos nuevos. Después de varios reinicios satisfactorios, una revisión manual puede identificar objetos y ranuras obsoletos usando los metadatos privados de cada operación. Nunca deduzcas por el número de ranura cuál contiene la contraseña. Conserva y verifica una vía manual de acceso.

## Mantenimiento

Mantén la contraseña de recuperación y los respaldos en un lugar privado accesible fuera del equipo. Antes de actualizaciones de firmware o Secure Boot, comprueba que puedes usarlos. Después de cambios relevantes, prueba el arranque y el montaje de tus datos.

La detección usa el estado local en cada ejecución. No se fijan rutas de discos, UUID, ranuras ocupadas ni identificadores TPM de una máquina concreta en el repositorio. No existe garantía de portabilidad a otro esquema de arranque sin revisar los requisitos.

La herramienta de sellado procede de [tpm2-initramfs-tool](https://github.com/timchen119/tpm2-initramfs-tool). Los scripts la invocan como dependencia y no redistribuyen su implementación.
