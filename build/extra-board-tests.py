#!/usr/bin/env python3
"""What test-board.py does not do: the things a person does with the board.

test-board.py proves the image is the one that was built and that every
program runs its test. This goes after what those leave out -- a session you
detach from and come back to, a password you change and log in with, cron
firing for real, /home surviving a reboot, a file written to jffs2 and read
back byte for byte, the shell under the kind of load that made 0.7 say
"fork: Cannot allocate memory", and the bank exchange under that same load
with its inconsistency latch watched. Each check leaves the board as it found
it. Nothing here needs WiFi; that is a separate matter and is said so.
"""
import hashlib, importlib.util, json, os, re, sys, time
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('probe', repo / 'experiments/mmu-poc/serial-probe.py')
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)

port = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyACM0'
out = Path(sys.argv[2]) if len(sys.argv) > 2 else repo / 'build-output/extra-board-tests'
out.mkdir(parents=True, exist_ok=True)
results = []


def record(name, fn):
    t0 = time.monotonic()
    try:
        detail = fn() or ''
        status = 'PASS'
    except Exception as e:
        detail = f'{type(e).__name__}: {e}'[:400]
        status = 'FAIL'
    results.append({'name': name, 'status': status, 'detail': detail, 'seconds': round(time.monotonic() - t0, 1)})
    print(f'{status}: {name}' + (f'  -- {detail}' if detail else ''), flush=True)


def reset(c):
    c.port.dtr = False; c.port.rts = True; time.sleep(0.1); c.port.rts = False


def boot(c, seconds=60):
    reset(c)
    data, t0 = b'', time.monotonic()
    while time.monotonic() - t0 < seconds:
        data += c.port.read(max(1, c.port.in_waiting))
        if b'buildroot login:' in data and time.monotonic() - t0 > 20:
            break
    return data


def logout(c):
    # `exit` alone is not enough: getty takes a moment to put the prompt back,
    # and a password typed before it is there jams it for sixty seconds.
    c.port.write(b'exit\r')
    c.until(rb'login: ?', 30)


def meminfo(c, key):
    return int(re.search(rf'{key}:\s*(\d+)', c.command(f'grep {key} /proc/meminfo', 20)).group(1))


c = probe.Console(port)
c.login()

# ---- 1. the bank exchange is the model on this image -----------------------
def swap_is_the_model():
    sw = meminfo(c, 'ForkSwitchMax')
    assert sw > 0, f'ForkSwitchMax={sw}: this kernel is the copy model'
    return f'ForkSwitchMax={sw}us'
record('swap-model-is-live', swap_is_the_model)

# ---- 2. jffs2: write big, read back byte for byte, twice ---------------------
def jffs2_roundtrip():
    c.command('dd if=/dev/urandom of=/home/.rt bs=4096 count=96 2>/dev/null; sync', 60)
    h1 = c.command('sha256sum /home/.rt | cut -c1-64', 60).splitlines()[-1].strip()
    c.command('cp /home/.rt /home/.rt2; sync; rm /home/.rt; sync', 60)
    h2 = c.command('sha256sum /home/.rt2 | cut -c1-64', 60).splitlines()[-1].strip()
    c.command('rm -f /home/.rt2; sync', 30)
    assert h1 == h2 and len(h1) == 64, f'{h1} != {h2}'
    return '384 KiB written, copied, read back identical'
record('jffs2-write-copy-readback', jffs2_roundtrip)

# ---- 3. bash under the load that broke 0.7 ------------------------------------
def shell_load():
    before = meminfo(c, 'ForkShadow')
    o = c.command('for i in $(seq 1 40); do (echo $i | tr 0-9 a-j | wc -c) >/dev/null; done; '
                  'x=$(seq 1 200 | sort -rn | head -1); echo LOAD_$x', 120)
    assert 'LOAD_200' in o, o[-200:]
    after = meminfo(c, 'ForkShadow')
    assert after == before, f'ForkShadow {before} -> {after}: shadow pages leaked'
    return f'40 subshell pipelines, ForkShadow {before}->{after}'
record('shell-pipelines-and-subshells', shell_load)

# ---- 4. the latch: still clean after all of that ------------------------------
def latch_clean():
    d = c.command('dmesg | grep -ciE "nommu_bank|inconsist|bank_report" || true', 20).splitlines()[-1].strip()
    t = c.command('cat /proc/sys/kernel/tainted', 20).splitlines()[-1].strip()
    assert d == '0' and t == '0', f'latch lines={d} tainted={t}'
    return 'no latch report, tainted 0'
record('bank-latch-silent-after-load', latch_clean)

# ---- 5. dtach: start, detach, attach, the program is still there --------------
def session_roundtrip():
    c.command('session start t1 >/dev/null 2>&1 || true', 30)
    time.sleep(1)
    o = c.command('session list', 20)
    assert 't1' in o, o
    c.command('dtach -p /tmp/dtach-0/t1 <<< "echo SESS_$(( 6 * 7 )) > /tmp/sess.out" 2>/dev/null || '
              'sh -c "echo \\"echo SESS_42 > /tmp/sess.out\\" | dtach -p /tmp/dtach-0/t1"', 20, check=False)
    time.sleep(2)
    o = c.command('cat /tmp/sess.out 2>/dev/null; echo', 20)
    c.command('session stop t1 >/dev/null 2>&1 || true; rm -f /tmp/sess.out', 20)
    assert 'SESS_42' in o, f'command sent to the detached session did not run: {o[-120:]}'
    return 'started, wrote through the socket, stopped'
record('session-detach-attach', session_roundtrip)

# ---- 6. cron fires for real ---------------------------------------------------
def cron_fires():
    c.command('rm -f /tmp/cron.mark; echo "* * * * * touch /tmp/cron.mark" | crontab -', 20)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 75:
        if 'YES' in c.command('test -e /tmp/cron.mark && echo YES || echo NO', 10):
            c.command('crontab -r; rm -f /tmp/cron.mark', 10)
            return f'fired after {time.monotonic() - t0:.0f}s'
        time.sleep(5)
    c.command('crontab -r', 10)
    raise AssertionError('no mark after 75 s')
record('cron-runs-a-job', cron_fires)

# ---- 7. passwd, then log in with the new one, then put it back ---------------
def passwd_roundtrip():
    o = c.command('printf "tmp-pw-1\\ntmp-pw-1\\n" | passwd root 2>&1; echo PW_$?', 30)
    assert 'PW_0' in o, o[-200:]
    logout(c)
    os.environ['MMU_BOARD_PASSWORD'] = 'tmp-pw-1'
    try:
        c.login()
        who = c.command('id -un', 10).splitlines()[-1].strip()
    finally:
        # whatever happened, put the factory password back before anything else runs
        c.command('printf "changeme123\\nchangeme123\\n" | passwd root >/dev/null 2>&1; sync', 30, check=False)
        os.environ['MMU_BOARD_PASSWORD'] = 'changeme123'
    assert who == 'root', who
    return 'changed, logged out, logged in with it, restored'
record('passwd-and-relogin', passwd_roundtrip)

# ---- 8. reboot: /home persists, second boot is not a factory boot -------------
def reboot_persists():
    c.command('echo PERSIST_OK > /home/.persist; sync', 20)
    c.port.write(b'reboot\r')
    data = boot(c, 90)
    assert b'buildroot login:' in data, 'no login after reboot'
    assert b'Kernel panic' not in data and b'Oops' not in data, 'fault on reboot'
    c.login()
    o = c.command('cat /home/.persist; rm -f /home/.persist', 20)
    assert 'PERSIST_OK' in o, o
    # a populated /home must not be re-seeded
    o = c.command('test -f /home/root/README.txt && ls /home/.www-seed.* 2>/dev/null | wc -l', 20).splitlines()[-1].strip()
    assert o == '0', f'seed left behind: {o}'
    return 'file survived, no re-seed'
record('reboot-home-persists', reboot_persists)

# ---- 9. bootlog round trip across a reboot -----------------------------------
def bootlog_roundtrip():
    c.command('bootlog verbose >/dev/null', 20)
    c.port.write(b'reboot\r'); data = boot(c, 90)
    verbose = data.count(b'\n')
    c.login(); c.command('bootlog quiet >/dev/null', 20)
    c.port.write(b'reboot\r'); data2 = boot(c, 90)
    quiet = data2.count(b'\n')
    c.login()
    assert verbose > 3 * quiet, f'verbose {verbose} lines vs quiet {quiet}'
    return f'verbose {verbose} lines, quiet {quiet}'
record('bootlog-across-reboots', bootlog_roundtrip)

# ---- 10. final health --------------------------------------------------------
def final():
    t = c.command('cat /proc/sys/kernel/tainted', 10).splitlines()[-1].strip()
    # "panic=10 panic_print=0x20" is in the command line; that is not a panic.
    d = c.command('dmesg | grep -v "Kernel command line" | grep -cE "Oops|BUG:|panic|inconsist" || true', 10).splitlines()[-1].strip()
    m = meminfo(c, 'MemAvailable')
    assert t == '0' and d == '0', f'tainted={t} bad-lines={d}'
    return f'tainted 0, MemAvailable {m} kB'
record('final-kernel-health', final)

c.port.close()
(out / 'results.json').write_text(json.dumps(results, indent=1) + '\n')
n = len(results); f = sum(r['status'] == 'FAIL' for r in results)
print(f'\n{n - f}/{n} passed' + (f', {f} FAILED' if f else ''))
sys.exit(1 if f else 0)
