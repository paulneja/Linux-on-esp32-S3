# Ejecución nativa remapeada — 2026-09-05

ESP32-S3 rev. 0.2, N16R8, Linux 6.11 NOMMU. Rama local `mmu-poc`.
Se flasheó únicamente el rootfs experimental en `0x540000`, por COM/UART.
Esptool verificó su hash. Kernel, firmware y `/etc` de la fase anterior sin cambios.
Ningún push ni publicación. Las imágenes originales del repositorio no se tocaron.

## Qué funciona

`mmu-run` carga un ELF freestanding Xtensa CALL0 en una página propia de PSRAM,
activa sus vistas de código/datos, lo llama y desactiva la ventana al salir.
Es ejecución nativa: no emula CPU ni Linux. Tampoco implementa una MMU de procesos.

Por una sola conexión COM, sin reiniciar entre pruebas:

- 22/22 `mmu-run self-test` aprobados: uno inicial, veinte consecutivos enviados
  individualmente desde el PC y uno después del fallo intencional de instrucciones.
- 88 llamadas A/B/A/B con **la misma entrada `0x43000004`** y código distinto.
  Resultados 103, 1006, 106, 1012 en cada ensayo; estado persistente independiente.
- Lectura de los datos desde las páginas nativas después de apagar el alias: correcta.
- Fibonacci(20), payload almacenado en flash: **6765**.
- Fibonacci(47), payload copiado a `/tmp` y cargado por `mmu-run`: **2971215073**.
  Esto NO equivale a ejecutar un ELF Linux normal directamente desde `/tmp`.
- Bucle infinito: SIGALRM a los 2 s, salida **142**, ventana apagada.
- Terminación con SIGTERM: salida **143**, ventana apagada.
- Instrucción ilegal intencional en la entrada del payload: SIGILL, salida **132**,
  ventana apagada; el ensayo A/B siguiente volvió a pasar.
- Segundo lanzador durante un payload activo: rechazado por `flock` con
  `Resource temporarily unavailable`; el primero pudo limpiar normalmente.
- ELF Linux FDPIC `/usr/bin/mmu-probe` presentado como payload: rechazado antes de mapear.
- Regresión de `mmu-probe --remap-esp32s3`: aprobada (65.536 comparaciones).
- Registros finales: `0x600c5400 = 0x4000` (alias inválido),
  `0x600080bc = 0` (core 0 no pausado).
- Escaneo WiFi posterior: 8 BSS encontrados; core 0 continuó respondiendo.
- Uptime observado: 24 s al empezar, 160 s al terminar, sin reinicio.
- Memoria libre observada antes/después de la tanda ampliada: 1812/1716 KiB;
  buff/cache: 876/972 KiB. No constituye una medición del pico ni prueba de ausencia
  de fugas a largo plazo.

Hubo 94 activaciones de payload registradas, contando Fibonacci, timeout,
TERM e instrucción inválida. Los tiempos impresos de `window_switch` fueron
26.951–119.066 ciclos (aprox. 112–496 microsegundos a 240 MHz).
Incluyen cachés y tabla; NO incluyen carga ELF ni ejecución, y no representan
un cambio de contexto Linux. No se usaron como prueba de aceleración del sistema.

Registro completo: `out/execute-board.log`, local e ignorado por Git.
El único mensaje de instrucción ilegal del kernel corresponde a la prueba
deliberada en `0x43000000`; no hubo OOM ni fallos inesperados en esta tanda.

## Repetir desde la consola Linux

```sh
mmu-run info
mmu-run self-test
mmu-run run /usr/share/mmu/fib.elf 20
mmu-run run /usr/share/mmu/timeout.elf 0
echo $?
mmu-run info
```

Para repeticiones, enviar comandos individuales desde el PC: no usar bucles
complejos de hush en este Linux NOMMU (ver el fallo anterior documentado).

La prueba SIGILL copió `timeout.elf` a `/tmp/mmu-fault.elf` y reemplazó sus
primeros tres bytes de código, offset de archivo `0x1000`, por ceros (`ill`).
No alteró los ejecutables instalados ni el firmware.

## Validación local y artefactos

`bash build.sh`: GCC con `-Wall -Wextra -Werror`; inspección del ensamblado
del payload y de la llamada CALL0/FDPIC del lanzador.
`bash test-host.sh`: diagnóstico puro, 160 comprobaciones de formato/límites,
50.000 mutaciones deterministas y validación/copia de los cuatro ELF reales,
con AddressSanitizer y UndefinedBehaviorSanitizer sin errores reportados.
LeakSanitizer desactivado por la restricción de ptrace del entorno.
El generador validó el cramfs y el tamaño de partición antes del flasheo.

```text
rootfs-probe.cramfs (6635520 bytes)
40177a7f5e2cd24d59d8c1b1cb3ff61a948d5ab2e2340c592d9588e96966b39b
mmu-run (82048 bytes, estático/XIP)
3fdbb8baca2c0cb7a520cf8ffccd401fa59eba3d5822ac0247da2b26df72206e
counter-a.elf
cd1f6938ca03fb13857fd71037ae9c13d042d9dc3ef0360de9ccb3dfc4f41925
counter-b.elf
390b7338fce230147a6a5f1e1c89bf69120c1b64b0904e4d7cbc4e4713be031e
fib.elf
eb8234996c8a43ea5bc1ed6c5d670955e75ca0a609589f3b0a4d8465129d041f
timeout.elf
c67694d524c47d1a5d225b2c57f035a166c3f05401b9de7dd7077c2129097742
```

## Límites que siguen pendientes

- Una página de 64 KiB por payload: 32 KiB código/literales y 32 KiB datos/BSS.
- ABI propia de función, sin libc, syscalls del payload, TLS, enlazado dinámico
  ni cargador de procesos Linux. Python y Neovim no están habilitados por esto.
- No hay aislamiento/protección, paginación bajo demanda ni `fork`.
- Solo código confiable. SIGKILL/OOM o corrupción del runtime pueden dejar la
  ventana activa; los handlers no convierten este entorno en un sandbox.
- La recuperación de fallos de caché no se inyectó ni validó físicamente:
  su ruta retiene las páginas y exige reset. No matar ese proceso.
- El historial de hush permanece desactivado como mitigación de laboratorio;
  no se corrigió la escritura general de JFFS2.
