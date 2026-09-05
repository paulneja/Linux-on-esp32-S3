# Userspace, memoria y perfiles

## Recuperación del backend de fork

`fork/build-kernel-reclaim.sh` aplica el backend base, el ajuste del scheduler
y `fork/reclaim.patch` al árbol privado de construcción. También aplica
`fork/quiet-trace.patch`: las trazas de forks exitosos están apagadas por
defecto. Produce `out/real-bins/xipImage-fork-quiet` y no flashea.

Cada región mantiene una lista circular de sus bancos. Cuando queda uno:

1. Se restaura el contenido del superviviente si otro banco estaba residente.
2. Se retira de la lista que recorre el cambio de contexto.
3. Se liberan sus páginas de respaldo. Permanece un descriptor pequeño hasta
   que se desmapea la VMA, para no invalidar referencias durante asignaciones
   de un fork que puedan dormir. Un fork posterior vuelve a crear las páginas.

La exclusión mediante IRQ es válida **solo para el kernel UP actual**.
No es COW, no aporta protección de memoria, no admite fork multihilo y se
mantiene el límite de 512 KiB privados por fork. No cambiar esas restricciones
como efecto lateral de esta optimización.

Se corrigió también la detección de mm compartido: `mm_users` incluye referencias
temporales de `/proc` y ptrace, no solo tareas. Si hay referencias adicionales,
se recorre la lista de tareas bajo RCU y se rechazan otros usuarios reales
del mismo mm. Esto evita que medir un proceso provoque falsos fallos de fork.

Contadores nuevos:

- `/proc/meminfo`: `ForkShadow` son páginas de respaldo actualmente asignadas,
  incluidas las asignaciones en curso; `ForkRecovered` es el volumen acumulado
  de respaldos del superviviente liberados, no RAM simultáneamente libre.
- `/proc/PID/status`: `ForkShadow` es el respaldo de ese mm; `PrivateRAM` suma
  las regiones privadas `VM_MAPPED_COPY` hasta `vm_top`. Excluye código XIP,
  memoria del kernel, estructuras administrativas y bibliotecas compartidas.

`test-reclaim.py` compila las funciones reales con un simulador UP de
asignación y listas: restaura al propietario, prueba 100 ciclos anidados,
inyecta fallos de página y la salida de un hermano durante una asignación.
ASan/UBSan comprueban el código del host; no sustituyen las pruebas físicas.
`process-test` comprueba además salida, exec, FD_CLOEXEC, offsets compartidos,
dup2, exec fallido, SIGPIPE/EPIPE, popen, huérfanos y asignación posterior.

## Shell del usuario, separada de los servicios

`/bin/sh` sigue apuntando a BusyBox; los scripts de arranque no se convierten
a Bash. `set-user-shell bash` cambia **solo root** en el `/etc/passwd` persistente
a `/usr/bin/user-shell`, con respaldo en `/etc/passwd.before-user-shell`.
La sustitución de passwd es mediante archivo temporal y rename; un directorio
de bloqueo evita dos cambios simultáneos. No cambia contraseñas ni otros usuarios.

`user-shell` ejecuta Bash para el usuario si existe. En un perfil sin Bash
usa BusyBox, para que cambiar de imagen no deje un login roto.
Para revertir: `set-user-shell sh`. Requiere volver a iniciar sesión.

La corrección de hush conserva el argv[0] original para el login y `$0`,
pero elimina el prefijo `-` **solo del nombre usado para reejecuciones internas
NOMMU**. Así las sustituciones/heredocs no vuelven a cargar el perfil.
`hush-login-test.sh` comprueba un login real `-sh`, un perfil temporal cargado
una vez, sustituciones anidadas y conservación de `$0`.

## Mediciones

```sh
programbench -- /bin/bash /usr/share/program-tests/bash-test.sh
programbench -t 20 -- /usr/bin/make -j2
```

El hijo usa ptrace para detenerse inmediatamente después de `exec`, antes de
ejecutar código de usuario. Se mide `PrivateRAM` en ese punto y luego se libera
el trazado. Se muestrea al proceso y `/proc/meminfo`, solicitando intervalos
de 10 ms. La lectura de `/proc` también consume tiempo y RAM.

Si el medidor posee el terminal en primer plano, se lo cede temporalmente
al grupo del hijo y lo restaura al terminar. Sin esa operación, un ioctl de
terminal puede detener al hijo con SIGTTOU: no era un cuelgue de socat.
No se toma el terminal de un trabajo ajeno. La cola, en cambio, ejecuta
trabajos no interactivos; detecta hijos detenidos y los termina con un
diagnóstico en lugar de esperar silenciosamente hasta el timeout.

- `elf_bytes`: tamaño del archivo ejecutado; **no** el coste comprimido ni el
  de sus bibliotecas. Los enlaces nc/netcat usan el ELF completo de BusyBox.
- `exec_private_kib`: regiones privadas al terminar el cargador del kernel;
  todavía no incluye toda la inicialización del runtime.
- `sampled_peak_private_kib`, `sampled_own_shadow_kib`: máximos observados del
  proceso principal. Pueden perder picos cortos; no suman sus descendientes.
- `global_shadow_delta_kib`: máximo muestreado global menos el valor inicial;
  incluye descendientes y cualquier servicio concurrente.
- `global_recovered_kib`: volumen global liberado durante la ejecución.
- `launch_ms`: creación del hijo, exec y observación del stop.
- `instrumented_run_ms`: tiempo de pared bajo muestreo, no tiempo de CPU puro.
- `-1` significa dato no disponible, no cero. Se conserva el estado de salida.

En el primer fork de una región aún no compartida se asignan **dos** respaldos
(padre e hijo), además del original y de metadatos del proceso. Por ello un
proceso con P KiB privados puede requerir aproximadamente **2P KiB adicionales**
para su primer fork. En una familia que ya está compartiendo esa región basta
el respaldo adicional del nuevo hijo. El registro `fork-bank` muestra P real
en cada fork exitoso; no deducirlo del tamaño del archivo ELF.

Desde el kernel #11, ese registro es opcional, para no llenar la consola ni
el buffer de dmesg durante el uso normal. Para una medición deliberada:

```sh
echo Y > /sys/module/nommu/parameters/fork_bank_trace
# Ejecutar la carga a medir
echo N > /sys/module/nommu/parameters/fork_bank_trace
```

Requiere root y vuelve a N al reiniciar. No cambia el nivel global de printk,
no oculta errores y no desactiva `/proc` ni la recuperación de memoria.
Para activarlo desde el arranque existe `nommu.fork_bank_trace=1` como
parámetro del kernel; la imagen normal no lo incluye.

### Datos medidos

[MEASUREMENTS.csv](MEASUREMENTS.csv) registra una ejecución representativa de
cada carga en el ESP32, kernel #10, con la shell ligera durante las mediciones.
Los tiempos no sirven para comparar velocidad entre programas: las cargas son
distintas y están instrumentadas. La suite interactiva de Bash se probó también
por separado dentro del login real.

| Programa | ELF instalado | RAM al exec | Pico privado observado | Respaldos adicionales de un primer fork, hasta |
|---|---:|---:|---:|---:|
| Bash | 780.692 B | 140 KiB | 276 KiB | 552 KiB |
| Dash | 94.796 B | 84 KiB | 140 KiB | 280 KiB |
| Make | 195.360 B | 92 KiB | 216 KiB | 432 KiB |
| MicroPython | 311.788 B | 104 KiB | 308 KiB | 616 KiB |
| socat | 242.092 B | 108 KiB | 184 KiB | 304 KiB |

La última columna se calcula como 2P a partir de P observado en los registros
reales de fork, no del pico de RAM ni de la lectura muestreada de ForkShadow.
Excluye estructuras de proceso y tablas. En el login interactivo, Bash usó
344–380 KiB privados según el estado de Readline y las variables de las pruebas.
La RAM al exec no es esa huella interactiva final.

nc utiliza el mismo ELF de BusyBox, de 846.033 B: no hay un segundo ejecutable
de ese tamaño. En `--help` se observaron 40 KiB iniciales y 76 KiB privados,
sin fork. TCP/UDP se comprueban con la suite de red, no con la ayuda.

## Cola de trabajos

```sh
jobq -j 2 -m 256 -r 512 -w 30 -t 60 -- \
  /usr/bin/make -j1 ::: /bin/bash /home/tarea.sh
```

`:::` separa comandos, sin interpretación implícita por una shell. `-j`
limita trabajadores; `-m` declara el presupuesto de RAM por trabajo en KiB;
`-r` deja una reserva; `-w` limita la espera de admisión y `-t` el tiempo de
cada trabajo. Hasta 64 trabajos y 32 trabajadores por invocación.

La admisión consulta MemAvailable, reserva hasta dos veces la RAM privada de
la cola para un fork y el presupuesto aún no consumido de trabajos activos.
Si no alcanza, espera. ENOMEM/EAGAIN reales se reintentan con límite; jamás
se devuelve un fork ficticio. Informa START/WAIT/EXIT y propaga fallos.

Es un control cooperativo, **no una garantía contra OOM**: los trabajos pueden
superar su presupuesto, otros servicios consumir memoria y NOMMU requiere
a veces bloques contiguos. Los trabajos no deben daemonizarse ni abandonar
su grupo de procesos si quieren quedar cubiertos por la cancelación/timeout.

## Selección y construcción

```sh
python3 experiments/mmu-poc/programs/image-profiles.py plan --profile bash-red
python3 experiments/mmu-poc/programs/image-profiles.py plan --profile python-automatizacion
python3 experiments/mmu-poc/programs/image-profiles.py plan --programs bash,micropython
python3 experiments/mmu-poc/programs/image-profiles.py build --profile all
# Opcional: reconstruir los programas seleccionados después de mostrar la estimación
python3 experiments/mmu-poc/programs/image-profiles.py build --profile all --compile
```

Requiere el toolchain y la imagen base de este experimento. `plan` no compila;
usa costes medidos incluidos en `profile-costs.json`. Son marginales de cramfs
XIP: alineación y deduplicación impiden prometer una suma exacta. `build`
comprueba el tamaño real contra **0x780000**, la integridad cramfs y genera
un JSON de inventario/hash. Rechaza sobrescrituras salvo `--replace` explícito.
No flashea ni modifica las particiones `/etc` y `/home`.

Todos los perfiles conservan los servicios originales, BusyBox/nc, libfork,
las herramientas MMU y los diagnósticos de procesos. La selección controla
el MicroPython **nativo**; el antiguo payload experimental de mmu-run se conserva.
No incluyen CPython ni Neovim. Los programas mantienen sus nombres y rutas.
Make y MicroPython incluyen Dash para sus pruebas y scripts auxiliares;
esa dependencia aparece también al resolver selecciones personalizadas.

## Reducción y decisiones de compilación

`compare-size.sh` construye Dash y Make con `-Os`, `-Oz`, `-Oz -flto`, sin
sustituir automáticamente la variante instalada. Los constructores de
BusyBox y MicroPython aceptan `OPT_VARIANT`; los resultados físicos deciden
qué usa el generador, no solo el menor tamaño.

`strip-rootfs.py --section-headers` elimina directorios de secciones y
metadatos offline de una copia. Verifica cada program header y **todos sus
bytes de segmento**, permitiendo cambiar únicamente e_shoff/e_shentsize/
e_shnum/e_shstrndx del encabezado ELF. Si cambian offsets, permisos, tamaños,
código, datos, relocaciones o tablas dinámicas, conserva el original.
Los originales para depuración permanecen en out; fib.elf y timeout.elf se
conservan porque strip intenta quitarles un PT_LOAD vacío.

`test-strip-sections.py` prueba la equivalencia y que corromper un byte de
código se detecta. Los ejecutables y bibliotecas instalados deben volver a
probarse en la placa después del empaquetado.

Resultados de variantes (tamaño de archivo antes de quitar el directorio de
secciones; mismas funciones configuradas):

| Programa | -Os | -Oz | -Oz + LTO | Decisión física |
|---|---:|---:|---:|---|
| Dash | 95.956 B | 95.956 B | 90.924 B | Conservar -Os: LTO falló en sustituciones con programas externos |
| GNU Make | 202.032 B | 202.032 B | 196.464 B | Conservar LTO: pasó -j2, dependencias, dry-run y errores |
| MicroPython | 312.948 B | 312.948 B | 298.328 B | Conservar -Os: LTO produjo SIGSEGV al arrancar |
| BusyBox con nc | 847.192 B | No medido | 843.288 B | Conservar -Os: LTO rechazó inittab al arrancar |

MicroPython con LTO y `-fno-semantic-interposition` dio 298.344 B: no mejoró
el tamaño y no se seleccionó. Bash y socat conservan sus variantes LTO que
ya funcionaban; las suites se repiten tras el empaquetado.

## Resultado físico y artefactos finales

Pruebas del 5 de septiembre de 2026, ESP32-S3 N16R8 conectado por COM.
Esta batería completa se realizó con kernel `6.11.0-forkbank #10` y el perfil completo.
El ajuste posterior #11 de trazas conserva ese rootfs; véase
[UPGRADE.md](../UPGRADE.md#ajuste-posterior-de-consola) para su hash y pruebas.
Los artefactos y logs de `out/` son locales e ignorados por Git; no se publicaron.

| Artefacto | Bytes | SHA256 |
|---|---:|---|
| `out/real-bins/xipImage-fork-reclaim` | 3.432.520 | `c74c636a9b3fb1e8e4a2c92782df033863fe928f19022aa926deba351d1ba869` |
| `out/programs/rootfs-upgrade-final.cramfs` | 7.786.496 | `596bc07182e7db0e5610c0a8ecf1b63e3d84f23feef1846043c9abd1f069eab7` |

`rootfs-all.cramfs` y `rootfs-upgrade-reproduced.cramfs` se reconstruyeron
y compararon byte a byte con el rootfs instalado. Se verificó el hash durante
el flasheo. No se sobrescribieron las imágenes estables del repositorio.

| Selección construida | Rootfs | Libre en partición |
|---|---:|---:|
| all | 7.786.496 B | 77.824 B |
| bash-red | 7.487.488 B | 376.832 B |
| python-automatizacion | 6.750.208 B | 1.114.112 B |
| personalizada: bash,micropython (incluye Dash) | 7.348.224 B | 516.096 B |

Se flasheó además `rootfs-python-final.cramfs`, sin Bash: el login persistente
usó BusyBox correctamente y pasaron MicroPython y Make. Luego se restauró
el perfil completo. Ese ensayo precede al último ajuste de terminal de las
herramientas de medición; los perfiles canónicos se reconstruyeron después
con ese ajuste y se comprobaron en host. No se afirma haber arrancado cada
combinación personalizada en placa.

Resultados del registro final `out/programs/board-upgrade-final.log`:

- `process-test` 10/10, más tres repeticiones completas. Cada ejecución
  incluye 24 forks repetidos y retorno de respaldos propios a cero.
- Recuperación medida del padre: **0 → 124 → 0 KiB**. Exec también libera
  su respaldo mientras el hijo sigue vivo con una imagen nueva.
- Bash interactivo: arrays, arrays asociativos, regex, subshell independiente,
  pipelines, PIPESTATUS, sustitución de procesos, mapfile, wait y señales.
- Hush login: perfil cargado una vez, 20 sustituciones anidadas, `$0` y heredoc.
- Dash, Make LTO (`-j2`, dependencias, no-op, dry-run, error esperado),
  MicroPython nativo (incluidos cinco forks reales e IPC), y red con socat/nc
  (TCP, UDP y sockets Unix): suites completas aprobadas.
- Cola: límite de concurrencia, espera por presupuesto, exec fallido,
  timeout y detección de un hijo detenido con SIGSTOP.
- Fork estático 5/5, dinámico 5/5 y callbacks atfork aprobados.
- MMU A/B/A/B: 103/1006/106/1012, alias desactivado; Fibonacci(20)=6765.
- socat con salida al terminal bajo programbench terminó con código 0;
  se restauró el terminal. Escaneo Wi-Fi: cinco redes detectadas.

Instantánea al terminar: MemFree 1356 KiB, MemAvailable 1292 KiB,
ForkShadow 0 KiB, ForkRecovered 45176 KiB acumulados. El último valor cuenta
memoria recuperada a lo largo de muchos forks, **no** RAM física disponible.
Taint 0, sin BUG, WARNING, OOM, fallos de asignación de páginas ni panic en
el registro de esta batería. No equivale a una prueba de duración ilimitada.

Evidencia adicional local:

- `out/programs/board-benchmark-fixed.log`: cargas medidas del CSV.
- `out/programs/board-profile-python.log`: arranque sin Bash y suites.
- `out/programs/flash-upgrade-final.log`: escritura/verificación del rootfs final.
- `out/flash-kernel-proc-users.log`: escritura/verificación del kernel #10.
- Host: test-reclaim con ASan/UBSan, test-process-tools (incluido ptrace),
  prueba PTY del medidor, test-strip-sections, test-profiles y test-serial.
