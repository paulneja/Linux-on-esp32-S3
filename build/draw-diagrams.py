#!/usr/bin/env python3
"""Draw docs/architecture*.svg and docs/banner*.svg.

Partition sizes come from the 16 MB partition table in new-files/esp-hosted.
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
docs = root / 'docs'
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

LIGHT = dict(fg='#1f2328', muted='#59636e', line='#d1d9e0', surface='#f6f8fa',
             card='#ffffff', accent='#0969da', accent_soft='#ddf4ff', green='#1a7f37',
             green_soft='#dafbe1', amber='#9a6700', amber_soft='#fff8c5', term='#0d1117')
DARK = dict(fg='#f0f6fc', muted='#9198a1', line='#3d444d', surface='#151b23',
            card='#0d1117', accent='#4493f8', accent_soft='#0c2d6b', green='#3fb950',
            green_soft='#0f3d1c', amber='#d29922', amber_soft='#3b2e0a', term='#010409')

PARTITIONS = [  # name, size in KiB, what
    ('firmware', 768, 'ESP-IDF, core 0'),
    ('etc', 448, 'jffs2'),
    ('linux', 4096, 'xipImage, XIP'),
    ('rootfs', 7680, 'cramfs, XIP'),
    ('home', 3328, 'jffs2'),
]


def text(x, y, s, size=14, fill=None, weight=400, anchor='start', mono=False):
    family = MONO if mono else FONT
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def box(x, y, w, h, fill, stroke, r=10, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"{d}/>')


def bullet(x, y, s, c, mono=False):
    return (f'<circle cx="{x}" cy="{y - 4.5}" r="2.6" fill="{c["muted"]}"/>'
            + text(x + 12, y, s, 14, c['fg'], mono=mono))


def architecture(c):
    W, H = 1200, 624
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    out.append(box(1, 1, W - 2, 366, c['surface'], c['line'], 14))
    out.append(text(28, 38, 'ESP32-S3', 18, c['fg'], 600))
    out.append(text(124, 38, 'two Xtensa LX7 cores at 240 MHz, one chip', 14, c['muted']))

    out.append(box(28, 62, 470, 280, c['card'], c['line']))
    out.append(text(52, 98, 'Core 0', 17, c['fg'], 600))
    out.append(text(120, 98, 'ESP-IDF 5.1 and FreeRTOS', 15, c['muted']))
    for i, s in enumerate(['owns the WiFi radio and the 802.11 MAC',
                           'NimBLE peripheral, Nordic UART service',
                           'writes the flash when Linux asks',
                           'boots first and starts Linux on core 1']):
        out.append(bullet(56, 140 + i * 34, s, c))
    out.append(box(52, 290, 422, 32, c['amber_soft'], 'none', 6))
    out.append(text(66, 311, 'network_adapter: esp-hosted firmware', 13, c['amber'], 500, mono=True))

    out.append(box(702, 62, 470, 280, c['card'], c['accent']))
    out.append(text(726, 98, 'Core 1', 17, c['fg'], 600))
    out.append(text(794, 98, 'Linux 7.2.4, NOMMU, runs from flash', 15, c['muted']))
    for i, s in enumerate(['esp32-ng driver: espsta0 and /dev/esp-ble',
                           'fork() by swapping memory banks',
                           'Bash, BusyBox, Dash, MicroPython, Make',
                           'dropbear or telnetd, cron, nano, curl']):
        out.append(bullet(730, 140 + i * 34, s, c))
    out.append(box(726, 290, 422, 32, c['accent_soft'], 'none', 6))
    out.append(text(740, 311, 'xipImage + cramfs, executed in place', 13, c['accent'], 500, mono=True))

    y = 186
    out.append(f'<line x1="510" y1="{y}" x2="690" y2="{y}" stroke="{c["muted"]}" stroke-width="1.6"/>')
    out.append(f'<path d="M 690 {y} l -9 -5 v 10 z" fill="{c["muted"]}"/>')
    out.append(f'<path d="M 510 {y} l 9 -5 v 10 z" fill="{c["muted"]}"/>')
    out.append(text(600, y - 14, 'shared-memory IPC', 14, c['fg'], 600, 'middle'))
    out.append(text(600, y + 26, 'WiFi frames, BLE bytes,', 13, c['muted'], anchor='middle'))
    out.append(text(600, y + 44, 'flash commands', 13, c['muted'], anchor='middle'))

    out.append(box(1, 392, 470, 230, c['card'], c['line'], 14))
    out.append(text(28, 428, 'Octal PSRAM', 17, c['fg'], 600))
    out.append(text(146, 428, '8 MB, all of it Linux RAM', 15, c['muted']))
    for i in range(128):
        col, row = i % 32, i // 32
        x, yy = 28 + col * 13, 448 + row * 13
        fill = c['accent'] if i in (37, 38, 39, 40, 69, 70, 71, 72, 101) else c['surface']
        out.append(f'<rect x="{x}" y="{yy}" width="11" height="11" rx="2" fill="{fill}" stroke="{c["line"]}" stroke-width="0.8"/>')
    out.append(text(28, 548, '128 pages of 64 KiB, mapped through the cache MMU. A context', 13, c['muted']))
    out.append(text(28, 568, 'switch between forked processes swaps whole pages by', 13, c['muted']))
    out.append(text(28, 588, 'rewriting MMU entries instead of copying them.', 13, c['muted']))

    out.append(box(497, 392, 702, 230, c['card'], c['line'], 14))
    out.append(text(524, 428, 'Flash', 17, c['fg'], 600))
    out.append(text(578, 428, '16 MB', 15, c['muted']))
    total = sum(s for _, s, _ in PARTITIONS)
    x, span = 524, 650
    tints = {'firmware': c['amber_soft'], 'linux': c['accent_soft'], 'rootfs': c['accent_soft'],
             'etc': c['green_soft'], 'home': c['green_soft']}
    small = []
    for name, size, what in PARTITIONS:
        w = span * size / total
        out.append(f'<rect x="{x:.1f}" y="450" width="{w - 3:.1f}" height="60" rx="5" '
                   f'fill="{tints[name]}" stroke="{c["line"]}"/>')
        if w > 90:
            out.append(text(x + 10, 475, name, 14, c['fg'], 600, mono=True))
            out.append(text(x + 10, 497, f'{size / 1024:g} MB', 12, c['muted']))
            out.append(text(x + 4, 530, what, 12, c['muted']))
        else:
            small.append((x + (w - 3) / 2, name, size))
        x += w
    for i, (mx, name, size) in enumerate(small):
        ly = 552 + i * 18
        out.append(f'<path d="M {mx:.1f} 512 V {ly - 4} H 640" fill="none" stroke="{c["muted"]}" stroke-width="0.8"/>')
    out.append(text(646, 552, 'firmware, 768 KB: ESP-IDF on core 0', 12, c['muted']))
    out.append(text(646, 570, 'etc, 448 KB: jffs2', 12, c['muted']))
    out.append(text(524, 596, 'Kernel and root filesystem run straight from flash; /etc and /home', 13, c['muted']))
    out.append(text(524, 614, 'are writable jffs2 and survive updates.', 13, c['muted']))
    out.append('</svg>')
    return '\n'.join(out)


def banner(c):
    W, H = 1280, 360
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    out.append(box(1, 1, W - 2, H - 2, c['surface'], c['line'], 16))
    cx, cy, s = 300, 180, 210
    x0, y0 = cx - s / 2, cy - s / 2
    for i in range(14):
        t = 18 + i * (s - 36) / 13
        for px, py, pw, ph in ((x0 + t - 4, y0 - 16, 8, 14), (x0 + t - 4, y0 + s + 2, 8, 14),
                               (x0 - 16, y0 + t - 4, 14, 8), (x0 + s + 2, y0 + t - 4, 14, 8)):
            out.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw}" height="{ph}" rx="1.5" fill="{c["line"]}"/>')
    out.append(box(x0, y0, s, s, c['card'], c['muted'], 12))
    out.append(box(x0 + 22, y0 + 22, s - 44, s - 44, 'none', c['line'], 6, '4 4'))
    out.append(box(x0 + 34, y0 + 40, 66, 74, c['amber_soft'], 'none', 6))
    out.append(text(x0 + 67, y0 + 72, 'core 0', 13, c['amber'], 600, 'middle', mono=True))
    out.append(text(x0 + 67, y0 + 92, 'ESP-IDF', 12, c['amber'], 400, 'middle', mono=True))
    out.append(box(x0 + 110, y0 + 40, 66, 74, c['accent_soft'], 'none', 6))
    out.append(text(x0 + 143, y0 + 72, 'core 1', 13, c['accent'], 600, 'middle', mono=True))
    out.append(text(x0 + 143, y0 + 92, 'Linux', 12, c['accent'], 400, 'middle', mono=True))
    out.append(text(cx, y0 + 152, 'ESP32-S3', 15, c['fg'], 600, 'middle', mono=True))
    out.append(text(cx, y0 + 172, 'N16R8', 12, c['muted'], 400, 'middle', mono=True))
    out.append(f'<circle cx="{x0 + 14}" cy="{y0 + 14}" r="4" fill="{c["muted"]}"/>')

    tx, ty = 520, 92
    out.append(box(tx, ty - 34, 700, 232, c['term'], c['line'], 10))
    for i, col in enumerate(('#ff5f57', '#febc2e', '#28c840')):
        out.append(f'<circle cx="{tx + 22 + i * 18}" cy="{ty - 16}" r="5.5" fill="{col}"/>')
    lines = [
        ('#7ee787', 'root@esp32s3:~# ', '#e6edf3', 'uname -sr'),
        (None, '', '#c9d1d9', 'Linux 7.2.4-forkbank'),
        ('#7ee787', 'root@esp32s3:~# ', '#e6edf3', 'grep -E "MemTotal|MemAvailable" /proc/meminfo'),
        (None, '', '#c9d1d9', 'MemTotal:           7852 kB'),
        (None, '', '#c9d1d9', 'MemAvailable:       4204 kB'),
        ('#7ee787', 'root@esp32s3:~# ', '#e6edf3', 'echo $(( $(bash -c "echo \\$BASHPID") != $$ ))'),
        (None, '', '#c9d1d9', '1'),
    ]
    for i, (pc, prompt, tc, body) in enumerate(lines):
        y = ty + 18 + i * 25
        if prompt:
            out.append(f'<text x="{tx + 22}" y="{y}" font-family="{MONO}" font-size="15" xml:space="preserve">'
                       f'<tspan fill="{pc}">{prompt}</tspan><tspan fill="{tc}">{body}</tspan></text>')
        else:
            out.append(text(tx + 22, y, body, 15, tc, mono=True))
    out.append('</svg>')
    return '\n'.join(out)


for dark in (False, True):
    c = DARK if dark else LIGHT
    suffix = '-dark' if dark else ''
    (docs / f'architecture{suffix}.svg').write_text(architecture(c) + '\n')
    (docs / f'banner{suffix}.svg').write_text(banner(c) + '\n')
print('wrote docs/architecture*.svg and docs/banner*.svg')
