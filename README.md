# Linux real (RISC-V emulado) en ESP32-S3, accesible por Telnet/WiFi

Un kernel de Linux **auténtico** (RV32IMA con MMU Sv32 + BusyBox/uClibc) corre sobre un
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
- `main/uc-rv32ima.c` — bucle Sv32, SBI y emulación del UART 8250. Corre en un
  task pineado al **Core 1**.
- `main/port-esp.c` — reserva la RAM del guest en PSRAM (`heap_caps_malloc`), carga
  el kernel desde la partición `kernel`, e I/O de UART0.
- `main/net_console.c` — AP WiFi WPA2 + servidor Telnet (:23) en el **Core 0**.
  Dos StreamBuffers puentean guest↔socket. La consola queda espejada en UART0.
- `main/Image_mmu` — kernel MMU sin initramfs, flasheado en `0x110000`.
- `main/rootfs.ext4` — root persistente virtio-blk, flasheado en `0x710000`.
- `main/s3.dts` — DTB Sv32, PLIC S-mode, virtio-net y virtio-blk.

## Detalles finos (fixes propios)
1. **RAM guest = 7.5 MB.** El firmware exige PSRAM suficiente, anuncia exactamente
   `0x780000` bytes y guarda el DTB externo por encima del rango administrado.
2. **Input de consola.** (a) se lee de UART0 (no del USB-JTAG nativo). (b) el
   registro **IIR** del 8250 emulado devuelve `0xC4` (RX data available) cuando hay
   tecla, si no el driver 8250 (irq=0, polling) nunca lee el byte. Ver
   `HandleControlLoad` en `uc-rv32ima.c`.

## Limitaciones conocidas
- Lento (~2 BogoMIPS). El backend ext4 hace read-modify-erase-write de 4 KB y está
  pensado como prototipo, sin wear leveling. Un cliente Telnet a la vez.

## Reconstruir las imágenes guest

```bash
cd ../refs/mini-rv32ima
./build_slim_mmu.sh
./build_slim_rootfs.sh
```

## Herramientas (`tools/`)
- `patch_dtb.py` — parchea el tamaño de RAM en el DTB embebido del Image.
- `capture_boot.py N` — captura N s del serie (resetea la placa; no necesita TTY).
- `interactive_test.py` — boot + manda comandos de prueba por serie.
- `telnet_test.py` — cliente Telnet de prueba contra 192.168.4.1.
