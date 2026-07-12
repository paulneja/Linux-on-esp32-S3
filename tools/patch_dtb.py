#!/usr/bin/env python3
# Patch the builtin DTB memory node size inside the kernel Image:
#   reg = <0x00 0x80000000 0x00 0x800000>  (8MB)  ->  0x780000 (7.5MB)
# so the guest kernel never accesses beyond our ~7.88MB PSRAM buffer.
import sys

IMG = "/home/paulneja/Arduino/esp-32/LINUX/s3-linux/main/Image"

# memory reg property value: addr-cells=2, size-cells=2
#   00000000 80000000 00000000 00800000
old = bytes.fromhex("00000000" "80000000" "00000000" "00800000")
new = bytes.fromhex("00000000" "80000000" "00000000" "00780000")

data = bytearray(open(IMG, "rb").read())
n = data.count(old)
print("occurrences of 8MB memory-reg pattern:", n)
if n != 1:
    print("ERROR: expected exactly 1 occurrence, aborting (found %d)" % n)
    sys.exit(1)

idx = data.find(old)
print("patching at offset 0x%x" % idx)
data[idx:idx+len(old)] = new
open(IMG, "wb").write(data)
print("DONE: memory node now 7.5MB (0x780000)")
