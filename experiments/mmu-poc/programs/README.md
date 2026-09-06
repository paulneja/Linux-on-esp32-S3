# Programas nativos: resultados del 2026-09-05

Para construir el sistema completo desde fuentes limpias, ver
[la ejecución integrada](../../../build/README.md). Los comandos y hashes
de este documento describen las construcciones incrementales anteriores.

Actualización posterior: [userspace, memoria y perfiles](USERSPACE-UPGRADE.md).
Web editable, usuarios y sesiones: [uso y verificación](HOME-USERS.md).
Ese documento describe el kernel nuevo, Bash solo para el usuario y la imagen
actual. Los resultados y hashes siguientes se conservan como historial.

Tareas programadas: [cron](CRON.md), con la imagen y pruebas más recientes.

Trabajo local en `mmu-poc`, sin push. Kernel físico `6.11.0-forkbank #7`.
Estos programas usan Linux FDPIC y el backend de fork del kernel, no el
intérprete de ELF freestanding de `mmu-run`.

## Selección actual

- `/usr/bin/dash` 0.5.12 y `/usr/bin/make` 4.4.1, sin sufijos experimentales.
  `/bin/sh` sigue siendo BusyBox. Las suites usan los nombres reales.
- Bash 5.2.37, socat 1.8.1.3 y nc/netcat de BusyBox están integrados en
  `rootfs-shell-tools.cramfs`. Ver [construcción y pruebas](SHELL-TOOLS.md).
  Bash funciona como `/bin/bash`; reemplazar globalmente `/bin/sh` produjo
  presión de RAM y un fallo en DHCP, por lo que se conserva BusyBox para sh.
- `/usr/bin/micropython`: port Unix de MicroPython 1.26.0, 128 KiB de GC
  divididos en cuatro heaps, setjmp de libc para la ABI FDPIC.
  No es CPython ni se instala con el nombre `python`.
- CPython 3.12.5: compilado y medido, pero **descartado por el usuario**.
  Nunca fue flasheado. No continuar ni incluirlo en las imágenes normales.
- Neovim 0.11.4: **experimento detenido por decisión del usuario**.
  No incluirlo en la imagen normal. Se compiló el código real del editor
  con PUC Lua 5.1, sin JIT y sin el runtime completo; el ejecutable tenía
  5.18 MiB de código/constantes y unos 293 KiB de datos/BSS. La imagen
  temporal requirió omitir servicios. No llegó a funcionar en la placa:
  `nvim --version` y ejecución headless abortaron con SIGABRT.

## MicroPython: pruebas físicas

`out/programs/board-programs.log` registra:

- Enteros grandes, double, struct; JSON, regex y SHA256.
- Escritura/lectura en `/tmp`, import de un módulo `.py` desde ese directorio.
- Excepciones, generadores y 100 ciclos de asignación/recolección.
- UDP por loopback. El port Unix espera sockaddr binario obtenido con
  `getaddrinfo`, no una tupla estilo CPython. El test inicial se corrigió.
- Cinco forks por suite: heap Python independiente, pipes, waitpid y exit 7.
- Lanzamiento de Dash con pipeline mediante `os.system`.
- Primera suite completa: 1.56 s; tres repeticiones adicionales completas.
- Kernel informó 307200 bytes privados por fork de MicroPython.
- Dash: suite completa en 2.04 s; Make `-j2`: 2.70 s.
- Tests estático y dinámico de fork: 5/5 cada uno; corregido `execlp` para
  que el autotest también funcione cuando se invoca por PATH.
- `tainted=0`; tras repeticiones, RAM libre 1812 KiB, disponible 1668 KiB.

La extensión `posix` es propia: fork, waitpid, pipe, read/write, close,
_exit. `read` tiene un límite explícito de 4096 bytes por llamada.
No se promete compatibilidad general de módulos CPython, pip, SSL o threads.

## Resultado reutilizable del intento con Neovim

La uClibc NOMMU devuelve EPERM al registrar atfork. Libuv exige esa
operación. `fork-compat.c` ahora mantiene hasta 32 registros y ejecuta:

1. prepare en orden inverso;
2. clone real sin CLONE_VM;
3. parent o child en orden de registro; también parent si clone falla.

Se probaron orden, independencia y límite del registro en host y en ESP32
(`board-neovim-atfork.log`). Se probó además clone fallido y preservación
de errno mediante un wrapper de syscall en host. **Esto no fue suficiente
para arrancar Neovim**: el aborto persistió y no se terminó de diagnosticar.

No habilita fork multihilo: el kernel sigue rechazándolo. Tampoco ofrece
reparación general de locks heredados ni descarga de DSOs con callbacks.

Se compilaron libuv 1.50.0, Lua 5.1.5, Luv 1.50.0-1, LPeg 1.1.0,
Tree-sitter 0.25.6, Unibilium 2.1.2, utf8proc 2.10.0 y libiconv 1.17.
Se preparó getifaddrs y libutil desde uClibc 1.0.48 por separado,
sin sustituir la libc del sistema. **Estas dependencias no están validadas
completamente en hardware.** `uv-test.c` está compilado, no ejecutado.

Se conservan scripts, parches, fuentes e imágenes experimentales para
reproducir el trabajo; no se borraron las imágenes estables del repositorio.

## Construcción de la imagen seleccionada

```sh
bash experiments/mmu-poc/fork/build-test.sh
bash experiments/mmu-poc/programs/build-atfork-test.sh
bash experiments/mmu-poc/programs/build-micropython.sh
bash experiments/mmu-poc/programs/make-image.sh
```

Requiere los binarios `out/real-bins/dash` y `make` de `fork/real/build.sh`.
Produce `out/programs/rootfs-programs.cramfs`; comprueba tamaño y cramfs.
Los scripts de construcción no flashean. Neovim/CPython quedan excluidos.

## Reducción de metadatos ELF

`make-image.sh` ahora aplica `strip-rootfs.py` a una copia de los archivos,
antes de generar cramfs. Usa el strip de Xtensa con `--strip-unneeded` y
elimina `.xt.prop` / `.xt.lit` no asignadas en memoria. No son las secciones
de código ni los literales usados durante la ejecución. Se conservan las
secciones asignadas, símbolos dinámicos, relocaciones y fixups FDPIC.
La comprobación compara byte a byte las secciones asignadas y los program
headers, incluyendo offsets XIP, permisos y tamaño de stack. Si cambiaran,
el archivo original se conserva: ocurre con `fib.elf` y `timeout.elf`, donde
strip intentaría eliminar un segmento PT_LOAD vacío.

Para reducir una imagen existente sin reconstruir ni sobrescribirla:

```sh
bash experiments/mmu-poc/programs/compact-image.sh
```

Resultado: `out/programs/rootfs-programs-stripped.cramfs`, **6836224 bytes**,
frente a 7819264 originales. Se recuperan **983040 bytes (960 KiB)** y quedan
**1028096 bytes (1004 KiB)** libres en la partición de 0x780000 bytes.
SHA256: `adbae72646ce9048999bd2e9f26a8ab50d72e13f510b7a23459ebb28667acde6`.
La reconstrucción completa con `make-image.sh` produjo exactamente ese hash.

Verificación local: mismos 657 paths, modos y destinos de enlaces; 143 ELF
cambiaron, manteniendo su información de ejecución, y todos los archivos
no ELF permanecieron idénticos. Una segunda pasada eliminó 0 bytes.
Se conservan la imagen anterior y los binarios de construcción para debug;
solo la copia instalada pierde metadatos de análisis/depuración.

**Verificada en placa:** flasheada por COM a 0x540000 con comprobación de
hash (`out/programs/flash-stripped.log`). Kernel y particiones de datos
sin cambios. En `board-stripped.log` pasan atfork, ambas suites de fork
(5/5 cada una), Dash, GNU Make -j2 y MicroPython completa. También pasan
MMU A/B/A/B y Fibonacci(20)=6765; Wi-Fi scan devuelve 5 redes. Después de
las pruebas: tainted=0, sin WARNING/BUG/OOM/panic en dmesg, RAM libre
1724 KiB y disponible 1568 KiB. Esto libera flash, no 960 KiB de RAM.
La imagen todavía no incorpora Bash, socat ni nc; `/bin/sh` no cambió.

## Restauración después de detener Neovim

Se flasheó y verificó `rootfs-programs.cramfs`, 7819264 bytes (44 KiB libres),
SHA256 `36bc317616e4876ed5143dd524bcfe4b4783e959191a67c5ad992df91da4978b`.
Kernel y particiones de datos no se sustituyeron. Registro de flash:
`out/programs/flash-restore-programs.log`.

`board-restored.log` registra atfork, MicroPython, Dash, Make y ambos
tests de fork completos. También pasó el runtime MMU A/B/A/B y el escaneo
Wi-Fi devolvió 6 BSS. Los hashes de MicroPython/libfork/atfork-test se
verificaron en la placa.

**Incidencia adicional pendiente:** ejecutar `$(cat /proc/sys/kernel/tainted)`
en la shell interactiva de login BusyBox generó una cadena de procesos `sh`
y dos eventos OOM (sh e id); el comando terminó y los procesos temporales
desaparecieron. El log no debe describirse como libre de OOM. El código de
hush NOMMU conserva argv[0] para reejecutarse, que en esa sesión es `-sh`,
y vuelve a procesar `/etc/profile`: es la explicación probable de la
recursión, pendiente de una corrección y una prueba aislada. No se cambió
`/bin/sh`. Las sustituciones equivalentes dentro de Dash pasan su suite.
Se reinició después para dejar un arranque limpio; comprobaciones finales
en `board-final.log`.
