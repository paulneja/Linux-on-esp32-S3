# Web, usuarios y sesiones

Sin sudo ni doas, por decisión del usuario. Bash sigue siendo la shell de
usuario; `/bin/sh` sigue siendo BusyBox para los servicios. No se modifica
el kernel ni se necesita hardware adicional.

## Web y datos persistentes

El servidor busca `/home/www/index.html` y `/home/www/cgi-bin/`. Ya no hay
`/www` en rootfs. Los archivos iniciales se conservan comprimidos en
`/usr/share/esp32-home/www.tar.gz` para sembrar una partición home nueva:
no se sirven desde ese archivo ni se pisan cambios del usuario al arrancar.

```sh
nano /home/www/index.html
web-server on
web-server status
web-server off
```

HTTP se ejecuta como `www-data`, no root. El HTML y CGI originales no cambian.
Un CGI nuevo debe ser ejecutable y poder leer sus dependencias como www-data.
No conceder escritura general sobre el contenido ni colocar secretos ahí.
No se agrega autenticación HTTP ni una API de administración remota.

`home-init` siembra únicamente archivos ausentes sobre `/home` JFFS2 montada
en escritura. `S06home-users` lo ejecuta durante el arranque. Tras actualizar
solo rootfs en una instalación existente, ejecutar como root:

```sh
home-users-setup
```

Instala el hook y el perfil inicial sin reemplazar cuentas, contraseñas,
web personalizada o archivos existentes. La migración conserva el estado
activado/desactivado de HTTP y rechaza servicios personalizados en el puerto 80.
El README inicial de `/home/root` comienza con
`Hi, Welcome to Linux on esp32-S3 !!!`.

## Usuarios y permisos

```sh
adduser -s /usr/bin/user-shell alice
su - alice
passwd
exit
```

`adduser` solicita contraseña y crea `/home/alice`, propiedad del usuario,
con modo 0700. Su perfil inicial establece umask 077. `passwd` cambia
contraseñas; `su -` solicita la contraseña de root desde otro usuario.
`addgroup alice GRUPO`, `delgroup alice GRUPO`, `groups alice` administran grupos.
No hay elevación automática por pertenecer a wheel: **sudo/doas no están**.

BusyBox es root:root 4755 en la imagen. Su tabla de applets descarta privilegios
en herramientas ordinarias y permite a su/passwd aplicar sus comprobaciones.
El bit se establece después de modificar los ELF: strip puede eliminarlo.
No convertir shells ni dtach en SUID.

Los permisos Unix funcionan, pero este kernel NOMMU **no tiene aislamiento
de memoria por hardware**. Las cuentas no convierten la placa en un entorno
seguro para ejecutar código hostil o dar acceso a usuarios no confiables.

## Sesiones y trabajos

```sh
session trabajo
# Ctrl-] desconecta de la sesión sin terminar su shell.
session list
session trabajo
# exit dentro de la sesión termina su shell.
```

`session` usa dtach original 0.9, con sockets en `/tmp/dtach-UID` (0700).
Cada sesión es independiente. No es tmux: no agrega paneles ni historial
visual persistente. Para crear sin adjuntar: `session start nombre COMANDO`.
Los nombres admiten letras, números, guion y guion bajo.

Las sesiones usan Dash por defecto (BusyBox sh si no está instalado), para
dejar RAM para adjuntar clientes y lanzar programas. El login principal sigue
en Bash. Bash explícito: `session trabajo /bin/bash -l`. Una consola principal
más dos Bash adicionales agotaron RAM al intentar adjuntar el segundo cliente;
no se recomienda esa combinación. No se impone un límite artificial de procesos.

Para un proceso que no necesita terminal:

```sh
nohup micropython /home/root/task.py > /home/root/task.log 2>&1 < /dev/null &
```

`&` solo lo manda al fondo; nohup evita que SIGHUP lo termine y las
redirecciones lo independizan del terminal. Sobrevive al cierre de COM si
la placa sigue alimentada y el programa de consola no la resetea con DTR/RTS.
Ni dtach ni nohup sobreviven a reinicios o pérdida de alimentación.
Cada shell/proceso consume RAM; no hay un número ilimitado de sesiones.

En este PC Linux se verificó la consola incluida, que abre DTR/RTS juntas
para evitar el pulso de reset producido al cambiarlas por separado:

```sh
/home/paulneja/.local/share/pipx/venvs/esptool/bin/python \
  experiments/mmu-poc/serial-probe.py \
  /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B8E071013-if00 --terminal
```

Pulsar Enter para ver el prompt. Ctrl-] se envía a dtach; Ctrl-X cierra la
consola del PC. No inicia sesión automáticamente ni registra contraseñas.
En otra máquina usar Python con pySerial 3.x y el puerto correspondiente.
La apertura atómica es POSIX; no se promete el mismo comportamiento en Windows
ni con otro programa que cambie las líneas de reset. La implementación usa
dos hooks internos de pySerial, cubiertos por prueba local: revisar al actualizarlo.
pySerial documenta este riesgo de pulsos al abrir el puerto en su
[API de open()](https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial.open).

## Construcción y pruebas

dtach: commit `b027c27b2439081064d07a86883c8e0b20a183c9` de
<https://github.com/crigler/dtach>. Guardar el archivo codeload de ese commit
como `out/programs/dtach-b027c27.tar.gz`; `build-dtach.sh` valida SHA256.
Usa la implementación portable de PTY y libfork; no reemplaza libc.

```sh
bash experiments/mmu-poc/programs/build-netcat.sh
bash experiments/mmu-poc/programs/build-dtach.sh
python3 experiments/mmu-poc/programs/image-profiles.py build --profile all \
  --output experiments/mmu-poc/out/programs/rootfs-home-users-ready.cramfs
python3 experiments/mmu-poc/programs/test-home-users.py
```

Los perfiles experimentales incorporan dtach. El defconfig normal incorpora
la migración web y usuarios; construir ese defconfig solo no incorpora todavía
el port experimental de dtach/libfork. No confundir ambos pipelines.

`test-home-users-board.py PORT` es una prueba física explícita: crea y elimina
usuarios `hwchecka/b`, verifica contraseñas sin registrarlas, prueba HTTP local,
dos sesiones y cierre/reapertura del COM. Rechaza usuarios preexistentes.
No ejecutarla simultáneamente con screen u otra consola. No flashea.

El flash se limita a rootfs en `0x540000`; `/etc` y `/home` se conservan.
El manifiesto JSON junto a la imagen contiene tamaño, espacio libre y SHA256.

## Estado físico verificado el 2026-09-05

Flasheada `rootfs-home-users-ready.cramfs`: 7.811.072 bytes, 53.248 libres
(52 KiB), SHA256
`e20728040823087bc694818dc2e82e633af4cb785324c297dcd928e576fd5b0e`.
Esptool verificó el hash escrito. No se reparticionó ni se flashearon /etc,
/home o el kernel. No hay sudo ni doas en la imagen.

Comprobado en la placa:

- README correcto, ausencia de /www y contenido web original intacto.
- Dos usuarios temporales con UID y home propios, modo 0700; acceso denegado
  a shadow, README de root y home ajena; escritura en la home propia.
- Alta/baja de membresía de grupos; su desde un usuario no privilegiado
  acepta la contraseña correcta y rechaza una incorrecta.
- HTML por HTTP idéntico al archivo local; CGI devuelve JSON; www-data
  puede leer la web pero no escribirla ni leer shadow. HTTP quedó apagado,
  como estaba antes de las pruebas.
- Un trabajo dtach de usuario común finaliza y escribe en su propia home.
- Dos sesiones Dash simultáneas se crean, adjuntan y separan con Ctrl-].
- Una sesión Bash se creó, adjuntó y ejecutó builtins en una prueba anterior.
  Dos Bash adicionales agotaron la RAM al adjuntar el segundo cliente.

La prueba inicial confirmó un reset: cambió el boot_id al reabrir COM.
Se corrigió el ayudante del PC para aplicar DTR/RTS con un único TIOCMSET
y desactivar HUPCL. Con esa apertura, la suite completa terminó correctamente:
mismo boot_id, dos sesiones con variables independientes conservadas tras
reconectar, salida limpia de ambas, y sesión Bash adicional con id correcto.
El error de sintaxis `&;` estaba en el test y también se corrigió.

Una prueba adicional cerró y reabrió COM tres veces, comprobando en cada
paso el boot_id y el PID vivo de un trabajo nohup. El trabajo esperaba una
señal por archivo: solo se permitió terminar después de las tres reconexiones.
Así se comprueba que no había terminado antes de cerrar el puerto.

Regresiones físicas de la imagen instalada: process-test 10/10, recuperación
del respaldo del padre 0 → 124 → 0 KiB, Bash, Dash, MicroPython con forks e IPC,
GNU Make -j2, socat/nc por TCP/UDP/socket Unix, hush login y mmu-run A/B/A/B
(103/1006/106/1012) y Fibonacci(20)=6765: aprobados. Los scripts de Make/red/login
se ejecutan con Dash, como indican sus shebangs; BusyBox sh no admite todas
las opciones que usan esos tests.

Jobq aprobó concurrencia limitada a dos, rechazo por presupuesto de memoria,
exec fallido y timeout. El modo `--terminal` se probó físicamente: crear una
sesión, guardar una variable, Ctrl-], Ctrl-X, abrir otra consola y volver a
adjuntar; la variable se conservó. `exit` terminó la sesión y se liberó COM.

Finalmente se ejecutó `sync; reboot` intencionalmente: siete archivos persistentes
(Sudoku, README, HTML, CGI, passwd, shadow e inetd.conf) conservaron sus hashes.
La home de root siguió en 0700, BusyBox en 4755, HTTP apagado, taint 0 y
process-test volvió a aprobar 10/10 después del arranque. Las sesiones de
prueba se terminaron; ningún programa se configura para arrancar oculto.

Última lectura: no quedan usuarios hwchecka/b ni sesiones de prueba,
`tainted=0`. `/home/root/sudoku.py` conserva SHA256
`7864439fb085fae1e2c09e38b9f666b2672b56f795947659cdfc6a0113c9173f`.
Registros finales en `out/programs/home-users-atomic-com.log`,
`com-reconnect-three.log`, `home-users-regressions.log` y
`home-reboot-final.log`, junto con `flash-home-users-ready.log`.
Los registros anteriores conservan los fallos
de desarrollo, no deben confundirse con la validación final.
