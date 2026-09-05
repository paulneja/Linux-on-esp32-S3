import sys, os, gc, math, json, re, struct, hashlib, binascii, socket, time
import posix

def passed(name):
    print("PASS micropython:", name)

assert sys.implementation.name == "micropython"
assert 2 ** 100 == 1267650600228229401496703205376
assert abs(math.sqrt(2) ** 2 - 2) < 1e-12
assert struct.unpack("<I", struct.pack("<I", 0x12345678))[0] == 0x12345678
passed("big integers, double precision, struct")
value = {"items": [1, 2, 3], "enabled": True, "label": "esp32"}
assert json.loads(json.dumps(value)) == value
assert re.match(r"(esp)([0-9]+)", "esp32").group(2) == "32"
assert binascii.hexlify(hashlib.sha256(b"abc").digest()) == b"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
passed("JSON, regex, SHA256")

directory = "/tmp/python-test-" + str(time.ticks_ms())
os.mkdir(directory)
with open(directory + "/helper.py", "w") as output:
    output.write("def square(x):\n    return x*x\n")
sys.path.insert(0, directory)
import helper
assert helper.square(17) == 289
with open(directory + "/data.json", "w") as output:
    json.dump(value, output)
with open(directory + "/data.json") as source:
    assert json.load(source) == value
passed("write/read files and import module from RAM filesystem")

try:
    1 / 0
except ZeroDivisionError:
    pass
else:
    raise AssertionError("missing exception")
def squares():
    for x in range(100):
        yield x*x
assert sum(squares()) == 328350
gc.collect()
before = gc.mem_free()
for iteration in range(100):
    blocks = [bytearray(1024) for _ in range(8)]
    blocks[3][100] = iteration
    assert blocks[3][100] == iteration
    del blocks
    gc.collect()
assert gc.mem_free() >= before - 4096
passed("exceptions, generators, 100 allocation/GC cycles")

receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
receiver.settimeout(2)
address = socket.getaddrinfo("127.0.0.1", 49172, socket.AF_INET, socket.SOCK_DGRAM)[0][-1]
receiver.bind(address)
sender.sendto(b"python-udp", address)
assert receiver.recvfrom(32)[0] == b"python-udp"
receiver.close()
sender.close()
passed("UDP loopback")

for iteration in range(5):
    state = [10, bytearray(b"parent")]
    read_fd, write_fd = posix.pipe()
    pid = posix.fork()
    if pid == 0:
        posix.close(read_fd)
        state[0] = 99
        state[1][0] = ord("C")
        assert posix.write(write_fd, b"child") == 5
        posix.close(write_fd)
        posix._exit(7)
    posix.close(write_fd)
    assert posix.read(read_fd, 16) == b"child"
    posix.close(read_fd)
    assert posix.waitpid(pid, 0) == (pid, 7 << 8)
    assert state == [10, bytearray(b"parent")]
passed("five real forks, independent Python heap, pipe IPC, waitpid/exit status")
assert os.system("/usr/bin/dash -c 'x=$(printf python | cat); test \"$x\" = python'") == 0
passed("external shell and pipeline")
os.remove(directory + "/helper.py")
os.remove(directory + "/data.json")
os.rmdir(directory)
print("MICROPYTHON LINUX TEST PASS", sys.version, "gc_free", gc.mem_free())
