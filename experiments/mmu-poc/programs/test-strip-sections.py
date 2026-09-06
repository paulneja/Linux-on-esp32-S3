#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('elf_strip', here / 'strip-rootfs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root = here.parent.parent.parent
build = (root.parent / 'refs/esp32-linux-build/build').resolve()
strip = build / 'crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-strip'
source = here.parent / 'out/programs/process-test'
with tempfile.TemporaryDirectory(prefix='elf-sections-test-') as tmp:
    candidate = Path(tmp) / 'candidate'
    subprocess.run([str(strip), '--strip-section-headers', '-R', '.comment', '-R', '.xtensa.info',
                    '-o', str(candidate), str(source)], check=True)
    assert module.segments(source) == module.segments(candidate)
    data = bytearray(candidate.read_bytes())
    assert struct.unpack_from('<I', data, 32)[0] == 0
    assert struct.unpack_from('<HHH', data, 46) == (0, 0, 0)
    data[4096] ^= 1
    candidate.write_bytes(data)
    assert module.segments(source) != module.segments(candidate)
    print('PASS: section stripping preserves complete segments; executable byte corruption rejected')
