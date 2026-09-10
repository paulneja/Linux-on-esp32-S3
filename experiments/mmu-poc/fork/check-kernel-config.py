#!/usr/bin/env python3
"""Assert a built .config still carries every statement of the seed config.

build-kernel.sh copies the configured buildroot tree into out/linux-fork only
when that directory does not exist, and the directory is gitignored, so it
outlives everything. A change to the seed config can therefore be added, built,
measured and released without ever having reached the kernel, and the build
succeeds all the way through. Compare the two and fail loudly instead.

The comparison is one-directional: only symbols the seed mentions are checked.
build-kernel.sh sets XTENSA_NOMMU_FORK and LOCALVERSION behind the seed's back
and neither is named in the seed, so neither is flagged. Naming either one in
the seed would fail every build.
"""
import re
import sys
from pathlib import Path

SET = re.compile(r'^(CONFIG_[A-Z0-9_]+)=(.*)$')
UNSET = re.compile(r'^# (CONFIG_[A-Z0-9_]+) is not set$')


def statements(text):
    result = {}
    for line in text.splitlines():
        match = SET.match(line)
        if match:
            result[match[1]] = match[2]
            continue
        match = UNSET.match(line)
        if match:
            result[match[1]] = None
    return result


def compare(seed_path, built_path):
    seed = statements(Path(seed_path).read_text())
    built = statements(Path(built_path).read_text())
    divergences = []
    for symbol, wanted in seed.items():
        present = symbol in built
        got = built.get(symbol, 'absent')
        if wanted is None:
            # olddefconfig drops symbols whose dependencies are unmet, so an
            # absent symbol is disabled just as surely as an explicit "not set".
            if present and got is not None:
                divergences.append((symbol, wanted, got))
        elif not present or got != wanted:
            divergences.append((symbol, wanted, got))
    return divergences


def show(value):
    return 'not set' if value is None else 'absent' if value == 'absent' else value


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: check-kernel-config.py SEED BUILT')
    found = compare(sys.argv[1], sys.argv[2])
    if not found:
        print(f'{sys.argv[2]}: matches every statement in {sys.argv[1]}')
        raise SystemExit(0)
    print(f'{sys.argv[2]} does not carry {len(found)} statement(s) from {sys.argv[1]}:',
          file=sys.stderr)
    for symbol, wanted, got in found:
        print(f'  {symbol}: seed says {show(wanted)}, built has {show(got)}', file=sys.stderr)
    print('\nThe kernel tree is stale. It is copied only when it does not exist,'
          '\nso a config change never reached it. Recover with:'
          '\n  rm -rf experiments/mmu-poc/out/linux-fork'
          '\nand build again, or run a clean build/reproduce.sh.', file=sys.stderr)
    raise SystemExit(1)
