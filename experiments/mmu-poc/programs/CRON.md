# Tareas programadas

Cron de BusyBox 1.36.1: `/usr/sbin/crond` y `/usr/bin/crontab`, sin un daemon
adicional de correo. SQLite fue cancelado por el usuario: no se incluye ni
se instala. Tampoco se agregan sudo o doas ni se cambian particiones.

## Uso

```sh
crontab -e
crontab -l
cron-server status
```

En el editor (nano por defecto), cada línea tiene cinco campos y un comando:

```cron
# minuto hora día-del-mes mes día-de-semana comando
*/5 * * * * /usr/bin/micropython /home/root/tarea.py >> /home/root/tarea.log 2>&1
@reboot /bin/echo Arranque >> /home/root/arranques.log
```

El archivo tarea.py del ejemplo debe existir; no se instala ninguna tarea
por defecto. `crontab -r` borra **todas las tareas del usuario actual**.
Root puede administrar otra cuenta con `crontab -u alice -e`.
Cada usuario puede listar, editar e instalar solamente su propia tabla.

```sh
cron-server off  # detiene y desactiva también para próximos arranques
cron-server on   # activa ahora y para próximos arranques
```

El servicio usa `/bin/sh` por defecto para ahorrar RAM; el login continúa en
Bash. Una tabla puede declarar `SHELL=/bin/bash`, pero eso cuesta más memoria.
`HOME` y las credenciales corresponden al propietario de la tabla. El PATH
predeterminado es `/usr/bin:/bin:/usr/sbin:/sbin`; se puede declarar `PATH=...`.
Es preferible usar rutas absolutas y redirigir stdout/stderr a un archivo:
no hay envío de correo. `tail /var/log/messages` muestra eventos del daemon.

Las tablas viven en `/etc/cron/crontabs` sobre la partición persistente de
/etc, no en /tmp. `@reboot` se ejecuta al arrancar el daemon por primera vez
en un arranque del sistema, no cada vez que se lo reinicia manualmente.
Las tareas sobreviven al cierre del COM si la consola no provoca un reset.

Cron trabaja con la fecha/hora de **la placa**, no la del PC. Verificar `date`:
sin RTC adicional, un arranque puede comenzar en 1970 hasta sincronizar hora
por red o ajustarla manualmente. Para horas/calendario reales hace falta una
hora correcta; no se promete recuperar ejecuciones perdidas mientras está
apagada. La resolución es de un minuto, no segundos. No es systemd timers.

Mientras no se recargue la tabla, BusyBox no inicia otra instancia de una
misma línea mientras su trabajo sigue vivo. Líneas distintas sí pueden coincidir: dimensionar la RAM
o usar `jobq` para limitar la concurrencia dentro de un trabajo.

## Integración

`cron-setup` prepara los directorios e instala el hook S50crond ausente en
instalaciones existentes; no reemplaza tablas ni un hook personalizado.
En imágenes nuevas, el overlay ya contiene el hook. El estado inicial es
habilitado, sin tareas. La carpeta `/etc/cron` es root 0711 para que el editor
sin privilegios acceda a su temporal propio; `/etc/cron/crontabs` es root 0700
y las tablas son root 0600. BusyBox SUID comprueba al usuario solicitante.

El servicio se identifica por PID y nombre al detenerlo; no se usa el nombre
del enlace BusyBox como si fuera un proceso independiente. El lanzamiento
fija un entorno básico y espera el PID antes de anunciar que arrancó.
Se habilita FEATURE_PIDFILE con directorio /var/run: el PID y el marcador
de @reboot deben estar en RAM escribible, no en la raíz cramfs.
No convierte los servicios a Bash.

También se habilita FEATURE_CROND_D: BusyBox 1.36.1 condiciona a esa opción
la copia de la línea que necesita el parser de @reboot y otros horarios
especiales. Sin ella, @reboot terminaba el daemon al leer la tabla. Habilitar
la opción no activa el registro de depuración del servicio: arranca con -l 8.

Se corrige el entorno por trabajo en crond: PATH tiene su propio puntero en
el camino NOMMU/putenv, separado de SHELL; cuando una tabla no especifica
PATH se restaura el predeterminado, sin heredar el de otra tabla.

## Construcción

```sh
bash experiments/mmu-poc/programs/build-netcat.sh
python3 experiments/mmu-poc/programs/image-profiles.py build --profile all \
  --output experiments/mmu-poc/out/programs/rootfs-cron-special-ready.cramfs
python3 experiments/mmu-poc/programs/test-cron-image.py \
  experiments/mmu-poc/out/programs/rootfs-cron-special-ready.cramfs
```

La imagen completa mide 7.819.264 bytes; quedan 45.056 bytes (44 KiB).
Son 8.192 bytes adicionales respecto de la imagen de usuarios/sesiones.
SHA256: `a2fbccd878a2e9228d49c866c44889f5fb6d052e88fc5039feed960f82bb6e99`.
Se escribe solo rootfs en 0x540000. Se conservan kernel, /etc y /home.

`test-cron-board.py PORT` crea dos usuarios temporales, instala tareas,
espera su minuto real, comprueba UID/HOME/PATH/SHELL, permisos, edición,
on/off y realiza un reboot para verificar persistencia y @reboot. Elimina
sus tablas y usuarios al terminar. No altera el reloj para acelerar pruebas.

## Pruebas en placa (2026-09-05)

Con la imagen identificada arriba y el kernel existente `6.11.0-forkbank #11`:

- Dos tablas ejecutaron trabajos en un límite de minuto real, con UID,
  propietario de archivos, HOME, SHELL y PATH correctos y separados.
- Usuarios sin root pudieron listar, instalar y editar su tabla; no pudieron
  leer la del otro usuario ni administrar la de root.
- `cron-server off/on` detuvo y arrancó el daemon. Tras un reinicio real,
  las tablas persistieron y @reboot se ejecutó como su usuario propietario.
- Kernel sin taint y SQLite ausente. Se retiraron las cuentas, homes y tablas
  temporales de las pruebas; no se dejó ninguna tarea de ejemplo instalada.
- Con cron activo también pasaron procesos 10/10, Bash, MicroPython (cinco
  forks con heap independiente), login hush, Dash y socat/nc por TCP, UDP y
  sockets Unix locales. Registro: `out/programs/cron-final-regressions.log`.

Registro local: `out/programs/cron-special-functional.log`. El test de imagen
también comprueba los requisitos de configuración que causaron los fallos
iniciales (PID en RAM y copia de línea para horarios especiales).
