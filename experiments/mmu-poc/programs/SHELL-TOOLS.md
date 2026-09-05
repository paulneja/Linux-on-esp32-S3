# Bash, netcat y socat

Construcción local para Xtensa CALL0 FDPIC y `6.11.0-forkbank #7`.
No activa CONFIG_MMU ni convierte el backend experimental en fork universal.

## Componentes

- Bash 5.2.37, `/bin/bash`: enlazado con libfork y ncurses ya instalada.
  Readline integrado, historial, arrays, regex, jobs y sustitución de procesos.
  Usa malloc de libc, LTO y optimización por tamaño. La ayuda completa de
  builtins vive en `/usr/share/bash/helpfiles`, comprimida por cramfs, y sigue
  disponible mediante `help`. Sin traducciones ni extensiones de builtins
  mediante `enable -f`; se evita exportar todo Bash/Readline para esa función.
  Esto no deshabilita scripts ni ejecución de programas externos.
- BusyBox 1.36.1: conserva su configuración y añade solamente NC, NETCAT,
  NC_SERVER, NC_EXTRA y NC_110_COMPAT. `/bin/nc` y `/bin/netcat` son enlaces
  a BusyBox, con TCP, UDP, escucha y timeout. No se instala otra copia de nc.
- Socat 1.8.1.3, `/usr/bin/socat`: libfork, TCP/UDP, sockets Unix, EXEC,
  SYSTEM, PTY, pipes y archivos. Sin OpenSSL, Readline, trazado de syscalls
  ni analizador filan; mensajes desde NOTICE hasta FATAL. SCTP, DCCP,
  VSOCK, namespaces y colas POSIX se omiten porque el kernel no los habilita.
- GNU Make 4.4.1 y MicroPython 1.26.0 se conservan sin sustituirlos.

Los límites del backend siguen vigentes: 512 KiB privados por banco,
sin fork multihilo ni copy-on-write. La compatibilidad de un programa
se confirma con pruebas físicas, no solo con que enlace.

## Reproducción

```sh
bash experiments/mmu-poc/programs/fetch-shell-tools.sh
bash experiments/mmu-poc/programs/build-bash.sh
bash experiments/mmu-poc/programs/build-netcat.sh
bash experiments/mmu-poc/programs/build-socat.sh
bash experiments/mmu-poc/programs/make-shell-tools-image.sh
```

Fuentes y hashes: [Bash en Buildroot](https://raw.githubusercontent.com/buildroot/buildroot/master/package/bash/bash.hash)
y [socat en Buildroot](https://raw.githubusercontent.com/buildroot/buildroot/master/package/socat/socat.hash).
Las versiones y SHA-256 están fijadas en `shell-tools.sha256`; no se desactiva
la validación TLS. BusyBox se construye en una copia del árbol original
ya parcheado por Buildroot, sin modificar ese árbol ni su configuración.

La fase inicial deja `/bin/sh` y el `/etc/passwd` persistente sin cambios.
El empaquetador no flashea, valida cramfs y rechaza imágenes que excedan
0x780000 bytes. No toca imágenes estables, kernel, `/etc` ni `/home`.

## Tamaños y comprobaciones locales

Primera imagen sin optimizaciones adicionales: 8142848 bytes, rechazada
por exceder la partición en 272 KiB. La imagen seleccionada mide
**7860224 bytes**, con **4096 bytes libres**. Es muy poco margen para
añadir más programas; no se debe aumentar la partición sin planificar
el respaldo y la distribución de datos persistentes.

SHA-256 de `rootfs-shell-tools.cramfs`:
Primera versión: `1633b184fb5aa3ef8b4e07a581f4b21620782162bea76606d50a8a5a4ad8c9c1`.
Con caché de PIDs bajo demanda:
`13a96d662b6cfc2b6ad13fba491db4a716848692b16f97c45b58aadc71b13733`.

SHA-256 de los ejecutables:

- Bash inicial, antes del ajuste de caché:
  `abe8157efd57a58eef2ee1b060bb2af0e15c25fc942606660c8ab4e3cbbc0bce`.
- Bash corregido: `251387b427c5429eaed6fc6aa38c5abb0819416b8670f0b3d77c7b8e80a74598`.
- Socat: `96df94995b417aa17152f4c396b859bb05925d92ae54266abcab3fc6bddcb79d`.
- BusyBox: `d1fb4852ec83f146d3ff67de4082095058c128db63a669d1c4bfd93dce822925`.

`bash-test.sh` pasa en Bash del host; no cuenta como validación de la placa.
`network-tools-test.sh` limita todas las escuchas IP a loopback y comprueba
transferencia de archivos, TCP con tres clientes, UDP y sockets Unix.

## Primera prueba física y reserva de estados de procesos

`board-shell-tools.log`: los tres binarios arrancan. Socat y nc pasan
transferencia de archivos, TCP con tres clientes (fork + EXEC), UDP y Unix.
Atfork, MicroPython completa y MMU A/B/A/B siguen funcionando.

Bash pasa arrays, regex, aislamiento, pipelines y PIPESTATUS, pero la suite
combinada falla intentando reservar 524288 bytes. El kernel informa que no
hay un bloque contiguo suficiente; no se debe describir ese log como limpio.
La sustitución de procesos y read/mapfile por separado sí pasan.

`jobs.c:bgp_resize` reserva anticipadamente hasta MAX_CHILD_MAX entradas
de 16 bytes (32768 * 16 = 512 KiB) al guardar estados de procesos terminados.
`bash-pid-cache.patch` empieza con las 512 entradas originales (8 KiB) y
duplica la capacidad solo al llenarse. Conserva el límite y los índices;
no reduce el número máximo de procesos ni simula resultados de wait.
`test-bash-pid-cache.py` compila la función parcheada real en un fixture con
ASan/UBSan: pasa reserva inicial, crecimiento, conservación de 32768 estados
y retorno circular al inicio sin una reserva adicional. LeakSanitizer se
deshabilita porque el sandbox usa ptrace; ASan/UBSan permanecen habilitados.

## Prueba física después de corregir la caché

`board-shell-tools-pid-cache.log`: Bash pasa dos suites completas consecutivas,
incluida la secuencia que fallaba. Pasa modo interactivo con Readline (`bind`),
ayuda separada (`help printf`) e historial. Pasa cargar `/etc/profile` en
modo POSIX y ejecutar `$(id -u)` sin la recursión del login BusyBox.

Pasan otra vez red (TCP, UDP, Unix, fork+exec), Make -j2, MicroPython completa,
ambas suites de fork (5/5 cada una) y atfork. Tainted=0, sin WARNING/BUG/OOM,
panic ni fallos de asignación en dmesg. RAM libre 1708 KiB, disponible 1600 KiB
antes de la prueba de perfil. Kernel sin cambios.

Para preparar la prueba de arranque con Bash como sh:

```sh
bash experiments/mmu-poc/programs/make-shell-tools-image.sh --bash-as-sh
```

Produce `rootfs-bash-sh.cramfs` sin sobrescribir `rootfs-shell-tools.cramfs`.
Solo cambia el enlace `/bin/sh`, de BusyBox a Bash. No cambia el passwd
persistente: al invocarse como `sh`, Bash usa modo POSIX; `bash` mantiene
su modo normal. `/bin/busybox sh` sigue disponible como shell de recuperación.
Tamaño 7860224 bytes, SHA-256
`934058fca9fec83e8bb8bdb8762d7caf422d3b8abb659f13493a5b268bdf7473`.

## Reemplazo global de sh: rechazado en la prueba física

`board-bash-sh.log` confirma login con `$0=-sh`, Bash 5.2.37 y `/bin/sh -> bash`.
También registra un fallo real de asignación de 64 KiB en `default.script`
(DHCP) al ejecutar los servicios y el login con Bash. La shell interactiva
tiene 376832 bytes privados por banco; después de las primeras órdenes,
RAM libre 968 KiB y disponible 744 KiB, frente a 1708/1600 KiB en la fase A.
No se acepta como configuración predeterminada por esa regresión.

Se selecciona de nuevo `rootfs-shell-tools.cramfs` (Bash corregido, socat y nc,
pero `/bin/sh -> busybox`). La opción `--bash-as-sh` se conserva únicamente
para reproducir el experimento; no usarla como imagen estable.
Los datos persistentes y el kernel no se cambiaron.

El lector COM se adaptó a las secuencias CSI de Readline: antes podía informar
timeout aunque Bash hubiera ejecutado la orden correctamente. `test-serial.py`
comprueba que tanto BusyBox como Bash se reconozcan y que el eco de la orden
no se confunda con su resultado. Este problema del lector es independiente
del fallo de memoria confirmado en DHCP.

## Estado final instalado

Restaurada y verificada por esptool `rootfs-shell-tools.cramfs`, SHA-256
`13a96d662b6cfc2b6ad13fba491db4a716848692b16f97c45b58aadc71b13733`.
Registro: `flash-shell-tools-final.log`; consola: `board-shell-tools-final.log`.

Comprobados `/bin/sh -> busybox` y las rutas reales de Bash, socat, nc y
netcat. Pasan otra vez Bash completa, red TCP/UDP/Unix con fork+exec,
MicroPython completa, Make -j2 y MMU A/B/A/B. Los tres hashes de ejecutables
coinciden con el host. Wi-Fi scan devuelve 5 redes. Tainted=0, sin
WARNING/BUG/OOM/panic ni fallos de asignación registrados. RAM libre
1668 KiB y disponible 1564 KiB después de las pruebas. Puerto COM cerrado.

Para entrar en Bash se puede ejecutar `bash`, y volver con `exit`.
No se ha cambiado la shell de login persistente ni el intérprete de servicios.
