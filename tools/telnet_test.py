#!/usr/bin/env python3
import socket, time, sys

HOST, PORT = "192.168.4.1", 23

def strip_iac(data):
    out = bytearray(); i = 0
    while i < len(data):
        b = data[i]
        if b == 255:  # IAC
            if i+1 < len(data) and 251 <= data[i+1] <= 254:
                i += 3; continue
            i += 2; continue
        out.append(b); i += 1
    return bytes(out)

s = socket.create_connection((HOST, PORT), timeout=8)
s.settimeout(3)
print("[connected to %s:%d]" % (HOST, PORT))

def drain(seconds):
    end = time.time() + seconds
    buf = bytearray()
    while time.time() < end:
        try:
            d = s.recv(4096)
            if not d: break
            buf += d
        except socket.timeout:
            pass
    txt = strip_iac(bytes(buf)).decode("latin-1")
    sys.stdout.write(txt); sys.stdout.flush()
    return txt

drain(3)
s.sendall(b"\n")
drain(1.5)
for cmd in [b"uname -a\n", b"cat /proc/cpuinfo\n", b"ls /\n",
            b"echo TELNET-WORKS-ON-ESP32\n"]:
    s.sendall(cmd)
    drain(3)
drain(2)
s.close()
print("\n[telnet test done]")
