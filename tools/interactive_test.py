#!/usr/bin/env python3
import sys, time, serial

PORT, BAUD = "/dev/ttyACM0", 115200
ser = serial.Serial(PORT, BAUD, timeout=0.2)

# reset into RUN mode
ser.dtr = False; ser.rts = True
time.sleep(0.15); ser.reset_input_buffer()
ser.rts = False; time.sleep(0.02); ser.dtr = False

def pump(seconds):
    end = time.time() + seconds
    out = bytearray()
    while time.time() < end:
        d = ser.read(4096)
        if d:
            sys.stdout.buffer.write(d); sys.stdout.buffer.flush()
            out += d
    return bytes(out)

# Wait for shell prompt (up to 40s)
buf = bytearray()
end = time.time() + 40
got_prompt = False
while time.time() < end:
    d = ser.read(4096)
    if d:
        sys.stdout.buffer.write(d); sys.stdout.buffer.flush()
        buf += d
        if b"~ #" in bytes(buf)[-200:]:
            got_prompt = True
            break

sys.stderr.write("\n\n[PROMPT DETECTED=%s] sending commands...\n" % got_prompt)

for cmd in [b"uname -a\n", b"cat /proc/cpuinfo\n", b"ls -la /\n",
            b"free\n", b"echo HELLO-FROM-LINUX-ON-ESP32\n"]:
    ser.write(cmd); ser.flush()
    time.sleep(2.5)
    pump(0.5)

pump(3)
ser.close()
sys.stderr.write("\n[test done]\n")
