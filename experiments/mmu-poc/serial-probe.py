#!/usr/bin/env python3
"""Local board console: bounded commands, acknowledged upload, no implicit reset."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

import serial


def terminal_text(data):
    """Readline emits CSI bracketed-paste controls before command output."""
    data = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", data)
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


class Console:
    def __init__(self, name, log=None):
        self.log = log
        self.port = serial.Serial(port=None, baudrate=115200, timeout=0.05,
                                  write_timeout=5, exclusive=True)
        self.port.dtr = False
        self.port.rts = False
        self.port.port = name
        self.port.open()

    def show(self, text):
        print(text, flush=True)
        if self.log:
            self.log.write(text + "\n")
            self.log.flush()

    def until(self, pattern, seconds=30):
        data = b""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            data += self.port.read(max(1, self.port.in_waiting))
            visible = terminal_text(data)
            match = re.search(pattern, visible)
            if match:
                return visible, match
        raise RuntimeError("Console timeout; last output: " + repr(data[-2048:]))

    def login(self):
        self.port.write(b"\n")
        data, _ = self.until(rb"(?:login: ?|(?:~ )?# |MMU_SHELL> )")
        if b"login:" in data:
            self.port.write(b"root\n")
            data, _ = self.until(rb"(?:Password: ?|(?:~ )?# )")
            if b"Password:" in data:
                password = os.environ.get("MMU_BOARD_PASSWORD", "changeme123")
                self.port.write(password.encode() + b"\n")
                data, _ = self.until(rb"(?:# |Login incorrect|(?:^|\n)[^\r\n]*login: ?$)")
                if b"# " not in data:
                    raise RuntimeError("Login failed; password not retried: " + data.decode(errors="replace"))

    def command(self, text, seconds=30, check=True):
        token = "MMU_DONE_" + secrets.token_hex(12)
        wire = f"{text}; echo {token}:$?\r"
        self.port.write(wire.encode())
        data, match = self.until(rb"\n" + token.encode() + rb":([0-9]+)\r?\n", seconds)
        result = data[:match.start()].decode(errors="replace").strip()
        status = int(match.group(1))
        if check and status:
            raise RuntimeError(f"Board command exited {status}: {result}")
        return result

    def upload(self, binary):
        payload = binary.read_bytes()
        expected = hashlib.sha256(payload).hexdigest()
        result = self.command("mktemp -d /tmp/mmu-poc.XXXXXX")
        match = re.search(r"(?m)^(/tmp/mmu-poc\.[A-Za-z0-9]+)\r?$", result)
        if not match:
            raise RuntimeError("Could not create board RAM directory: " + result)
        remote = match.group(1) + "/mmu-probe"
        self.show(f"Uploading {len(payload)} bytes to {remote}")
        # Acknowledge every short chunk: no large shell here-document or UART queue.
        for offset in range(0, len(payload), 384):
            chunk = base64.b64encode(payload[offset:offset + 384]).decode()
            self.command(f"echo '{chunk}' | base64 -d >> {remote}")
            if offset % (384 * 32) == 0:
                self.show(f"Transfer {offset}/{len(payload)}")
        result = self.command(f"sha256sum {remote}")
        if not re.search(r"(?m)^" + expected + r"\s+" + re.escape(remote), result):
            raise RuntimeError("SHA256 mismatch; binary not executed: " + result)
        self.command(f"chmod +x {remote}")
        self.show(f"SHA256 verified: {expected}")
        return remote

    def close(self):
        self.port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--upload", type=Path)
    parser.add_argument("--run", action="append", default=[])
    parser.add_argument("--log", type=Path)
    parser.add_argument("--session", action="store_true",
                        help="Keep one serial connection; read JSON command/upload requests from stdin")
    args = parser.parse_args()
    if args.run and not args.upload:
        parser.error("--run requires --upload")
    log = args.log.open("a") if args.log else None
    console = Console(args.port, log)
    try:
        console.login()
        for command in args.command:
            console.show("$ " + command)
            console.show(console.command(command))
        if args.upload:
            remote = console.upload(args.upload)
            for option in args.run:
                if not re.fullmatch(r"--[a-z0-9-]+", option):
                    raise ValueError("Invalid diagnostic option")
                console.show("$ " + remote + " " + option)
                console.show(console.command(remote + " " + option))
        if args.session:
            console.show("SESSION_READY")
            for line in sys.stdin:
                try:
                    request = json.loads(line)
                    if request.get("close"):
                        break
                    if "command" in request:
                        console.show(console.command(request["command"],
                                                     seconds=request.get("timeout", 30)))
                    elif "upload" in request:
                        console.show("REMOTE=" + console.upload(Path(request["upload"])))
                    elif request.get("relogin"):
                        console.port.write(b"exit\r")
                        console.until(rb"(?:^|\n)[^\r\n]*login: ?$", 15)
                        console.login()
                        console.show("LOGIN_OK")
                    else:
                        raise ValueError("Expected command, upload, relogin or close")
                    console.show("SESSION_OK")
                except Exception as error:
                    console.show("SESSION_ERROR: " + str(error))
    except Exception as error:
        console.show("ERROR: " + str(error))
        raise
    finally:
        console.close()
        if log:
            log.close()


if __name__ == "__main__":
    main()
