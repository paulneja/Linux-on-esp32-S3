# Linux real (RISC-V emulado) en ESP32-S3, accesible por Telnet/WiFi

Un kernel de Linux **auténtico** (6.9 RV32IMA NOMMU + BusyBox) corre sobre un
emulador RISC-V (mini-rv32ima) dentro de un ESP32-S3, usando la PSRAM como RAM
del sistema. Te conectás a su WiFi y entrás por Telnet a una shell de Linux.

Basado en [`Epiczhul/esp32p4-rv32ima`](https://github.com/Epiczhul/esp32p4-rv32ima)
y el core [`cnlohr/mini-rv32ima`](https://github.com/cnlohr/mini-rv32ima).

## Hardware
- ESP32-S3, **8 MB PSRAM Octal (OPI)**, 16 MB flash.
- Consola serie por UART0 (en esta placa, el CH343 → `/dev/ttyACM0`).

## Uso (usuario final)
1. Alimentá la placa.
2. Conectate al WiFi **`esp32-linux`** (clave **`linux1234`**).
3. `telnet 192.168.4.1` → shell de Linux. Boot ~12 s.

También por cable: `python tools/capture_boot.py 60` (o cualquier terminal serie
a 115200 en `/dev/ttyACM0`). `idf.py monitor` NO sirve aquí (requiere TTY).

## Compilar y flashear
Requiere ESP-IDF v5.3 activado con el helper (workaround Python 3.14→3.12):
```bash
source ~/esp/idfenv.sh        # bash   (o: source ~/esp/idfenv.fish  en fish)
./flash.sh /dev/ttyACM0       # build + flash app + flash kernel Image
```

## Cómo está armado
- `main/uc-rv32ima.c` — bucle del emulador + emulación del UART 8250. Corre en un
  task pineado al **Core 1**.
- `main/port-esp.c` — reserva la RAM del guest en PSRAM (`heap_caps_malloc`), carga
  el kernel desde la partición `kernel`, e I/O de UART0.
- `main/net_console.c` — AP WiFi WPA2 + servidor Telnet (:23) en el **Core 0**.
  Dos StreamBuffers puentean guest↔socket. La consola queda espejada en UART0.
- `main/Image` — kernel + initramfs + DTB embebido (payload del guest, va a flash
  en `0x110000`).

## Detalles finos (fixes propios)
1. **RAM = 7.5 MB, no 8 MB.** El S3 solo entrega ~7.88 MB contiguos de PSRAM, pero
   el DTB embebido pedía 8 MB → panic al tope de RAM. Se parchea el nodo `memory`
   del DTB dentro del `Image` (`0x800000`→`0x780000`) con `tools/patch_dtb.py`.
   El Image de este repo **ya viene parcheado**; backup en `main/Image.orig8mb`.
2. **Input de consola.** (a) se lee de UART0 (no del USB-JTAG nativo). (b) el
   registro **IIR** del 8250 emulado devuelve `0xC4` (RX data available) cuando hay
   tecla, si no el driver 8250 (irq=0, polling) nunca lee el byte. Ver
   `HandleControlLoad` en `uc-rv32ima.c`.

## Limitaciones conocidas
- Lento (~2 BogoMIPS). Rootfs **volátil** (initramfs en RAM). 1 cliente Telnet a la
  vez. El guest no tiene red propia (solo consola). Queda debug por UART0.

## Herramientas (`tools/`)
- `patch_dtb.py` — parchea el tamaño de RAM en el DTB embebido del Image.
- `capture_boot.py N` — captura N s del serie (resetea la placa; no necesita TTY).
- `interactive_test.py` — boot + manda comandos de prueba por serie.
- `telnet_test.py` — cliente Telnet de prueba contra 192.168.4.1.
