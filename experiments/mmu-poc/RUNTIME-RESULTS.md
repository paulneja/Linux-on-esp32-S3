# Runtime multipágina y MicroPython — 2026-09-05

ESP32-S3 rev. 0.2 N16R8, Linux nativo 6.11 NOMMU, conexión COM a 115200.
Trabajo en `mmu-poc`, sin commits ni pushes en esta fase. Kernel y firmware
originales; rootfs experimental actualizado. `images/` no cambió.

## Resultado final en la placa

Registro local completo: `out/runtime-python-board.log`.
Una sola sesión serie y un solo arranque durante esta tanda (uptime 18–310 s).

- **11/11 pruebas multipágina**: `pages.elf` cruza el límite de 64 KiB de código
  y usa 160 KiB de BSS. Comprueba el cero inicial, escribe/lee todo el buffer
  y llama a una función situada en otra página de instrucciones.
  Resultado correcto: **20890617**, máscara `0x703`, 5 páginas propias.
- **11/11 autotests de MicroPython**: Fibonacci(20/47), enteros grandes,
  listas/diccionarios, clases, excepciones y estrés de GC con raíces retenidas.
- `print(2 ** 100)` produjo **1267650600228229401496703205376**.
- El intérprete usó 7 páginas simultáneas, máscara `0x13f`, entrada `0x43057018`.
- `import mmu`: lectura de `/etc/hostname`, creación de un archivo de texto en
  `/tmp/mmu-python-test.txt` y lectura/verificación de su contenido: correctas.
- Intento de crear `/tmp/not-allowed.txt`: rechazado, OSError 1.
- Intento de sobrescribir el archivo propio existente: rechazado, OSError 17;
  contenido original comprobado después.
- `ValueError`, `SyntaxError` y `MemoryError` deliberados: excepción impresa,
  código 1 y ventana apagada. La petición de una lista de 4 MB fue rechazada
  por el heap del intérprete, sin intervenir el OOM killer.
- Bucle infinito en Python: timeout de 10 s, código 142, mapa apagado y
  recuperación registrada de los **98304 bytes** del heap GC.
- SIGTERM a Python: código 143, mismo cierre y recuperación de heap.
- Durante esa ejecución, `info` mostró `BUSY mapped=7/12`; un segundo lanzador
  fue rechazado por el bloqueo compartido. Al terminar: `OFF mapped=0/12`.
- Utilidades: heap de 128 KiB, límite de asignaciones, reutilización y rechazo
  de doble liberación aprobados; copia a `/tmp` comprobada byte a byte con `cmp`.
- Fallo intencional de instrucciones con recursos abiertos: SIGILL, código 132,
  mapa apagado, un archivo cerrado y 65536 bytes recuperados.
- Regresión de A/B/A/B: 2/2 aprobadas en esta tanda; regresión del diagnóstico
  original de datos: 65536 comparaciones aprobadas.
- WiFi después de la tanda: **8 BSS** encontrados.
- Estado final: 12 entradas inválidas y registro de pausa `0x600080bc = 0`.

37 ejecuciones del lanzador finalizaron dejando `MMU OFF` en el registro.
Los errores de Python, el SIGILL y el timeout son pruebas intencionales, no
fallos inesperados. No hubo `SESSION_ERROR`, fallo del asignador ni OOM kernel
en esta tanda final.

Memoria observada: libre 1860 KiB al inicio y 1324 KiB tras la tanda principal;
buff/cache creció de 824 a 1356 KiB. No es una medida precisa del pico ni una
prueba de ausencia de fugas a largo plazo.

## Fallo intermedio corregido

`out/multipage-board.log` conserva la primera versión de ocho páginas.
Los servicios funcionaron, pero el programa grande falló **antes de activar el
mapeo**: `posix_memalign(65536, 65536)` acabó provocando una petición de 200704
bytes en uClibc/NOMMU y Linux no encontró un bloque de orden 6.

Se sustituyó por `mmap` anónimo de 64 KiB y validación de su alineación y mapa.
También se eliminó la copia completa del ELF: ahora se validan cabeceras acotadas
y se leen los segmentos directamente a cada página propia. Las 11 pruebas del
programa grande y las 11 de Python posteriores verifican esta corrección.
El fallo intermedio no se cuenta como éxito.

## Implementación y alcance

Ventana de hasta 12 páginas: 512 KiB de instrucciones/literales y 256 KiB de
datos/BSS. Solo se asignan las páginas usadas. Se ensayaron hasta 7 simultáneas;
la capacidad máxima depende de la RAM disponible, no se garantiza toda en cada arranque.

SDK propio CALL0 no-FDPIC, puente a servicios CALL0/FDPIC del lanzador:
consola, archivos regulares, reloj y heap acotado. Recursos pendientes se cierran
al terminar o al recuperar señales. La creación se limita a nuevos `/tmp/mmu-*`.
Se agregó pila Linux de 64 KiB mediante GNU_STACK; señales usan pila alterna.

MicroPython oficial v1.26.0, commit
`4ce2dd2cdab6e57f3982fc899f15a2103d71b0be`, sin modificar upstream.
Port propio en `micropython/`; licencia instalada junto al programa.
Scripts de hasta 16 KiB, heap GC 96 KiB, enteros grandes, sin float ni paquetes
externos/pip/REPL. No es CPython. Ver [uso y límites](README.md).

Esto ejecuta un intérprete real por la ventana remapeada, pero **no es una MMU
de procesos ni un cargador general de ELF Linux**. No agrega aislamiento, `fork`,
swap, ni compatibilidad automática con Neovim. SIGKILL, corrupción o fallo de
caché todavía pueden exigir reset. La escritura general JFFS2 sigue pendiente.

## Construcción y artefactos

- GCC con avisos tratados como errores; ensambladores sin avisos de pila.
- Validación ELF: **163 casos + 50000 mutaciones**, ASan/UBSan.
- Pruebas de servicios: archivos, políticas de creación, heap y limpieza.
- ELF de los 7 payloads validado, incluyendo MicroPython.
- Cramfs validado y tamaño comprobado contra partición antes del flasheo.
- Esptool verificó el hash escrito; solo se escribió rootfs en `0x540000`.

```text
rootfs-probe.cramfs (7081984 bytes)
935fffa28ac78cd80b84b78f2d4fb64f8c432c2940ddbae5e97a1b31b195d6c1
mmu-run (87484 bytes)
70ee696aa08113a9d323331b68a2950915ab1b868e37f3528120ae33ffe4a186
micropython.elf (384460 bytes)
adba5b31cca53d698ce59d3955ec277e4179e4e1d76274e0957abe3428457d18
```

Binarios y registros completos están en `out/`, ignorado por Git. El generador
de imágenes incluye ahora los tests locales y no flashea ni publica por sí mismo.
