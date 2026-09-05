# Runtime MMU experimental — ESP32-S3 Linux

Trabajo local en `mmu-poc`, sin pushes. Solo N16R8 con este Linux NOMMU.
Ejecuta código nativo en PSRAM usando la MMU de memoria externa del S3.
**No emula CPU/Linux ni implementa una MMU de procesos o compatibilidad binaria Linux.**

Historial: [datos](RESULTS.md), [primer lanzador](EXECUTION-RESULTS.md).
Esos registros conservan sus versiones y hashes; no describen la imagen actual.
Runtime multipágina y MicroPython: [resultados](RUNTIME-RESULTS.md).

Hay además una integración independiente en el kernel para
[fork con bancos de memoria por software](fork/README.md). No atribuir ese
soporte a `mmu-run`: requiere `xipImage-fork` y la compatibilidad de libc.
El texto siguiente describe el runtime de remapeo, no el backend de fork.

## Usar en la placa

```sh
mmu-run info
mmu-run self-test
mmu-run run /usr/share/mmu/fib.elf 20
mmu-run run /usr/share/mmu/pages.elf 17
mmu-tools heap-test
mmu-tools cat /etc/hostname
mmu-tools wc /etc/passwd
mmu-tools copy /etc/hostname /tmp/mmu-hostname-copy
micropython-mmu -c 'print(2 ** 100)'
micropython-mmu /usr/share/mmu/selftest.py
micropython-mmu -c 'import mmu; print(mmu.read("/etc/hostname"))'
```

`run` pasa un argumento numérico y muestra el resultado. `exec` pasa argumentos
y servicios; usa el resultado como código de salida (0–125; otros se convierten
en 1). Los wrappers usan `exec`. Timeout: 2 s en `run`, 10 s en `exec`.

La ventana se activa durante el programa y se apaga al salir: `info` debe mostrar
`OFF mapped=0/12`. El payload puede cargarse desde flash o `/tmp`; el lanzador
Linux permanece en flash/XIP. No hay un interruptor global que convierta binarios.

## Memoria, ABI y servicios

- Hasta 12 páginas propias de 64 KiB, asignadas individualmente con `mmap`.
- Código/literales en `0x43000000`: hasta 512 KiB, primeras 8 páginas.
- Datos/BSS en `0x3d080000`: hasta 256 KiB, últimas 4 páginas.
- Solo se asignan páginas presentes en segmentos LOAD. Los huecos quedan inválidos.
- Carga por partes: cabeceras de hasta 1076 bytes, sin copiar el ELF entero a RAM.
- ELF de hasta 1 MiB, sin solapamientos, W+X, TLS ni cargador dinámico.
- Servicios: consola, archivos regulares, reloj y heap de hasta 128 KiB / 32 bloques.
- Hasta 16 archivos y 4096 bytes de IO por llamada.
- Creación exclusivamente de archivos nuevos `/tmp/mmu-*`, sin subdirectorios,
  sobrescritura ni seguimiento de symlinks. Los existentes se pueden leer.

Entrada del SDK (`sdk/`):

```c
uint32_t mmu_main(uint32_t argumento, const struct mmu_api *api);
```

Payload CALL0 no-FDPIC; host CALL0/FDPIC. `sdk/call.S` adapta la llamada y el GOT.
No se enlaza libc Linux en el payload. Ver `payloads/tools.c`.
Los ELF del primer experimento de una página deben recompilarse: cambió la zona de datos.

## MicroPython

Port mínimo de **MicroPython v1.26.0**, no CPython. Su intérprete/compilador corre
nativamente por la ventana MMU. Scripts de hasta 16 KiB; heap GC de 96 KiB;
comprobación de pila de 40 KiB. El lanzador reserva 64 KiB de pila Linux y 32 KiB
para señales. Incluye enteros grandes, compilador, GC y módulo `mmu`.
Sin float, paquetes externos, pip, módulos `machine`/ESP-IDF ni REPL.
Se utiliza `-c` o un archivo `.py`.

```python
import mmu
texto = mmu.read("/etc/hostname")
mmu.write("/tmp/mmu-ejemplo.txt", texto)  # archivo nuevo
print(mmu.ticks_ms())
```

`mmu.read/write` trabajan con textos de hasta 16 KiB; no son una API POSIX
completa ni el builtin `open()`. El GC conserva raíces de pila y registros CALL0.
Las excepciones internas usan `micropython/setjmp.S`.

## Compilar

Requiere toolchain Linux Xtensa CALL0/FDPIC y dynconfig S3 del proyecto, más
los generadores de imagen de Buildroot. Descargar una vez las fuentes oficiales:

```sh
git clone --depth 1 --branch v1.26.0 --single-branch \
  https://github.com/micropython/micropython.git out/micropython-src
bash build.sh
bash build-micropython.sh
bash test-host.sh
bash make-test-images.sh
```

Los scripts aceptan otra ruta `esp32-linux-build/build` como primer argumento.
MicroPython debe estar limpio en el commit
`4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`. No se modifica upstream.
Su licencia MIT se instala en `/usr/share/licenses/micropython/LICENSE`.
Artefactos/fuentes descargadas/registros van en `out/`, ignorado por Git.
Los tests usan ASan/UBSan; LeakSanitizer está desactivado por la restricción de ptrace.
Payloads requieren `-mno-fdpic`, `-Wl,-m,elf32xtensa` y `payload.ld`.

`make-test-images.sh` compila, prueba y valida; **nunca flashea ni publica**.
`out/rootfs-probe.cramfs` va en `0x540000`.
La mitigación `out/etc-no-history.jffs2` va en `0xd0000` solo cuando sea necesario
reemplazar esa partición. `images/` permanece intacto.

## Límites y seguridad

Solo código confiable. **No es un sandbox**: comparte direcciones/hardware con
Linux. No hay aislamiento, protección, paginación bajo demanda, swap ni `fork`.
No habilita Neovim o ejecutables arbitrarios por sí solo.

Las transacciones pausan brevemente core 0/IRQs y sincronizan cachés; el payload
corre con ambos activos. `flock` en `/run/mmu-window.lock` coordina el lanzador
y el diagnóstico de datos, pero no protege contra otros escritores de registros.

Timeout, INT/TERM/HUP/QUIT y SEGV/BUS/ILL/FPE intentan limpiar mapas y recursos.
Los servicios bloquean temporalmente señales para no saltar fuera del asignador
o dejar recursos sin registrar. Un servicio bloqueado en el kernel puede demorar
la señal. SIGKILL/OOM/corrupción pueden impedir la limpieza.
Ante `FATAL`, conserva las páginas: **resetear la placa, no matar el proceso**.
No se han inyectado fallos de caché para validar esa recuperación extrema.

Consola por **COM**, 115200 baudios. `serial-probe.py --session` mantiene una
sola conexión y recibe JSON. Evitar bucles complejos de hush: una prueba anterior
acumuló procesos y causó OOM. `HISTFILE=/dev/null` sigue siendo una mitigación;
la ruta general de escritura JFFS2 continúa pendiente.

Referencias: [Espressif](https://docs.espressif.com/projects/esp-idf/en/v5.3.2/esp32s3/api-reference/system/mm.html),
[MicroPython v1.26.0](https://github.com/micropython/micropython/tree/v1.26.0).
