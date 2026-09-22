"""
Render the two charts that carry the finding, as PNGs for slides or a write-up.

  python3 charts.py results/gpt-4o-mini.json        -> charts/*.png

Two charts, each with one job:

  disagreements_by_rule.png
      Where the 4000 inputs disagreed, per rule, split into the two kinds that
      mean different things: the table ran and was wrong (logic), or the table
      could not run at all (crash). Sorted, so scale is readable at a glance.

  golden_tests.png
      The finding itself. Bar length is golden tests passed. Two rules sit at a
      full 5/5 and are still wrong on real input. That contradiction is the
      whole experiment, so those two are the only ones in colour.

Colours are the reference categorical slots 1 and 2 (blue, orange), held to the
same meaning in both charts: blue always means "the table ran and was wrong".

Requires matplotlib. Everything else in this project is standard library only,
which is why charts live here and not in analyze.py.
"""
import json, os, sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ---------- tokens ----------

SURFACE   = "#fcfcfb"
INK       = "#0b0b0b"
INK_SOFT  = "#52514e"
INK_FAINT = "#8a8983"
GRID      = "#e5e4e0"

LOGIC = "#2a78d6"   # categorical slot 1: the table ran, wrong answer
CRASH = "#eb6834"   # categorical slot 2: the table could not run
QUIET = "#c9c8c3"   # de-emphasis grey for context marks

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": ["DejaVu Sans"],
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK_SOFT,
    "xtick.color": INK_SOFT,
    "ytick.color": INK,
    "axes.edgecolor": GRID,
    "axes.linewidth": 0.8,
})


def strip(ax, keep_x=True):
    """Recessive axes: no box, one hairline baseline, no tick marks."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_visible(keep_x)
    ax.tick_params(length=0)


def load(results_path):
    rows = [r for r in json.load(open(results_path)) if r["status"] == "ok"]
    for r in rows:
        r["crash"] = r.get("spec_errors", 0)
        r["logic"] = r.get("logic_diffs", r["disagreements"] - r["crash"])
        r["silent"] = (r["disagreements"] > 0
                       and r["tests_passed"] == r["tests_total"])
    return rows


# ---------- chart 1 ----------

def disagreements_by_rule(rows, out_path, model):
    rows = sorted(rows, key=lambda r: r["disagreements"])
    names = [r["rule"] for r in rows]
    y = range(len(rows))

    fig, ax = plt.subplots(figsize=(9, 5.6), dpi=200)

    # A 2px surface-coloured edge separates the two segments of a stack.
    ax.barh(y, [r["logic"] for r in rows], height=.62, color=LOGIC,
            edgecolor=SURFACE, linewidth=1.4, label="Logic: table ran, wrong answer")
    ax.barh(y, [r["crash"] for r in rows], height=.62, color=CRASH,
            edgecolor=SURFACE, linewidth=1.4, left=[r["logic"] for r in rows],
            label="Crash: table could not run")

    total = rows[0]["inputs"] if rows else 4000
    for i, r in enumerate(rows):
        d = r["disagreements"]
        label = "0" if d == 0 else f"{d:,}"
        ax.text(d + total * .012, i, label, va="center", ha="left",
                fontsize=9, color=INK_FAINT if d == 0 else INK_SOFT)

    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=9.5, fontfamily="DejaVu Sans Mono")
    ax.set_xlim(0, total * 1.09)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.set_xlabel(f"Orders where the two implementations disagreed  (of {total:,})",
                  fontsize=9.5, labelpad=10)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    strip(ax)

    # Title sits above the subtitle: pad clears the subtitle's own line box.
    ax.set_title("Where the translations broke", fontsize=15, color=INK,
                 loc="left", pad=36, fontweight="medium")
    ax.text(0, 1.015, f"{model} · one bar per migrated rule",
            transform=ax.transAxes, fontsize=9.5, color=INK_FAINT)

    ax.legend(loc="lower right", frameon=False, fontsize=9.5,
              handlelength=.9, handleheight=.9, borderpad=0, labelspacing=.5)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# ---------- chart 2 ----------

def golden_tests(rows, out_path, model):
    rows = sorted(rows, key=lambda r: (r["tests_passed"], -r["disagreements"]))
    names = [r["rule"] for r in rows]
    y = range(len(rows))

    fig, ax = plt.subplots(figsize=(9, 5.6), dpi=200)

    colors = [LOGIC if r["silent"] else QUIET for r in rows]
    ax.barh(y, [r["tests_passed"] for r in rows], height=.62, color=colors)

    for i, r in enumerate(rows):
        if r["silent"]:
            ax.text(r["tests_passed"] + .12, i,
                    f"passed every test, and is wrong on {r['disagreements']} orders",
                    va="center", ha="left", fontsize=9.5, color=LOGIC,
                    fontweight="medium")
        elif r["disagreements"] == 0:
            ax.text(r["tests_passed"] + .12, i, "no divergence found",
                    va="center", ha="left", fontsize=9, color=INK_FAINT)

    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=9.5, fontfamily="DejaVu Sans Mono")
    ax.set_xlim(0, 5)
    ax.set_xticks([0, 1, 2, 3, 4, 5])
    ax.set_xlabel("Golden tests passed (of 5, frozen before translation)",
                  fontsize=9.5, labelpad=10)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    strip(ax)

    n_silent = sum(1 for r in rows if r["silent"])
    ax.set_title("A full test suite is not evidence of a correct translation",
                 fontsize=15, color=INK, loc="left", pad=36, fontweight="medium")
    ax.text(0, 1.015,
            f"{model} · {n_silent} of {len(rows)} rules passed 5/5 and still diverged",
            transform=ax.transAxes, fontsize=9.5, color=INK_FAINT)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 charts.py <results.json>")
    results_path = sys.argv[1]
    model = os.path.basename(results_path).replace(".json", "")

    rows = load(results_path)
    os.makedirs("charts", exist_ok=True)

    one = os.path.join("charts", "disagreements_by_rule.png")
    two = os.path.join("charts", "golden_tests.png")
    disagreements_by_rule(rows, one, model)
    golden_tests(rows, two, model)
    print("wrote", one)
    print("wrote", two)


if __name__ == "__main__":
    main()
