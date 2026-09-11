"""Exercise the real login wrapper with a PTY and temporary executable stubs."""
from pathlib import Path
import os, pty, subprocess, tempfile
source = Path(__file__).resolve().parents[2] / 'new-files/board/espressif/esp32s3/rootfs_overlay/usr/bin/user-shell'
mirroring = 'PAPERBOARD_MIRROR_ACTIVE' in source.read_text()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    def executable(name, text):
        path=root/name;path.write_text('#!/bin/sh\n'+text);path.chmod(0o755);return path
    executable('id', 'echo "${TEST_UID:-0}"\n')
    executable('tty', 'echo "${TEST_TTY:-/dev/ttyS0}"\n')
    shell=executable('shell', 'echo SHELL\n')
    mirror=executable('mirror', 'echo MIRROR\nexec "$@"\n')
    wrapper=root/'user-shell'
    text=source.read_text().replace('/usr/bin/user-shell',str(wrapper)).replace('/usr/bin/epd-shell',str(mirror)).replace('/etc/paperboard-no-mirror',str(root/'disabled')).replace('/dev/epd','/dev/null').replace('/bin/bash',str(shell))
    wrapper.write_text(text);wrapper.chmod(0o755)
    base=dict(os.environ,HOME=str(root),PATH=str(root)+':/usr/bin:/bin')
    base.pop('PAPERBOARD_MIRROR_ACTIVE',None)
    def run(expected, terminal=True, args=(), **env):
        master,slave=pty.openpty()
        try:
            result=subprocess.run([str(wrapper),*args],stdin=slave if terminal else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(base,**env),timeout=5,check=True)
            assert result.stdout.decode().splitlines()==expected,(result.stdout,result.stderr)
        finally:os.close(master);os.close(slave)
    run(['MIRROR','SHELL'] if mirroring else ['SHELL']) # Re-entry on the same mocked serial TTY must not recurse.
    run(['MIRROR','SHELL'] if mirroring else ['SHELL'],TEST_TTY='/dev/console')
    run(['SHELL'],terminal=False)
    run(['SHELL'],TEST_TTY='/dev/pts/0')
    run(['SHELL'],TEST_UID='1000')
    run(['SHELL'],PAPERBOARD_MIRROR_ACTIVE='1')
    run(['SHELL'],args=('-c','true'))
    (root/'disabled').touch();run(['SHELL'])
print('Automatic mirror: serial login, recursion guard, SSH/non-root/noninteractive and opt-out checks passed')
