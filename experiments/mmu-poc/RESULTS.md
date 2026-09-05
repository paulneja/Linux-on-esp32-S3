# Resultado físico — 2026-09-05

Este registro conserva el ensayo original de **datos** y sus hashes.
La fase posterior de ejecución está en [EXECUTION-RESULTS.md](EXECUTION-RESULTS.md).

ESP32-S3 revisión 0.2, flash 16 MiB, PSRAM 8 MiB. Consola COM/UART.
Linux nativo 6.11.0, kernel y firmware originales; rootfs experimental
con dos diagnósticos XIP y `/etc` de prueba con historial desactivado.

## Ensayo aceptado

40 invocaciones individuales, 20 estáticas y 20 dinámicas, enviadas desde
el PC por una única conexión serie. Sin bucles de shell en la placa.

- 40/40 aprobaron; 160 cambios A/B de la ventana `0x3d000000`.
- 2.621.440 comparaciones de palabras de 32 bits a través de la ventana.
- Escrituras por la ventana verificadas también desde las direcciones nativas.
- Al terminar: entrada MMU `0x100 = 0x4000` (inválida) y registro de
  pausa de núcleos `0x600080bc = 0x00000000`.
- Media: 2.614.380,9 ciclos, unos 10,893 ms a 240 MHz **por ensayo completo**.
  Incluye sincronizaciones, cuatro mapeos, lecturas y escrituras; NO es
  una medida del coste de un cambio de contexto ni de una sola entrada MMU.
- No hubo OOM, SIGSEGV ni errores de comprobación en esta serie.
- `uptime` avanzó de 10 a 81 segundos sin reiniciar.
- Memoria libre: 1892 KiB al inicio, 1640 tras 20 ensayos y 1876 tras 40.
  No es una medida precisa del pico de memoria del proceso.
- Después de los ensayos, `iw dev espsta0 scan` terminó con código 0 y
  encontró 6 BSS: el firmware de core 0 siguió respondiendo.

Una salida representativa:

```text
Remap: switches=4 comparisons=65536 cycles=2613324 stage=13 fatal=0
PASS: read/write A -> B -> A -> B, native readback, alias OFF.
```

Registro completo local: `out/remap-clean.log` (ignorado por Git).

## Fallos conservados, no contados como éxito

- Desde `/tmp`, los ELF dinámicos fallaron en el cargador y el estático
  produjo SIGSEGV, pese a que SHA-256 coincidía. Los mismos diagnósticos
  funcionaron desde flash/XIP. La ejecución desde RAM queda pendiente.
- Con el historial original, hasta `echo READY` se bloqueó antes de dar
  salida. Hush escribe el historial antes de ejecutar el comando. Con
  `HISTFILE=/dev/null` las pruebas pudieron continuar: es una mitigación
  de laboratorio, no una reparación de la ruta general de escritura a flash.
- Un intento de repetir mediante un bucle complejo de hush acumuló procesos
  y disparó el OOM killer. Se reinició la placa y se sustituyó ese método
  por las 40 invocaciones individuales documentadas arriba.

## Artefactos del ensayo

```text
rootfs-probe.cramfs
b01fef2ebfad23c27e0556d9b9a42d9ec3d13a7cb8267f5f2c91e9158b089bb4
etc-no-history.jffs2
10da6e48baad27e00018b09404f117eb09e0c0b9d6ff234e338f4cbae2bdfc2b
mmu-probe (79448 bytes)
4f7543cba55f8ff5c00033e51a1de4121470c58c02b4fd9d73ee7e6ce0ab48e1
mmu-probe-dynamic (13612 bytes)
5959b0c3bc782ca6cafeda4c5ac5f13448bc0c4845d262ae74ce931123b45c48
```

Las imágenes originales de `images/` no se modificaron. La placa sí fue
reflasheada, incluyendo su configuración y datos anteriores, con autorización.
No hubo pushes ni publicación externa.

## Límite de la prueba

Demuestra remapeo reversible de **datos** mediante la MMU externa del S3,
sin emular CPU ni Linux. No demuestra ejecución de código por esa ventana,
memoria virtual por proceso, aislamiento, `fork`, ni compatibilidad con Neovim.
