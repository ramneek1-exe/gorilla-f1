"""Charts for the experiments (called from scripts/experiments.py)."""

import os

import matplotlib

matplotlib.use("Agg")  # write files only, no window
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
NEUTRAL = "#b9b8b2"
# Categorical colours, always used in this order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

# update the default rc parameters for matplotlib, these are used for all the charts.
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": NEUTRAL, "axes.labelcolor": INK_2, "text.color": INK,
    "xtick.color": INK_2, "ytick.color": INK_2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False,
})

# helper function to save a figure and close it.
def _save(fig, out_dir, name):
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, name), dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)

# helper function to add value labels to horizontal bars.
def _hbar_value_labels(ax, bars, fmt):
    for bar in bars:
        w = bar.get_width()
        ax.text(w, bar.get_y() + bar.get_height() / 2, " " + fmt.format(w),
                va="center", ha="left", fontsize=8, color=INK_2)

# create a bar chart of bytes per point for each race, with different compression methods.
def bytes_per_point(out_dir, races):
    names = [r["name"] for r in races][::-1]
    methods = [("gorilla_shared", "Gorilla, shared timestamps"),
               ("gorilla_per_channel", "Gorilla, paper layout"),
               ("zstd_lap", "zstd -19, per lap"),
               ("gzip_lap", "gzip -9, per lap")]
    if not any(r["zstd_lap"] for r in races):
        methods = [m for m in methods if m[0] != "zstd_lap"]
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(names) + 1.6))
    height = 0.8 / len(methods)
    for j, (key, label) in enumerate(methods):
        vals = [r[key] / r["points"] for r in races][::-1]
        ys = [i + (len(methods) - 1 - j - (len(methods) - 1) / 2) * height for i in range(len(names))]
        ax.barh(ys, vals, height=height * 0.9, color=SERIES[j], label=label, edgecolor=SURFACE, linewidth=1)
    ax.axvline(1.37, color=INK, linestyle="--", linewidth=1)
    ax.text(1.37, len(names) - 0.4, " paper: 1.37", fontsize=8, color=INK, va="bottom")
    ax.set_yticks(range(len(names)), names)
    ax.set_xlabel("bytes per point (raw = 16)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Compressed size per race")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08 - 0.9 / (0.55 * len(names) + 1.6)),
              ncol=2, fontsize=8)
    _save(fig, out_dir, "fig1_bytes_per_point.png")

# create a bar chart of bits per value for each channel.
def channel_bits(out_dir, channels, chan, ts_bits):
    labels = channels + ["Timestamp (shared)"]
    vals = [chan[c]["bits_per_value"] for c in channels] + [ts_bits]
    fig, ax = plt.subplots(figsize=(7, 3.4))
    bars = ax.barh(labels[::-1], vals[::-1], color=SERIES[0], height=0.6)
    bars[0].set_color(NEUTRAL)  # timestamps are a different kind of cost
    _hbar_value_labels(ax, bars, "{:.2f}")
    ax.set_xlim(0, max(vals) * 1.15)
    ax.set_xlabel("bits per value, all races (raw = 64)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Cost of each channel")
    _save(fig, out_dir, "fig2_channel_bits.png")

# create a bar chart of value cases for each channel.
def value_cases(out_dir, channels, chan):
    rows = channels + ["Paper (Facebook)"]
    data = [[chan[c][k] for k in ("repeat", "reuse", "new")] for c in channels] + [[51.0, 30.0, 19.0]]
    labels = ["repeat (0)", "reuse window (10)", "new window (11)"]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = list(range(len(rows)))[::-1]
    left = [0.0] * len(rows)
    for j, label in enumerate(labels):
        widths = [d[j] for d in data]
        bars = ax.barh(y, widths, left=left, color=SERIES[j], height=0.62, label=label,
                       edgecolor=SURFACE, linewidth=2)
        for bar, w in zip(bars, widths):
            if w >= 9:
                ax.text(bar.get_x() + w / 2, bar.get_y() + bar.get_height() / 2, f"{w:.0f}%",
                        ha="center", va="center", fontsize=8, color="white" if j != 2 else INK)
        left = [a + b for a, b in zip(left, widths)]
    ax.set_yticks(y, rows)
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of values that changed or repeated (%)")
    ax.grid(False)
    ax.set_title("Which XOR case each value uses")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, fontsize=8)
    _save(fig, out_dir, "fig3_value_cases.png")

# create a bar chart of timestamp buckets for all races.
def timestamp_buckets(out_dir, all_time):
    names = ["zero", "7-bit", "9-bit", "12-bit", "32-bit"]
    total = sum(all_time.values())
    ours = [100.0 * all_time[n] / total for n in names]
    labels = ["0  (1 bit)", "10 + 7 bits", "110 + 9 bits", "1110 + 12 bits", "1111 + 32 bits"]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.barh(labels[::-1], ours[::-1], color=SERIES[0], height=0.6, label="F1, all races")
    _hbar_value_labels(ax, bars, "{:.1f}%")
    ax.barh([labels[0]], [96.0], color="none", edgecolor=INK, linestyle="--", height=0.6,
            linewidth=1, label="paper: 96% in the 1-bit case")
    ax.set_xlim(0, 105)
    ax.set_xlabel("share of timestamps (%)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Delta-of-delta buckets used by timestamps")
    ax.legend(loc="lower right", fontsize=8)
    _save(fig, out_dir, "fig4_timestamp_buckets.png")

# create a line chart of block size and query time for each race.
def block_size(out_dir, block_rows, timing_name):
    labels = [r[0] for r in block_rows]
    size = [float(r[1]) for r in block_rows]
    query = [float(r[2]) for r in block_rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, vals, title, ylabel, fmt in (
            (a1, size, "Size", "bytes per point, all races", "{:.3f}"),
            (a2, query, f"One-lap query ({timing_name})", "median ms", "{:.1f}")):
        ax.plot(labels, vals, color=SERIES[0], linewidth=2, marker="o", markersize=7,
                markeredgecolor=SURFACE, markeredgewidth=2)
        for x, v in zip(labels, vals):
            ax.annotate(fmt.format(v), (x, v), textcoords="offset points", xytext=(0, 8),
                        ha="center", fontsize=8, color=INK_2)
        ax.set_xlabel("laps per block")
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(vals) * 1.25)
        ax.set_title(title)
        ax.grid(axis="x", visible=False)
    fig.suptitle("Laps per block: size against one-lap query time", x=0.01, ha="left",
                 fontweight="bold", fontsize=12)
    _save(fig, out_dir, "fig5_block_size.png")

# create a bar chart of timestamp buckets for each race.
def ablations(out_dir, reuse_rows, ts):
    dod_bits, delta_bits, samples = ts
    names = [r[0] for r in reuse_rows] + ["Timestamps"]
    paper = [float(r[1]) for r in reuse_rows] + [dod_bits / samples]
    without = [float(r[2]) for r in reuse_rows] + [delta_bits / samples]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = list(range(len(names)))[::-1]
    h = 0.36
    b1 = ax.barh([v + h / 2 for v in y], paper, height=h * 0.92, color=SERIES[0],
                 label="as in the paper", edgecolor=SURFACE, linewidth=1)
    b2 = ax.barh([v - h / 2 for v in y], without, height=h * 0.92, color=SERIES[1],
                 label="without window reuse / with plain deltas", edgecolor=SURFACE, linewidth=1)
    _hbar_value_labels(ax, b1, "{:.2f}")
    _hbar_value_labels(ax, b2, "{:.2f}")
    ax.set_yticks(y, names)
    ax.set_xlim(0, max(without + paper) * 1.15)
    ax.set_xlabel("bits per value, all races")
    ax.grid(axis="y", visible=False)
    ax.set_title("What each idea saves")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=8)
    _save(fig, out_dir, "fig6_ablations.png")

# draw all the charts.
def draw_all(out_dir, races, channels, chan, all_time, block_rows, reuse_rows, ts, timing_name):
    bytes_per_point(out_dir, races)
    total_time_bits = sum(r["time_bits"] for r in races)
    channel_bits(out_dir, channels, chan, total_time_bits / sum(r["samples"] for r in races))
    value_cases(out_dir, channels, chan)
    timestamp_buckets(out_dir, all_time)
    block_size(out_dir, block_rows, timing_name)
    ablations(out_dir, reuse_rows, ts)
