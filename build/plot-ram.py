#!/usr/bin/env python3
"""Draw docs/ram-before-after*.svg from the figures in build/verification.

Before is the 0.7 kernel as measured at 734c157 (2026-09-12-full-image.md),
after is the 0.8 image (2026-09-14-final-image.md, 2026-09-14-final-results.json).
All numbers are kB read off the board through /proc/meminfo and programbench.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent.parent
records = root / 'build/verification'
after_results = json.loads((records / '2026-09-14-final-results.json').read_text())

mem_total = after_results['memory_baseline']['meminfo_kb']['MemTotal']
available = {
    '0.7': 1340,
    '0.8': after_results['memory_baseline']['meminfo_kb']['MemAvailable'],
}

# program: (peak fork shadow, lowest MemAvailable during the run)
programs = ['bash', 'micropython', 'dash', 'make', 'socat', 'jobq']
before = {'bash': (892, 248), 'dash': (560, 708), 'micropython': (512, 328),
          'socat': (296, 944), 'make': (432, 660), 'jobq': (248, 968)}
after = {'bash': (528, 2984), 'dash': (280, 3364), 'micropython': (308, 2996),
         'socat': (152, 3544), 'make': (0, 3332), 'jobq': (0, 3568)}


def draw(path, dark):
    fg = '#d0d4d9' if dark else '#24292f'
    grid = '#3a3f45' if dark else '#d8dce0'
    old, new = ('#8b949e', '#58a6ff') if dark else ('#9aa0a6', '#1f6feb')
    plt.rcParams.update({
        'font.size': 10, 'text.color': fg, 'axes.labelcolor': fg,
        'xtick.color': fg, 'ytick.color': fg, 'axes.edgecolor': grid,
        'svg.fonttype': 'path',
    })
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2),
                             gridspec_kw={'width_ratios': [1, 1.8, 1.8]})
    fig.patch.set_alpha(0)
    for ax in axes:
        ax.set_facecolor('none')
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)

    ax = axes[0]
    names = list(available)
    values = [available[n] for n in names]
    bars = ax.barh(names, values, color=[old, new], height=0.45)
    ax.set_xlim(0, mem_total)
    ax.set_xlabel(f'MemAvailable after boot, kB  (MemTotal {mem_total})')
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=grid, linewidth=0.6)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values):
        ax.text(value + 90, bar.get_y() + bar.get_height() / 2, f'{value}',
                va='center', ha='left', fontsize=10)
    ax.set_title('Free RAM once the board is up', loc='left', fontsize=11)

    def grouped(ax, index, label, title, legend):
        x = range(len(programs))
        width = 0.38
        left = [before[p][index] for p in programs]
        right = [after[p][index] for p in programs]
        b1 = ax.bar([i - width / 2 for i in x], left, width, color=old, label='0.7')
        b2 = ax.bar([i + width / 2 for i in x], right, width, color=new, label='0.8')
        ax.set_xticks(list(x), programs, fontsize=9.5)
        ax.set_ylabel(label)
        ax.yaxis.grid(True, color=grid, linewidth=0.6)
        ax.set_axisbelow(True)
        top = max(left + right)
        ax.set_ylim(0, top * 1.18)
        for bars in (b1, b2):
            for bar in bars:
                v = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2, v + top * 0.02,
                        f'{int(v)}', ha='center', va='bottom', fontsize=8.5)
        ax.set_title(title, loc='left', fontsize=11)
        if legend:
            ax.legend(frameon=False, loc='upper right')

    grouped(axes[1], 0, 'peak fork shadow, kB',
            'What each program costs to run', legend=True)
    grouped(axes[2], 1, 'lowest MemAvailable during the run, kB',
            'How close each one gets to the floor', legend=False)
    fig.tight_layout(w_pad=2.5)
    fig.savefig(path, format='svg', transparent=True)
    plt.close(fig)


draw(root / 'docs/ram-before-after.svg', dark=False)
draw(root / 'docs/ram-before-after-dark.svg', dark=True)
