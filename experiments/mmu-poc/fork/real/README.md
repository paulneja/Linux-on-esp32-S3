# Binarios reales: Dash y GNU Make

Experimento local del 2026-09-05. Sin pushes ni cambios en `images/`.
Placa: ESP32-S3 N16R8; Linux `6.11.0-forkbank #7`; consola COM.
Las mediciones iniciales con #6 se conservan abajo como historial.
Los registros históricos usaban los nombres `dash-fork` y `gmake-fork`;
las imágenes nuevas y los scripts ahora instalan `dash` y `make`.

## Instalado y probado físicamente

| Programa | Binario | Tamaño | Resultado |
|---|---|---:|---|
| Dash 0.5.12 | `/usr/bin/dash` | 154488 bytes | Batería completa aprobada |
| GNU Make 4.4.1 | `/usr/bin/make` | 297480 bytes | Batería completa aprobada |

Son programas originales compilados para Xtensa Linux FDPIC, enlazados con
`libfork.so.0`. No son payloads de `mmu-run` ni reimplementaciones de juguete.
El único cambio de fuentes en cada programa incorpora una declaración de
`fork()` ausente en los headers NOMMU. Se conservan las licencias en el rootfs.
La shell predeterminada `/bin/sh` no se reemplazó.

Dash mantiene su ruta original de `vfork()` para ciertos comandos externos;
las subshells, pipelines y sustituciones probadas usan `fork()`. Make fue
configurado sin `posix_spawn` ni `vfork` para ejercitar su fallback a `fork`.
`readelf` confirmó que el Make compilado importa `fork`, no aquellos dos.

Pruebas ejecutadas:

- Dash: variables privadas en subshell, sustitución con pipeline de tres
  etapas, dos trabajos en segundo plano con `wait`, código de salida del
  hijo, trap USR1 y diez sustituciones anidadas.
- Make: dos recetas con `-j2` y archivos de presencia que comprueban que
  ambas están activas, dependencia final, objetivo actualizado (`-q`),
  simulación (`-n -B`) y receta que falla con 7; Make devuelve 2 como espera
  la prueba. El mensaje `Error 7` es intencional, no un fallo de la batería.

```sh
dash /usr/share/fork-real/dash-test.sh
dash /usr/share/fork-real/make-test.sh
make --version
```

Ambas baterías llegaron a sus mensajes finales de éxito con planificación
normal en el kernel #6. La primera ejecución de Dash superó el timeout de
45 s; siguió avanzando y fue interrumpida manualmente antes de terminar.
La segunda sí completó los seis grupos. No se cuenta la interrumpida como
aprobada. El `wait` posterior desde hush falló porque ya había recogido al
hijo: el éxito de esa repetición se basa en el marcador final del script
con `set -eu`, no en ese `wait`.

## Problema real encontrado: planificación y copias

Mediciones físicas con el kernel #6, conservadas en `out/real-bins/board.log`:

| Prueba | Política normal | SCHED_FIFO prioridad 1 (diagnóstico) |
|---|---:|---:|
| Diez subshells `( : )` | 0,88 s | No medido |
| `x=$(printf x \| cat)` y comprobación | 63,77 s; 60,17 s en kernel | 0,28 s |
| Batería Dash completa | Completó, lenta; sin medición `time` completa | 1,37 s |
| Batería Make completa | Completó, lenta; sin medición `time` completa | 2,18 s |

La comparación señala la interacción del planificador con las copias de
bancos; no demuestra por sí sola cada detalle de la causa. El kernel tiene
un slice base de 0,75 ms, mientras copiar bancos puede superar ese tiempo.
La prueba con FIFO no modifica permanentemente la política de la shell ni
de otros servicios. No se recomienda FIFO como solución: puede retrasar
otros procesos. Se observó `RT throttling activated`, sin Oops ni panic.

Se preparó `scheduler.patch`: slice de al menos 50 ms sólo para entidades
de tareas con bancos activos, en la planificación justa normal. No cambia
la prioridad a tiempo real; las tareas sin bancos conservan su slice.
**Este ajuste ya fue flasheado y probado en la placa.** El primer intento
fue rechazado por el revisor automático; se continuó únicamente después
de que el usuario habilitó más acceso y autorizó nuevamente el flasheo.
Posible coste: mayor latencia entre tareas CPU-bound con bancos.

La compilación local terminó correctamente: kernel `#7`, imagen de
3432520 bytes, SHA256
`be8ee4b2b104e79a6570a9fb4efc828e772466c0cec28a7bcea4930ef33681f7`.
Archivo: `out/real-bins/xipImage-fork-slice`. Los dos parches coinciden con
el árbol compilado (aplicación inversa en seco comprobada). Se escribió en
`0x140000` y esptool verificó el contenido; `uname` confirmó #7. Rootfs,
bootloader y particiones de datos no se reescribieron en ese paso.

Al cerrar la consola de la sesión inicial (#6): `tainted=0`, uptime 782,69 s, sin reinicio durante las
pruebas. Tras las baterías FIFO: 1608 KiB libres, 1036 KiB de buffers/caché.
No es una prueba exhaustiva de ausencia de fugas. COM se cerró normalmente.

## Reproducir

```sh
bash experiments/mmu-poc/fork/real/fetch.sh
bash experiments/mmu-poc/fork/real/build.sh
bash experiments/mmu-poc/fork/real/make-image.sh
# Construir el kernel con el ajuste de planificación probado
bash experiments/mmu-poc/fork/real/build-kernel-slice.sh
```

La descarga Dash vino del archivo oficial de Debian porque el servidor del
autor no respondió. SHA512 contrastado con `package/dash/dash.hash` del
Buildroot local. Make vino de `ftp.gnu.org`; MD5 coincidió con el anuncio
oficial de 4.4.1. `sources.sha256` fija ambos tarballs para repetir el build.
Fuentes: [Dash original en Debian](https://deb.debian.org/debian/pool/main/d/dash/),
[GNU Make](https://ftp.gnu.org/gnu/make/),
[anuncio de Make 4.4.1](https://lists.gnu.org/archive/html/info-gnu/2023-02/msg00011.html).

Se desactivaron Guile, traducciones y carga de plugins de Make. No hay
compilador C nuevo en la placa: Make puede ejecutar recetas y organizar
dependencias, pero no implica poder compilar C allí sin un compilador.

## Imagen instalada

`out/rootfs-real.cramfs`: 7507968 bytes; quedan 356352 bytes en la partición
de 7,5 MiB. Incluye ambos programas, tests, licencias y los experimentos
previos. esptool verificó el hash al escribir; kernel/bootloader intactos.

SHA256:

```text
31bd1215eac99596125cb5f1775a11eba49ced46f062f6509ba3639ce456fdad  rootfs-real.cramfs
4cde05d80d9f3d4b1cdab856cd756ebb0d70b42d771bb1cfc2fa825ddd03b77b  dash
a47760aa2f4b35b1c9dd10f2bfa103445796c2e77cbc578496e6fbb79868f81d  make
```

## Validación física del kernel #7 (planificación normal)

Registro completo: `out/real-bins/board-slice.log`. La shell y la prueba
CPU-bound reportaron `SCHED_OTHER`, prioridad 0. Ningún programa de esta
sesión fue elevado a SCHED_FIFO. No se detectó `RT throttling` en dmesg.

| Prueba | Cuatro ejecuciones (segundos reales) |
|---|---|
| Tubería mínima y comprobación del resultado | 0,29 / 0,41 / 0,29 / 0,30 |
| Batería Dash, seis grupos | 2,05 / 1,64 / 1,68 / 1,83 |
| Batería Make, cuatro grupos, incluye `-j2` | 2,53 / 2,80 / 2,91 / 2,39 |

Las ocho baterías completas y las cuatro tuberías finalizaron con estado
0. La tubería que antes registró 63,77 s ya no reprodujo esa demora en estas
cuatro repeticiones. Son muestras cortas, no garantías de latencia máxima.

Regresiones aprobadas en el mismo arranque:

- `/usr/bin/fork-test` y `/usr/bin/fork-test-dynamic`: 5/5 cada uno,
  incluyendo fork anidado, exec, pipes, señales y liberación repetida.
- MMU A/B/A/B y payload multipágina `pages.elf 17` → 20890617.
- Self-test de MicroPython y prueba de heap de 128 KiB de `mmu-tools`.
- Wi-Fi: escaneo de `espsta0` devolvió 7 BSS.
- Dos hijos CPU-bound completaron 1500 iteraciones cada uno: 8,24 s total.
  Ambos conservaron contadores propios y se recogieron con `wait`.
- Hijo en bucle ocupado terminado por SIGTERM: estado 143; operación
  completa, que incluye `sleep 0.2`, en 0,54 s.
- SHA256 de Dash y Make leído en la placa coincide con los binarios locales.

Incidencia del test registrada, no ocultarla: las primeras llamadas a
`fork-test` y `fork-test-dynamic` sin ruta absoluta fallaron únicamente en
su auto-exec (`execl(argv[0], ...)`, que no busca en PATH). Se repitieron con
`/usr/bin/…` y pasaron. La versión instalada del test requiere esas rutas;
no se reescribió el rootfs para corregir la comodidad de invocación.

Estado final medido: `tainted=0`, sin WARNING/Oops/BUG/OOM/panic en dmesg;
uptime 185,35 s, frente a unos 15 s al iniciar pruebas, sin reinicios.
RAM libre 1800 → 1012 KiB; buffers/caché 704 → 1652 KiB. Se crearon archivos
temporales de pruebas y crecieron las cachés; esto no demuestra una fuga
ni su ausencia. La memoria disponible final reportada fue 1160 KiB.

Pendiente: medir latencia y presión de RAM con cargas mayores; ampliar los
límites del backend y probar más programas. Nada de esto equivale aún a
soporte de Neovim, fork multihilo o protección completa de memoria.
