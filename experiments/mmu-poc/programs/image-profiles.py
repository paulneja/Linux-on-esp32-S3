#!/usr/bin/env python3
"""Select userspace packages; plan without compiling, pack/check without flashing."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
OUT = EXP / 'out'
PROGRAMS = OUT / 'programs'
REPO = EXP.parent.parent
BUILD = (REPO.parent / 'refs/esp32-linux-build/build').resolve()
HOST = BUILD / 'build-buildroot-esp32s3_devkit_c1_16m/host'
LIMIT = 0x780000
PROFILES = {'all': ['bash', 'dash', 'make', 'micropython', 'socat'],
            'bash-red': ['bash', 'dash', 'make', 'socat'],
            'python-automatizacion': ['dash', 'make', 'micropython'], 'base': []}
PACKAGES = {
    'bash': {'binary': 'bin/bash', 'source': 'programs/bash',
             'extras': ['usr/share/bash', 'usr/share/licenses/bash', 'usr/share/program-tests/bash-test.sh']},
    'dash': {'binary': 'usr/bin/dash', 'source': 'real-bins/dash-baseline',
             'extras': ['usr/share/licenses/dash', 'usr/share/fork-real/dash-test.sh']},
    'make': {'binary': 'usr/bin/make', 'source': 'real-bins/make-lto',
             'extras': ['usr/share/licenses/make', 'usr/share/fork-real/make-test.sh',
                        'usr/share/fork-real/peer.sh', 'usr/share/fork-real/Makefile.test']},
    'micropython': {'binary': 'usr/bin/micropython', 'source': 'programs/micropython-linux',
                   'extras': ['usr/share/licenses/micropython', 'usr/lib/micropython',
                              'usr/share/program-tests/micropython-test.py']},
    'socat': {'binary': 'usr/bin/socat', 'source': 'programs/socat',
              'extras': ['usr/share/licenses/socat', 'usr/share/program-tests/network-tools-test.sh']}}

def run(*args):
    subprocess.run([str(a) for a in args], check=True)

def install(src, dst, mode=0o755):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(mode)

def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)

def pack(selected, output):
    base = PROGRAMS / 'rootfs-programs-stripped.cramfs'
    if not base.is_file():
        raise SystemExit('Missing baseline image. Run make-image.sh/compact-image.sh first; see README.')
    sources = [OUT / PACKAGES[n]['source'] for n in selected]
    sources += [PROGRAMS / name for name in ('busybox-with-netcat', 'process-test', 'programbench', 'jobq')]
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise SystemExit('Missing compiled artifacts (nothing flashed):\n' + '\n'.join(missing))
    # Never delete user paths: removal is confined to this freshly extracted tree.
    with tempfile.TemporaryDirectory(prefix='profile-', dir=PROGRAMS) as tmp:
        tree = Path(tmp) / 'tree'
        run(HOST / 'bin/cramfsck', '-x', tree, base)
        for name, pkg in PACKAGES.items():
            remove(tree / pkg['binary'])
            if name not in selected:
                for path in pkg['extras']:
                    remove(tree / path)
        for name in selected:
            pkg = PACKAGES[name]
            install(OUT / pkg['source'], tree / pkg['binary'])
        if 'dash' in selected:
            install(EXP / 'fork/real/dash-test.sh', tree / 'usr/share/fork-real/dash-test.sh', 0o644)
        if 'make' in selected:
            for name in ('make-test.sh', 'peer.sh', 'Makefile.test'):
                install(EXP / 'fork/real' / name, tree / 'usr/share/fork-real' / name, 0o644)
        # BusyBox LTO booted init but rejected valid inittab entries on hardware.
        # Keep the tested -Os build with the login fix; do not select LTO for it.
        install(PROGRAMS / 'busybox-with-netcat', tree / 'bin/busybox')
        for name in ('nc', 'netcat'):
            path = tree / 'bin' / name
            remove(path)
            path.symlink_to('busybox')
        for name in ('process-test', 'programbench', 'jobq'):
            install(PROGRAMS / name, tree / 'usr/bin' / name)
        install(HERE / 'user-shell', tree / 'usr/bin/user-shell')
        install(HERE / 'set-user-shell.sh', tree / 'usr/sbin/set-user-shell')
        if 'dash' in selected:
            install(HERE / 'jobq-test.sh', tree / 'usr/share/program-tests/jobq-test.sh', 0o644)
        if set(PACKAGES).issubset(selected):
            install(HERE / 'benchmark-suite.sh', tree / 'usr/share/program-tests/benchmark-suite.sh', 0o644)
        if 'bash' in selected:
            for path in (PROGRAMS / 'bash-5.2.37/builtins/helpfiles').iterdir():
                if path.is_file(): install(path, tree / 'usr/share/bash/helpfiles' / path.name, 0o644)
            install(PROGRAMS / 'bash-5.2.37/COPYING', tree / 'usr/share/licenses/bash/COPYING', 0o644)
            install(HERE / 'bash-test.sh', tree / 'usr/share/program-tests/bash-test.sh', 0o644)
            if 'dash' in selected:
                install(HERE / 'hush-login-test.sh', tree / 'usr/share/program-tests/hush-login-test.sh', 0o644)
        if 'socat' in selected:
            install(PROGRAMS / 'socat-1.8.1.3/COPYING', tree / 'usr/share/licenses/socat/COPYING', 0o644)
            install(HERE / 'network-tools-test.sh', tree / 'usr/share/program-tests/network-tools-test.sh', 0o644)
        assert (tree / 'bin/sh').is_symlink() and (tree / 'bin/sh').readlink() == Path('busybox')
        strip = BUILD / 'crosstool-NG/builds/xtensa-esp32s3-linux-uclibcfdpic/bin/xtensa-esp32s3-linux-uclibcfdpic-strip'
        run('python3', HERE / 'strip-rootfs.py', tree, '--strip', strip, '--section-headers')
        # Bytes by installed component are real ELF sizes, not compressed flash claims.
        inventory = {name: {'path': '/' + PACKAGES[name]['binary'],
                           'elf_bytes': (tree / PACKAGES[name]['binary']).stat().st_size,
                           'sha256': hashlib.sha256((tree / PACKAGES[name]['binary']).read_bytes()).hexdigest()}
                     for name in selected}
        candidate = Path(tmp) / 'rootfs.cramfs'
        run(HOST / 'bin/mkcramfs', '-X', '-q', tree, candidate)
        run(HOST / 'bin/cramfsck', candidate)
        size = candidate.stat().st_size
        result = {'programs': selected, 'image_bytes': size, 'free_bytes': LIMIT-size,
                  'sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(), 'binaries': inventory}
        print(json.dumps(result, indent=2))
        if size > LIMIT:
            raise SystemExit(f'IMAGE REJECTED: exceeds rootfs partition by {size-LIMIT} bytes; output unchanged.')
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, output)
        output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
        return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'build', 'calibrate'])
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--profile', choices=PROFILES, default=None)
    choice.add_argument('--programs', help='Comma-separated selection; empty string selects base.')
    parser.add_argument('--output', type=Path, help='New image path; no overwrite unless --replace.')
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--compile', action='store_true', help='Rebuild selected binaries after showing the estimate.')
    args = parser.parse_args()
    selected = sorted(set(args.programs.split(',') if args.programs else [])) if args.programs is not None else PROFILES[args.profile or 'all'][:]
    unknown = set(selected) - PACKAGES.keys()
    if unknown: parser.error('Unknown programs: ' + ', '.join(sorted(unknown)))
    if {'make', 'micropython'} & set(selected) and 'dash' not in selected:
        selected.append('dash')  # packaged regression tests use Dash explicitly
    selected.sort()
    cache = HERE / 'profile-costs.json'
    if args.action == 'calibrate':
        results = {}
        for name, packages in {'base': [], **{n: [n] for n in PACKAGES}}.items():
            results[name] = pack(sorted(packages), PROGRAMS / f'calibration-{name}.cramfs')
        base = results['base']['image_bytes']
        costs = {'base_bytes': base, 'marginal_bytes': {n: results[n]['image_bytes']-base for n in PACKAGES},
                 'note': 'Measured XIP cramfs marginal costs; alignment/deduplication makes totals approximate.'}
        # Generated calibration is an output artifact; review/copy into the source manifest explicitly.
        (PROGRAMS / 'profile-costs.json').write_text(json.dumps(costs, indent=2)+'\n')
        return
    print('Programs:', ', '.join(selected) or '(base only)')
    print('Core retains BusyBox/nc, existing services, libfork, MMU tools and process diagnostics.')
    if cache.exists():
        costs = json.loads(cache.read_text())
        estimate = costs['base_bytes'] + sum(costs['marginal_bytes'][n] for n in selected)
        uncertainty = 4096 * (len(selected)+1)
        print(f'Estimated image: {estimate} bytes; free: {LIMIT-estimate}; alignment allowance ±{uncertainty}.')
        print('Estimate uses recorded builds, not a guarantee: build checks the actual partition limit.')
    else:
        print('No calibrated estimate yet; calibrate using compiled artifacts. No compilation performed.')
    if args.action == 'build':
        output = (args.output or PROGRAMS / ('rootfs-' + (args.profile or 'custom') + '.cramfs')).resolve()
        if output.exists() and not args.replace: parser.error('Output exists; choose another path or --replace.')
        if args.compile:
            import os
            run('bash', HERE / 'build-process-tools.sh')
            commands = [('busybox', HERE / 'build-netcat.sh', None)]
            for name in selected:
                if name in ('dash', 'make'): commands.append((name, EXP / 'fork/real/build.sh', name))
                else: commands.append((name, HERE / f'build-{name}.sh', None))
            for name, script, argument in commands:
                subprocess.run(['bash', str(script)] + ([argument] if argument else []),
                               env={**os.environ, 'OPT_VARIANT': 'baseline' if name in ('busybox', 'dash', 'micropython') else 'lto'}, check=True)
        pack(selected, output)
        print('Built and checked only. No flash, commit or push was performed.')

if __name__ == '__main__':
    main()
