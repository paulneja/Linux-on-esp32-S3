#!/usr/bin/env python3
"""Host tests; does not open a serial port or require a board."""
import importlib.util
from pathlib import Path
import re
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("serial_probe", Path(__file__).with_name("serial-probe.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

token = b"MMU_DONE_0123456789"
pattern = rb"\n" + token + rb":([0-9]+)\r?\n"
for data in (
    b"echo " + token + b":$?\r\n" + token + b":0\r\n~ # ",
    b"echo " + token + b":$?\r\n\x1b[?2004l\r" + token + b":0\r\n\x1b[?2004h# ",
):
    visible = module.terminal_text(data)
    match = re.search(pattern, visible)
    assert match and match[1] == b"0"
    assert b"$?" in visible[:match.start()]
assert not re.search(pattern, module.terminal_text(b"echo " + token + b":$?\r\n"))
assert module.terminal_text(b"\x1b[31merror\x1b[0m\r\n") == b"error\n"
print("PASS serial: BusyBox and Bash Readline framing; command echo is not a result")

if module.os.name == 'posix':
    # DTR/RTS must be written in ONE TIOCMSET, preserving unrelated modem bits.
    port = module.ConsoleSerial(port=None)
    for dtr, rts in ((False, False), (True, True), (False, True), (True, False)):
        port.dtr, port.rts = dtr, rts
        unrelated = module.termios.TIOCM_CTS
        calls = []
        def ioctl(fd, operation, data):
            calls.append((operation, data))
            return module.struct.pack('I', unrelated | module.termios.TIOCM_DTR | module.termios.TIOCM_RTS)
        with patch.object(port, 'fd', 7, create=True), patch.object(module.fcntl, 'ioctl', side_effect=ioctl):
            port._update_dtr_state()
        assert len(calls) == 2 and calls[1][0] == module.termios.TIOCMSET
        expected = unrelated | (module.termios.TIOCM_DTR if dtr else 0) | (module.termios.TIOCM_RTS if rts else 0)
        assert module.struct.unpack('I', calls[1][1])[0] == expected
    print('PASS serial: atomic DTR/RTS update preserves other modem bits')
