"""
How big does a golden test suite have to be before silent divergence disappears?

  python3 dose_response.py results/gpt-4o-mini.json results/gpt-4o.json ...

A silent divergence is a translation that passes its whole suite and still
disagrees with the legacy rule. The obvious remedy is "write more tests". This
measures whether that works.

The catch is that "more tests" is underspecified, so the DISTRIBUTION the tests
are drawn from is made an explicit variable rather than a buried assumption:

  fields always present   every field is populated. NOTE this is not "no null
                          testing": coupon is still drawn from a pool including
                          None, because an absent coupon is a legitimate value a
                          person would test. What never happens is a field going
                          MISSING. tests.json is drawn this way.
  fields sometimes missing
                          any field is absent 5% of the time, the same
                          distribution the differential check uses.

The distinction matters because the suite in tests.json does test nulls: every
case has a null coupon, and insurance_required has a deliberate amount=None case
written because that rule's source says `if amt is None`, visibly. The rules
that diverge silently hide their null handling inside `or 0`, which reads as a
default rather than a null branch, so no one wrote the case.

For each suite size N, a spec "would have shipped" if it matches the legacy rule
on all N cases. It is a silent divergence if it shipped AND still disagrees
somewhere in the 4000-input differential run. Repeated over many draws, so each
point is a mean rather than one lucky suite.

Test cases are drawn from a seed stream disjoint from the differential inputs,
so a suite is never scored against the cases that generated it.
"""
import json, os, random, sys

import checker
from rules import RULES

SIZES = [5, 10, 25, 50, 100, 200, 400]
TRIALS = 40             # independent suites drawn per (size, condition)
TEST_SEED_BASE = 90000  # disjoint from all_inputs' seed 2026

CONDITIONS = [("fields always present", 0.0), ("fields sometimes missing", 0.05)]


def draw_suite(rng, n, null_rate):
    """n test cases the way make_tests.py builds them: inputs, legacy answers."""
    # Half boundary, half free: a hand-written suite does probe thresholds.
    return [make for make in
            (checker.make_input(rng, i % 2 == 1, null_rate) for i in range(n))]


def ships(spec, cases, fn):
    """Would this translation pass review? True if it matches on every case."""
    return all(checker._safe(spec, o) == fn(o) for o in cases)


def run(results_paths):
    # Which (model, rule) pairs actually diverge, from the committed results.
    diverges, specs = {}, {}
    for path in results_paths:
        model = os.path.basename(path).replace(".json", "")
        for r in json.load(open(path)):
            if r["status"] != "ok":
                continue
            diverges[(model, r["rule"])] = r["disagreements"] > 0
            specs[(model, r["rule"])] = json.load(
                open(os.path.join("specs", model, r["rule"] + ".json")))
    fns = {name: fn for name, fn, _ in RULES}
    pairs = sorted(specs)

    table = {}  # (condition, size) -> mean silent count across all pairs
    for cond_name, null_rate in CONDITIONS:
        for size in SIZES:
            silent_total = 0
            for trial in range(TRIALS):
                rng = random.Random(TEST_SEED_BASE + trial)
                cases = draw_suite(rng, size, null_rate)
                for key in pairs:
                    if not diverges[key]:
                        continue          # nothing to hide: it agrees everywhere
                    if ships(specs[key], cases, fns[key[1]]):
                        silent_total += 1
            table[(cond_name, size)] = silent_total / TRIALS
    return table, len(pairs)


def print_table(table, n_pairs):
    print(f"silent divergences out of {n_pairs} translations, "
          f"mean of {TRIALS} suites\n")
    w = max(len(c) for c, _ in CONDITIONS) + 2
    head = "".join(f"{s:>9}" for s in SIZES)
    print(f"{'suite size':<{w}}{head}")
    for cond_name, _ in CONDITIONS:
        row = "".join(f"{table[(cond_name, s)]:>9.2f}" for s in SIZES)
        print(f"{cond_name:<{w}}{row}")


def chart(table, n_pairs, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from charts import SURFACE, INK, INK_SOFT, INK_FAINT, GRID, LOGIC

    AQUA = "#1baf7a"   # categorical slot 3; all-pairs validated against slot 1
    colors = {"fields always present": LOGIC, "fields sometimes missing": AQUA}

    fig, ax = plt.subplots(figsize=(9.6, 5.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for cond_name, _ in CONDITIONS:
        ys = [table[(cond_name, s)] for s in SIZES]
        ax.plot(SIZES, ys, color=colors[cond_name], linewidth=2,
                marker="o", markersize=6, markeredgecolor=SURFACE,
                markeredgewidth=1.5, label=cond_name, clip_on=False, zorder=3)
        ax.text(SIZES[-1] * 1.06, ys[-1], cond_name, color=colors[cond_name],
                fontsize=10, va="center", fontweight="medium")

    ax.set_xscale("log")
    ax.set_xticks(SIZES)
    ax.set_xticklabels([str(s) for s in SIZES])
    ax.set_xlim(SIZES[0] * .9, SIZES[-1] * 1.9)
    # A little headroom below zero so the "with nulls" end label, which lands on
    # y=0, clears the axis line instead of sitting on it.
    top = max(table.values()) * 1.15 or 1
    ax.set_ylim(-top * .05, top)
    ax.set_yticks(range(0, int(top) + 1))
    ax.set_xlabel("Golden tests in the suite", fontsize=9.5, labelpad=10)
    ax.set_ylabel(f"Silent divergences (of {n_pairs} translations)",
                  fontsize=9.5, labelpad=10)
    ax.yaxis.grid(True, color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(length=0, colors=INK_SOFT)

    ax.set_title("More tests do not help. Different tests do.",
                 fontsize=15, color=INK, loc="left", pad=36, fontweight="medium")
    ax.text(0, 1.015,
            "Silent divergence against suite size, by how the test inputs were drawn",
            transform=ax.transAxes, fontsize=9.5, color=INK_FAINT)
    # Both conditions include null coupons; only the second lets fields go missing.
    ax.text(0, -.17,
            "Both conditions test null values. They differ in whether a field can be "
            "absent altogether.",
            transform=ax.transAxes, fontsize=8.5, color=INK_FAINT)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 dose_response.py <results.json> [more...]")
    table, n_pairs = run(sys.argv[1:])
    print_table(table, n_pairs)

    os.makedirs("charts", exist_ok=True)
    out = os.path.join("charts", "dose_response.png")
    chart(table, n_pairs, out)
    print("\nwrote", out)

    json.dump({f"{c}|{s}": v for (c, s), v in table.items()},
              open("results/dose_response.json", "w"), indent=1)
    print("wrote results/dose_response.json")


if __name__ == "__main__":
    main()
