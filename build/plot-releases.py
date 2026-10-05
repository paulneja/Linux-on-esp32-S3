#!/usr/bin/env python3
"""Draw docs/releases*.svg and docs/fork-switch*.svg from build/verification.

Free RAM is MemAvailable at the start of the board suite (0.7: after boot).
The fork figure is ForkSwitchMax from the swap-model-is-live check, the same
check on every release, plus the 0.9 image with fork_bank_mmu off and on.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent.parent
records = root / 'build/verification'


def results(name):
    return json.loads((records / name).read_text())


def available(name):
    return results(name)['memory_baseline']['meminfo_kb']['MemAvailable']


def switch_ms(name):
    for test in results(name):
        if test['name'] == 'swap-model-is-live':
            return int(test['detail'].split('=')[1].rstrip('us')) / 1000


releases = ['0.7', '0.8', '0.8.1', '0.9', '0.9.1']
free_kb = [1340, available('2026-09-14-final-results.json'),
           available('2026-09-23-results.json'), available('2026-10-04-results.json'),
           available('2026-10-05-clean-results.json')]
kernel_mb = [3432520 / 1e6, 2982440 / 1e6, 2982472 / 1e6, 2419056 / 1e6, 2419056 / 1e6]
switch = [None, switch_ms('2026-09-14-extra-tests.json'),
          switch_ms('2026-09-23-extra-tests.json'), switch_ms('2026-10-04-extra-tests.json'),
          switch_ms('2026-10-05-clean-extra-tests.json')]
mmu = results('2026-10-04-fork-mmu.json')


def style(dark):
    fg = '#d0d4d9' if dark else '#24292f'
    grid = '#3a3f45' if dark else '#d8dce0'
    plt.rcParams.update({
        'font.size': 10, 'text.color': fg, 'axes.labelcolor': fg,
        'xtick.color': fg, 'ytick.color': fg, 'axes.edgecolor': grid,
        'svg.fonttype': 'path', 'svg.hashsalt': 'releases',
    })
    old, new = ('#8b949e', '#58a6ff') if dark else ('#9aa0a6', '#1f6feb')
    return fg, grid, old, new


def clean(ax, grid, axis):
    ax.set_facecolor('none')
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    getattr(ax, axis).grid(True, color=grid, linewidth=0.6)
    ax.set_axisbelow(True)


def label(ax, bars, texts, pad):
    for bar, text in zip(bars, texts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + pad, text,
                ha='center', va='bottom', fontsize=9)


def releases_figure(path, dark):
    fg, grid, old, new = style(dark)
    colors = [old] * 4 + [new]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.0))
    fig.patch.set_alpha(0)

    ax = axes[0]
    clean(ax, grid, 'yaxis')
    bars = ax.bar(releases, free_kb, color=colors, width=0.55)
    label(ax, bars, [f'{v}' for v in free_kb], 60)
    ax.set_ylim(0, 5000)
    ax.set_ylabel('kB')
    ax.set_title('Free RAM when the suite starts', loc='left', fontsize=10, color=fg)

    ax = axes[1]
    clean(ax, grid, 'yaxis')
    bars = ax.bar(releases, kernel_mb, color=colors, width=0.55)
    label(ax, bars, [f'{v:.2f}' for v in kernel_mb], 0.04)
    ax.set_ylim(0, 4)
    ax.set_ylabel('MB')
    ax.set_title('Kernel image (xipImage)', loc='left', fontsize=10, color=fg)

    ax = axes[2]
    clean(ax, grid, 'yaxis')
    shown = releases[1:]
    values = switch[1:]
    bars = ax.bar(shown, values, color=colors[1:], width=0.55)
    label(ax, bars, [f'{v:.1f} ms' for v in values], 0.4)
    for bar in bars[:2]:
        ax.text(bar.get_x() + bar.get_width() / 2, 1.0, 'IRQs off', ha='center',
                va='bottom', fontsize=8, color='white' if not dark else '#0d1117')
    ax.set_ylim(0, 25)
    ax.set_ylabel('ms')
    ax.set_title('Slowest switch between forked processes', loc='left', fontsize=10, color=fg)

    fig.tight_layout(w_pad=3)
    fig.savefig(path, transparent=True, metadata={'Date': None})
    plt.close(fig)


def fork_figure(path, dark):
    fg, grid, old, new = style(dark)
    loads = list(mmu)
    copy = [mmu[k]['copy_ms'] for k in loads]
    swap = [mmu[k]['mmu_ms'] for k in loads]
    fig, ax = plt.subplots(figsize=(9, 3.5))
    fig.patch.set_alpha(0)
    clean(ax, grid, 'xaxis')
    y = range(len(loads))
    ax.barh([i + 0.2 for i in y], copy, height=0.36, color=old, label='copying every page')
    ax.barh([i - 0.2 for i in y], swap, height=0.36, color=new, label='aligned 64 KiB chunks through the MMU')
    for i, (c, s) in enumerate(zip(copy, swap)):
        ax.text(c + 0.4, i + 0.2, f'{c:.1f} ms', va='center', fontsize=9)
        ax.text(s + 0.4, i - 0.2, f'{s:.1f} ms', va='center', fontsize=9)
    ax.set_yticks(list(y), [mmu[k]['label'] for k in loads])
    ax.invert_yaxis()
    ax.set_xlim(0, 40)
    ax.set_xlabel('slowest context switch while the load runs, ms (0.9 image, fork_bank_mmu=0 and 1)')
    ax.legend(loc='lower left', bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, transparent=True, metadata={'Date': None})
    plt.close(fig)


docs = root / 'docs'
for dark in (False, True):
    suffix = '-dark' if dark else ''
    releases_figure(docs / f'releases{suffix}.svg', dark)
    fork_figure(docs / f'fork-switch{suffix}.svg', dark)
print('wrote docs/releases*.svg and docs/fork-switch*.svg')
