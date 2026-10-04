#!/usr/bin/env python3
"""Draw docs/fork-remap*.svg, the animated comparison of the two switch paths.

The animation is not to scale. The figures in the caption come from
build/verification/2026-10-04-fork-mmu.json.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
docs = root / 'docs'
bash = json.loads((root / 'build/verification/2026-10-04-fork-mmu.json').read_text())['bash']
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
LIGHT = dict(fg='#1f2328', muted='#59636e', line='#d1d9e0', surface='#f6f8fa', card='#ffffff',
             a='#0969da', b='#bc4c00')
DARK = dict(fg='#f0f6fc', muted='#9198a1', line='#3d444d', surface='#151b23', card='#0d1117',
            a='#4493f8', b='#db6d28')

CYCLE = 16.0
SLOTS = [('big', 84), ('big', 84), ('big', 84), ('big', 84), ('small', 26), ('small', 26), ('small', 26)]
X0 = 230
DROP = 74


def pct(t):
    return f'{100 * t / CYCLE:.3f}%'


def slot_x():
    xs, x = [], X0
    for _, w in SLOTS:
        xs.append(x)
        x += w + 8
    return xs


def text(x, y, s, size, fill, weight=400, anchor='start', mono=False):
    family = MONO if mono else FONT
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def move_keyframes(name, t1, t2, dy):
    return (f'@keyframes {name} {{ 0%, {pct(t1)} {{ transform: translateY(0) }} '
            f'{pct(t1 + 0.42)}, {pct(t2)} {{ transform: translateY({dy}px) }} '
            f'{pct(t2 + 0.42)}, 100% {{ transform: translateY(0) }} }}')


def visible_keyframes(name, windows, start_visible=False):
    stops = [f'0% {{ opacity: {1 if start_visible else 0} }}']
    for start, end in windows:
        if start > 0:
            stops.append(f'{pct(start - 0.01)} {{ opacity: 0 }} {pct(start + 0.15)} {{ opacity: 1 }}')
        if end < CYCLE:
            stops.append(f'{pct(end)} {{ opacity: 1 }} {pct(end + 0.15)} {{ opacity: 0 }}')
    stops.append(f'100% {{ opacity: {1 if windows[-1][1] >= CYCLE else 0} }}')
    return f'@keyframes {name} {{ {" ".join(stops)} }}'


def status(prefix, y, done, c, css):
    states = [('process A running', c['a'], [(0, 2.0), (done + 6.0, CYCLE)]),
              ('switching', c['muted'], [(2.0, done), (8.0, done + 6.0)]),
              ('process B running', c['b'], [(done, 8.0)])]
    out = []
    for i, (label, color, windows) in enumerate(states):
        name = f'{prefix}s{i}'
        css.append(visible_keyframes(name, windows, start_visible=i == 0))
        out.append(f'<g style="animation: {name} {CYCLE}s linear infinite">'
                   + text(X0 + 700, y, label, 14, color, 600, 'end') + '</g>')
    return out


def draw(c):
    W, H = 960, 640
    css = []
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    out.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="14" fill="{c["surface"]}" stroke="{c["line"]}"/>')
    xs = slot_x()

    out.append(f'<rect x="24" y="24" width="{W - 48}" height="220" rx="10" fill="{c["card"]}" stroke="{c["line"]}"/>')
    out.append(text(48, 58, 'Copying every page', 16, c['fg'], 600))
    out += status('c', 58, 2.0 + 0.5 * len(SLOTS), c, css)
    out.append(text(X0 - 16, 109, 'process memory', 13, c['muted'], anchor='end'))
    out.append(text(X0 - 16, 109 + DROP, 'saved copy', 13, c['muted'], anchor='end'))
    for i, ((kind, w), x) in enumerate(zip(SLOTS, xs)):
        t1, t2 = 2.0 + 0.5 * i, 8.0 + 0.5 * i
        for row, color, dy in ((0, c['a'], DROP), (1, c['b'], -DROP)):
            name = f'cm{i}{row}'
            css.append(move_keyframes(name, t1, t2, dy))
            y = 86 + row * DROP
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="36" rx="5" fill="none" '
                       f'stroke="{c["line"]}" stroke-dasharray="3 3"/>')
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="36" rx="5" fill="{color}" '
                       f'style="animation: {name} {CYCLE}s ease-in-out infinite"/>')
    out.append(text(48, 226, 'Every page of both processes crosses the memory bus on every switch.', 13, c['muted']))

    top = 268
    out.append(f'<rect x="24" y="{top}" width="{W - 48}" height="250" rx="10" fill="{c["card"]}" stroke="{c["line"]}"/>')
    out.append(text(48, top + 34, 'Aligned 64 KiB pages through the cache MMU', 16, c['fg'], 600))
    out += status('m', top + 34, 2.0 + 0.3 + 0.5 * 3, c, css)
    vy, py = top + 62, top + 160
    out.append(text(X0 - 16, vy + 23, 'addresses in use', 13, c['muted'], anchor='end'))
    out.append(text(X0 - 16, py + 23, 'PSRAM pages', 13, c['muted'], anchor='end'))
    big = [x for (kind, _), x in zip(SLOTS, xs) if kind == 'big']
    pages_a = [X0 + i * 46 for i in range(4)]
    pages_b = [X0 + 4 * 46 + 18 + i * 46 for i in range(4)]
    for x in pages_a:
        out.append(f'<rect x="{x}" y="{py}" width="40" height="36" rx="5" fill="{c["a"]}"/>')
    for x in pages_b:
        out.append(f'<rect x="{x}" y="{py}" width="40" height="36" rx="5" fill="{c["b"]}"/>')
    for which, targets, windows in (('a', pages_a, [(0, 2.0), (8.15, CYCLE)]),
                                    ('b', pages_b, [(2.15, 8.0)])):
        name = f'map{which}'
        css.append(visible_keyframes(name, windows, start_visible=which == 'a'))
        lines = ''.join(f'<path d="M {vx + 42} {vy + 36} C {vx + 42} {vy + 70}, {px + 20} {py - 34}, {px + 20} {py}" '
                        f'fill="none" stroke="{c[which]}" stroke-width="1.6"/>'
                        for vx, px in zip(big, targets))
        out.append(f'<g style="animation: {name} {CYCLE}s linear infinite">{lines}</g>')
        fill = ''.join(f'<rect x="{vx}" y="{vy}" width="84" height="36" rx="5" fill="{c[which]}" fill-opacity="0.18" '
                       f'stroke="{c[which]}"/>' for vx in big)
        out.append(f'<g style="animation: {name} {CYCLE}s linear infinite">{fill}</g>')
    small = [x for (kind, _), x in zip(SLOTS, xs) if kind == 'small']
    sy = py
    for i, x in enumerate(small):
        t1, t2 = 2.3 + 0.5 * i, 8.3 + 0.5 * i
        shadow_x = pages_b[-1] + 70 + i * 34
        out.append(f'<rect x="{x}" y="{vy}" width="26" height="36" rx="5" fill="none" stroke="{c["line"]}" stroke-dasharray="3 3"/>')
        out.append(f'<rect x="{shadow_x}" y="{sy}" width="26" height="36" rx="5" fill="none" stroke="{c["line"]}" stroke-dasharray="3 3"/>')
        dx, dy = shadow_x - x, sy - vy
        for row, color, sx, sign in ((0, c['a'], x, 1), (1, c['b'], shadow_x, -1)):
            name = f'ms{i}{row}'
            css.append(f'@keyframes {name} {{ 0%, {pct(t1)} {{ transform: translate(0, 0) }} '
                       f'{pct(t1 + 0.42)}, {pct(t2)} {{ transform: translate({sign * dx}px, {sign * dy}px) }} '
                       f'{pct(t2 + 0.42)}, 100% {{ transform: translate(0, 0) }} }}')
            y = vy if row == 0 else sy
            out.append(f'<rect x="{sx}" y="{y}" width="26" height="36" rx="5" fill="{color}" '
                       f'style="animation: {name} {CYCLE}s ease-in-out infinite"/>')
    out.append(text(pages_b[-1] + 70, sy + 56, 'small pages, still copied', 12, c['muted']))
    out.append(text(48, top + 236, 'The big pages stay where they are; two MMU entries per page are rewritten.', 13, c['muted']))

    for i, (label, color) in enumerate((('process A', c['a']), ('process B', c['b']))):
        out.append(f'<rect x="{48 + i * 120}" y="540" width="14" height="14" rx="3" fill="{color}"/>')
        out.append(text(70 + i * 120, 552, label, 13, c['fg']))
    cap = (f'Slowest switch measured with three busy Bash children on the 0.9 image: '
           f'{bash["copy_ms"]:.1f} ms copying, {bash["mmu_ms"]:.1f} ms through the MMU.')
    out.append(text(48, 588, cap, 13, c['fg']))
    out.append(text(48, 610, 'The animation shows the order of the work, not its duration.', 13, c['muted']))
    out.insert(1, '<style>' + '\n'.join(css) + '</style>')
    out.append('</svg>')
    return '\n'.join(out)


for dark in (False, True):
    (docs / f'fork-remap{"-dark" if dark else ""}.svg').write_text(draw(DARK if dark else LIGHT) + '\n')
print('wrote docs/fork-remap*.svg')
