#!/usr/bin/env python3
"""Strip staging ELF metadata, checking every runtime section stays intact."""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


def runtime(path):
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        return None
    if data[4:6] != b"\x01\x01":
        raise ValueError(f"Not ELF32 little-endian: {path}")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    _, kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = header
    if machine != 94 or kind not in (2, 3):
        raise ValueError(f"Not an Xtensa executable/shared object: {path}")
    sections = [struct.unpack_from("<10I", data, shoff + i * shsize) for i in range(shnum)]
    names_section = sections[shstr]
    names = data[names_section[4]:names_section[4] + names_section[5]]
    allocated = {}
    for nameoff, typ, attrs, addr, offset, size, link, info, align, entsize in sections:
        name = names[nameoff:].split(b"\0", 1)[0]
        if name in (b".xt.prop", b".xt.lit") and attrs & 2:
            raise ValueError(f"Refusing to remove allocated {name!r}: {path}")
        if attrs & 2:
            payload = b"" if typ == 8 else data[offset:offset + size]
            allocated[name] = (typ, attrs, addr, size, align, entsize, payload)
    # Program headers include file offsets, XIP mapping, permissions and stack size.
    return ((kind, machine, version, entry, flags, ehsize, phsize, phnum),
            data[phoff:phoff + phsize * phnum], allocated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Disposable rootfs staging tree")
    parser.add_argument("--strip", required=True, help="Xtensa target strip executable")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir() or root == Path("/") or not (root / "bin/busybox").is_file():
        parser.error("Expected an extracted rootfs staging directory")
    count = saved = 0
    with tempfile.TemporaryDirectory(prefix="esp32-strip-") as temp:
        candidate = Path(temp) / "candidate"
        for directory, _, names in os.walk(root, followlinks=False):
            for name in sorted(names):
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    continue
                before = runtime(path)
                if before is None:
                    continue
                shutil.copy2(path, candidate)
                subprocess.run([args.strip, "--strip-unneeded", "-R", ".xt.prop",
                                "-R", ".xt.lit", str(candidate)], check=True)
                if runtime(candidate) != before:
                    # Some freestanding payloads lose an empty PT_LOAD when stripped.
                    # Keep the original instead of relaxing loader invariants.
                    print(f"KEEP {path.relative_to(root)}: runtime layout would change")
                    continue
                reduction = path.stat().st_size - candidate.stat().st_size
                if reduction < 0:
                    raise RuntimeError(f"ELF grew: {path}")
                shutil.copyfile(candidate, path)  # Preserve mode, ownership and hard links.
                saved += reduction
                count += 1
                print(f"{path.relative_to(root)}: -{reduction} bytes")
    print(f"Verified {count} ELF files; removed {saved} bytes before cramfs packing.")


if __name__ == "__main__":
    main()
