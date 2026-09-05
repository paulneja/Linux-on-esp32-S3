# Ampliación del userspace y fork

Trabajo local, sin pushes. Las pruebas de host no sustituyen las de placa.

## Completado y probado el 5 de septiembre de 2026

1. Recuperar páginas de respaldo al quedar un único propietario.
2. Medir flash, RAM, respaldos de fork y tiempos por programa.
3. Bash para el login de usuario; BusyBox sh para los servicios.
4. Evitar que hush NOMMU reejecute un login en las sustituciones.
5. Cola de trabajos con límite de procesos y admisión por memoria.
6. Ampliar pruebas de procesos, descriptores y asignaciones.
7. Comparar optimización por tamaño y LTO, conservando solo resultados probados.
8. Seleccionar programas y estimar/comprobar imágenes antes de flashear.

Los ocho puntos están implementados. El detalle técnico, las decisiones de
compilación y las limitaciones están en [USERSPACE-UPGRADE.md](programs/USERSPACE-UPGRADE.md);
los números por programa, en [MEASUREMENTS.csv](programs/MEASUREMENTS.csv).

La placa quedó con Linux `6.11.0-forkbank #10`, Bash solo para el login del
usuario y BusyBox para `/bin/sh` y los servicios. Se probó también una imagen
sin Bash: el login de respaldo funcionó y luego se restauró la imagen completa.

- Recuperación física: respaldo del padre **0 → 124 → 0 KiB**.
- `process-test`: **10/10**, más tres repeticiones completas; también pasaron
  las suites de shells, Make, MicroPython, red, cola, fork estático/dinámico,
  atfork y el experimento MMU original.
- Rootfs final: **7.786.496 bytes**, quedan **77.824 bytes (76 KiB)**.
- Al finalizar: `ForkShadow=0 KiB`, `MemAvailable=1292 KiB`, kernel sin taint
  ni BUG/WARNING/OOM/panic en el registro de esa prueba.

No se añaden CPython ni Neovim. No es una MMU completa, COW ni aislamiento:
se conserva el límite de 512 KiB privados por fork y la restricción sin fork
multihilo. Las variantes LTO que fallaron en placa no se instalaron.

## Punto de restauración

- Kernel: `out/real-bins/xipImage-fork-slice`, SHA256
  `be8ee4b2b104e79a6570a9fb4efc828e772466c0cec28a7bcea4930ef33681f7`.
- Rootfs: `out/programs/rootfs-shell-tools.cramfs`, SHA256
  `13a96d662b6cfc2b6ad13fba491db4a716848692b16f97c45b58aadc71b13733`.
- Particiones de datos y las imágenes estables del repositorio se conservan.
