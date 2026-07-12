#!/usr/bin/env python3
import sys, time, serial

PORT = "/dev/ttyACM0"
BAUD = 115200
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0

ser = serial.Serial(PORT, BAUD, timeout=0.2)

# Hard reset into RUN mode (not download): IO0 high, pulse EN low->high.
ser.dtr = False   # GPIO0 high (normal boot)
ser.rts = True    # EN low  -> chip in reset
time.sleep(0.15)
ser.reset_input_buffer()
ser.rts = False   # EN high -> chip runs
time.sleep(0.02)
ser.dtr = False

start = time.time()
buf = bytearray()
while time.time() - start < SECONDS:
    data = ser.read(4096)
    if data:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        buf += data
ser.close()
sys.stderr.write("\n[capture done, %d bytes]\n" % len(buf))
