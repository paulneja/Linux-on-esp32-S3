# Fork experimental en Linux NOMMU del ESP32-S3

Para compilar la imagen completa, usar [la ejecución integrada](../../../build/README.md).
Los resultados siguientes conservan el historial de desarrollo del backend.

Trabajo local en `mmu-poc`. Sin pushes. No modifica `images/` ni el árbol
original de construcción. Requiere el kernel experimental; **no ejecutar
`fork-test` ni utilizar esta biblioteca sobre el kernel NOMMU original**.

Pruebas posteriores con programas reales: [Dash y GNU Make](real/README.md).
Ambos están instalados y sus baterías completaron en la placa. Esa prueba
detectó demoras de planificación; el ajuste de kernel #7 ya está flasheado
y validado con planificación normal. Los tiempos y regresiones están en
ese registro; no requiere prioridad de tiempo real.

## Qué implementa

`clone(SIGCHLD, 0, ...)`, sin `CLONE_VM` y sin `CLONE_VFORK`, crea un hijo
con PID, registros, `mm_struct`, mapas y memoria privada independientes.
El planificador de Linux ejecuta ambos procesos. Pipes, descriptores,
señales, `execve()` y `waitpid()` siguen pasando por el kernel Linux.

El backend inicial es **copia de bancos de memoria al cambiar de proceso**,
no remapeo hardware ni emulación de instrucciones. Cada familia de procesos
conserva sus direcciones originales; antes de ejecutar otro banco se guarda
el residente y se restaura el entrante. El código XIP de sólo lectura queda
compartido y los mapas `MAP_SHARED` no se copian.

Los respaldos se asignan en páginas de 4 KiB, sin exigir un bloque contiguo
grande. Se usa una lista por `mm` protegida contra interrupciones para el
cambio de contexto, y referencias de región para evitar liberar memoria
residente mientras otro proceso aún la utiliza. Los accesos remotos de
`/proc` y ptrace consultan el banco correspondiente, no el residente ajeno.

No cambia los registros de la MMU externa usados por `mmu-run`.
No es protección de memoria: Linux continúa con `CONFIG_MMU=n`.

## ABI y uso

La uClibc de este toolchain NOMMU omite `fork()`. `fork-compat.c` proporciona
la entrada para programas de un solo hilo, mediante la syscall Xtensa `clone`.
Se incluye directamente al enlazar el test estático y se ofrece como
`/usr/lib/libfork.so.0` para ejecutables dinámicos Xtensa Linux FDPIC.

```sh
/usr/bin/fork-test
/usr/bin/fork-test-dynamic
fork-run /usr/bin/fork-test-dynamic
```

Un programa nuevo puede enlazar con `-l:libfork.so.0`. `fork-run PROGRAM`
precarga esa biblioteca con `LD_PRELOAD`; no transforma arquitectura, ABI,
formato ELF ni bibliotecas incompatibles. No modifica binarios estáticos.
Esto es independiente de `mmu-run`: **los programas Linux no se ejecutan
como payloads del runtime MMU**.

## Límites actuales, no ocultarlos

- Sólo Linux monoprocesador. El otro núcleo puede seguir ejecutando IDF.
- Rechaza fork con `mm_users != 1`: falta soporte de fork multihilo y
  la reparación general de cerrojos heredados de libc. La actualización
  documentada en `../programs/README.md` agrega hasta 32 callbacks
  `pthread_atfork`, probados en placa, pero no fork multihilo ni descarga
  de bibliotecas con callbacks registrados.
- Límite inicial: 512 KiB de regiones privadas respaldadas por proceso.
  La RAM real disponible puede imponer un límite menor. La implementación
  reserva un respaldo por banco además de la memoria residente original:
  dos procesos con D bytes privados pueden necesitar aproximadamente 3D.
- No hay COW, swap ni paginación bajo demanda. Se copian los bancos completos
  que cambian de propietario; el coste de planificación aumenta con D.
- Rechaza regiones privadas con páginas fijadas. Impide nuevas fijaciones
  GUP de regiones bancadas: no se admite DMA/asíncrono sobre esos buffers.
- No admite dividir ni desmapear parcialmente una región bancada. Desmapear
  la región completa y terminar/ejecutar otro proceso sí tienen liberación.
- No admite fork de mapas ejecutables privados de archivos cargados en RAM;
  requieren resolver aparte la coherencia entre las cachés I/D del S3.
- Todavía no valida las extensiones de memoria compartida, ptrace, handlers
  complejos de señales, fork concurrente multihilo o fallo parcial de reserva
  mediante una batería completa de pruebas. Un fallo de duplicación puede
  dejar respaldos del padre asignados hasta que se desmapeen sus regiones.
- La ruta genérica `dup_mm()` puede devolver `ENOMEM` incluso cuando una
  restricción del backend causó el rechazo. Falta mejorar ese diagnóstico.
- No implica que Neovim, CPython o un binario para otra arquitectura funcionen.
  Hay que portar/enlazar sus dependencias y medir flash, heap y stack.

## Construcción reproducible local

```sh
bash experiments/mmu-poc/fork/build-kernel.sh
bash experiments/mmu-poc/fork/make-image.sh
```

`build-kernel.sh` copia el árbol de Linux existente a `out/linux-fork`, aplica
`kernel.patch` y activa `CONFIG_XTENSA_NOMMU_FORK=y`. No ejecuta limpiezas
en el árbol original. `make-image.sh` parte de `out/rootfs-probe.cramfs`,
conserva el runtime y MicroPython e incorpora los tests y la biblioteca.
Ninguno de estos scripts flashea automáticamente.

Los productos son `out/xipImage-fork` (partición Linux, offset `0x140000`,
máximo 4 MiB) y `out/rootfs-fork.cramfs` (offset `0x540000`, máximo 7,5 MiB).
`out/kernel-before-fork.bin` contiene el respaldo de los 4 MiB de la
partición Linux anterior, leído directamente de la placa.

## Verificación

El programa prueba memoria global, BSS, stack y heap independientes con
64 intercambios bidireccionales por pipes, fork anidado, fork + exec,
estado de salida, SIGTERM y ocho ciclos adicionales de creación/liberación.
La batería también se ejecuta en el host; esa ejecución comprueba el test,
**no demuestra que el backend del kernel del ESP32 funcione**.

Primera ejecución física: cinco pruebas pasaron, pero hubo advertencias del
iterador Maple Tree. Se corrigió su reposicionamiento antes de cada inserción
y se añadió el bloqueo de escritura del `mm` del hijo. Esa versión inicial
no debe tratarse como una ejecución limpia. Registro: `out/fork-board.log`.

Versión corregida en la placa: **`6.11.0-forkbank #6`**, probada el
2026-09-05. Registro: `out/fork-board-clean.log`.

- 4 baterías del ejecutable estático y 4 del dinámico, más 1 del dinámico
  mediante `fork-run`: **9/9 baterías completas, 45/45 grupos de pruebas**.
- Cada batería crea 13 hijos: **117 forks**, incluyendo los nietos;
  **576 intercambios bidireccionales** por pipes.
- Memoria privada respaldada: 64 KiB en el estático, 96 KiB en el dinámico.
- En el mismo arranque pasaron A/B/A/B de `mmu-run`, el self-test de
  MicroPython y el heap de 128 KiB de `mmu-tools`.
- `tainted=0` al final y sin coincidencias reales de WARNING, BUG, Oops,
  OOM o panic en `dmesg`. Uptime inicial de pruebas: unos 19 s; final: 242 s.
- Wi-Fi: escaneo en `espsta0` devolvió 7 BSS. El primer intento usó por error
  `wlan0` y devolvió `No such device`; no fue un fallo del driver.
- RAM libre: 1580 KiB antes, 1288 KiB después de las baterías; caché/buffers
  pasó de 752 a 1392 KiB. Esto no demuestra ausencia de fugas en todos los
  caminos; sí muestra que las ejecuciones repetidas completaron sin OOM.
- SHA256 de ambos tests y de la biblioteca verificados dentro de la placa.
- Host: batería normal y ASan/UBSan completas; LeakSanitizer deshabilitado
  por la restricción del entorno. Scripts comprobados con `bash -n`.

Imágenes verificadas por esptool al flashear:

| Archivo | Bytes | SHA256 |
|---|---:|---|
| `xipImage-fork` | 3432520 | `4746034851964b8c27ae21f1fe1a346a061502c8d06b4e3621d2092a3768007e` |
| `rootfs-fork.cramfs` | 7147520 | `297fc5fed3ab418bc17a1168df49334af38744830850532810daf5ae65dfefd3` |
| `fork-test` | — | `4428607d7a4091f884b7e849a0ea8bcf33d018e10315cef0c6b02c25fa561daf` |
| `fork-test-dynamic` | 10336 | `04a5f4275de77ee82ea339058017c2445dd0a31ab0d7f571aba3dd1d25b19daf` |
| `libfork.so.0` | 4028 | `b575738a366a5dad4d313ec8d888accebd04770ea8ff15faaa6084e90425e643` |

Los binarios cambian de hash si se reconstruye el kernel con otra fecha o
número de compilación. El parche guardado corresponde al código corregido;
su aplicación inversa en seco fue verificada sobre `out/linux-fork`.
