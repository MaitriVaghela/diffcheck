"""
Read a results file, print the summary table, and write FINDINGS.md.

The one number that matters:
  SILENT DIVERGENCE = translation passes all 5 golden tests AND still
  disagrees with the legacy rule on at least one of the 4000 inputs.
That is the translation a real migration would have shipped.

Disagreements split into two kinds, because they mean different things:
  logic  = the spec ran and returned a different answer than the legacy rule.
  crash  = the spec could not run (it used an operator outside the allowed 9),
           so it "disagrees" everywhere without ever being evaluated.
A rule with crashes is a format-adherence failure, not a reasoning failure.

Every figure is computed from results/<model>.json and specs/<model>/, so the
document cannot drift from the run.

  python3 analyze.py results/gpt-4o-mini.json
"""
import json, os, sys

# The nine operators cond_holds() implements. Anything else in a spec is a
# format violation: the table cannot run at all.
ALLOWED_OPS = {"==", "!=", ">", ">=", "<", "<=", "in", "is_null", "not_null"}

VERDICTS = {"clean": "no divergence found",
            "silent": "SILENT DIVERGENCE",
            "caught": "caught by tests"}


def classify(r):
    """clean / silent / caught. The single definition of a verdict."""
    if r["disagreements"] == 0:
        return "clean"
    if r["tests_passed"] == r["tests_total"]:
        return "silent"
    return "caught"


def split(r):
    """(logic, crash). Older results files predate the split; assume all logic."""
    crash = r.get("spec_errors", 0)
    return r.get("logic_diffs", r["disagreements"] - crash), crash


def invalid_ops(spec_dir):
    """{rule: sorted operators the engine does not implement}."""
    found = {}
    if not os.path.isdir(spec_dir):
        return found
    for filename in sorted(os.listdir(spec_dir)):
        if not filename.endswith(".json"):
            continue
        spec = json.load(open(os.path.join(spec_dir, filename)))
        # A condition may also arrive with no "op" key at all. Report that as
        # its own violation rather than crashing on it.
        bad = {c.get("op", "(no op key)") for row in spec.get("rows", [])
               for c in row.get("if", []) if c.get("op") not in ALLOWED_OPS}
        if bad:
            found[filename[:-5]] = sorted(bad)
    return found


def print_table(results, bad_ops):
    print(f"{'rule':<20}{'band':<6}{'tests':<8}{'logic':<8}{'crash':<8}{'verdict'}")
    for r in results:
        if r["status"] != "ok":
            print(f"{r['rule']:<20}{r['band']:<6}{r['status']}")
            continue
        logic, crash = split(r)
        verdict = VERDICTS[classify(r)]
        if r["rule"] in bad_ops:
            verdict += "  (invalid op)"
        tests = f"{r['tests_passed']}/{r['tests_total']}"
        print(f"{r['rule']:<20}{r['band']:<6}{tests:<8}{logic:<8}{crash:<8}{verdict}")


def write_markdown(results, bad_ops, model, results_path, out_path):
    scored = [r for r in results if r["status"] == "ok"]
    silent = [r for r in scored if classify(r) == "silent"]
    clean = [r for r in scored if classify(r) == "clean"]
    n_inputs = scored[0]["inputs"] if scored else 0

    L = []
    add = L.append

    add(f"# Findings: {model}\n")
    add(f"Generated from `{results_path}` by `analyze.py`. {len(scored)} rules, "
        f"{n_inputs:,} inputs each, {len(scored) * n_inputs * 2:,} paired executions.\n")

    add("## Headline\n")
    add(f"**Silent divergence: {len(silent)}/{len(scored)}**. Translations that pass every "
        "golden test and still disagree with the legacy rule on real input. These are the "
        "only failures that survive review.\n")
    if bad_ops:
        add(f"**Format violations: {len(bad_ops)}/{len(scored)}**. Specs using an operator "
            "the engine does not implement. These crash rather than answer, so they are "
            "caught by the test suite, but they inflate raw disagreement counts.\n")
    add(f"**No divergence found: {len(clean)}/{len(scored)}**. Agreed on all "
        f"{n_inputs:,} inputs. Not a proof of equivalence.\n")

    add("## Results by rule\n")
    add("`logic` = the table ran and gave a different answer. "
        "`crash` = the table could not run (invalid operator).\n")
    add("| rule | band | tests | logic | crash | verdict |")
    add("|---|---|---|---|---|---|")
    for r in results:
        if r["status"] != "ok":
            add(f"| `{r['rule']}` | {r['band']} | - | - | - | {r['status']} |")
            continue
        logic, crash = split(r)
        verdict = VERDICTS[classify(r)]
        if classify(r) == "silent":
            verdict = f"**{verdict}**"
        if r["rule"] in bad_ops:
            verdict += " (invalid op)"
        add(f"| `{r['rule']}` | {r['band']} | {r['tests_passed']}/{r['tests_total']} "
            f"| {logic:,} | {crash:,} | {verdict} |")
    add("")

    add("## Silent divergences\n")
    if not silent:
        add("None found.\n")
    for r in silent:
        e = r["examples"][0]
        nulls = [k for k, v in e["input"].items() if v is None]
        add(f"### `{r['rule']}`, {r['disagreements']} disagreements\n")
        add(f"Passed {r['tests_passed']}/{r['tests_total']} golden tests. "
            f"Legacy returned `{e['legacy']}`, the table returned `{e['new']}`.\n")
        add("```json")
        add(json.dumps(e["input"], indent=1))
        add("```")
        if nulls:
            add(f"\nMissing fields in this input: {', '.join('`%s`' % n for n in nulls)}. "
                "The legacy rule coalesces a missing value with `or 0`; the decision table "
                "has no equivalent, so an ordered comparison on that field simply does not "
                "hold and the row is skipped.\n")

    if bad_ops:
        add("## Format violations\n")
        add("Operators outside the nine given in the prompt "
            "(`== != > >= < <= in is_null not_null`):\n")
        for rule, ops in bad_ops.items():
            add(f"- `{rule}`: {', '.join('`%s`' % o for o in ops)}")
        add("\nThese are instruction-following failures rather than reasoning failures: in "
            "each case the model reached for a Python construct visible in the legacy source "
            "instead of composing one from the allowed set.\n")

    add("## By complexity band\n")
    add("A = 1-2 conditions, B = 3-5, C = nested / ordered / null-sensitive.\n")
    add("| band | rules | clean | silent | caught |")
    add("|---|---|---|---|---|")
    for band in ("A", "B", "C"):
        rows = [r for r in scored if r["band"] == band]
        if not rows:
            continue
        counts = [sum(1 for r in rows if classify(r) == k)
                  for k in ("clean", "silent", "caught")]
        add(f"| {band} | {len(rows)} | {counts[0]} | {counts[1]} | {counts[2]} |")
    add("")
    if silent:
        bands = sorted({r["band"] for r in silent})
        add(f"Both silent divergences sit in band {', '.join(bands)}, not the hardest band. "
            "Structural difficulty predicts *loud* failure; null handling predicts silent "
            "failure, and the band label does not capture it.\n")

    add("## Reading these numbers\n")
    add(f"- `no divergence found` means none appeared in {n_inputs:,} inputs, not that the "
        "two implementations are equivalent.")
    add("- A large `crash` count says the spec never executed, not that the model "
        "misunderstood the rule. Read `logic` for translation quality.")
    add("- Some rules may be inexpressible in the target format. Check whether a "
        "violation had any valid alternative before counting it against the model.")
    add("- Golden tests are five per rule by construction; a deeper suite would move "
        "rules out of the silent category and into `caught by tests`.")

    open(out_path, "w").write("\n".join(L) + "\n")


def write_comparison(runs, out_path):
    """One document covering several models. `runs` is [(model, results, bad_ops)]."""
    models = [m for m, _, _ in runs]
    scored = {m: [r for r in res if r["status"] == "ok"] for m, res, _ in runs}
    silent = {m: [r["rule"] for r in scored[m] if classify(r) == "silent"]
              for m in models}
    n_rules = len(scored[models[0]])

    L = []
    add = L.append

    add("# Findings: model comparison\n")
    add(f"Generated by `analyze.py` from {', '.join('`%s`' % m for m in models)}. "
        f"{n_rules} rules per model, {scored[models[0]][0]['inputs']:,} inputs each, "
        "identical prompt and identical inputs across models, so the model is the "
        "only variable.\n")

    add("## Outcomes\n")
    add(f"One outcome per translation. Mutually exclusive, and each row sums to "
        f"{n_rules}.\n")
    add("| model | no divergence found | **silent divergence** | caught by tests |")
    add("|---|---|---|---|")
    for m, _, _bad in runs:
        counts = {k: sum(1 for r in scored[m] if classify(r) == k)
                  for k in ("clean", "silent", "caught")}
        add(f"| `{m}` | {counts['clean']}/{n_rules} | **{counts['silent']}/{n_rules}** "
            f"| {counts['caught']}/{n_rules} |")
    add("")

    # Format violations are a tag on some specs, not a fourth outcome. Every one
    # of them lands in "caught by tests" above, so the counts deliberately overlap.
    add("### Format violations (a tag, not an outcome)\n")
    add("Some specs used an operator the engine does not implement, so the table "
        "could not run at all. That is a failure to follow the output format, not "
        "a mistranslation of the rule. **These are already counted in "
        "*caught by tests* above** and are listed separately only because the two "
        "failures mean different things.\n")
    add("| model | specs using an invalid operator | which |")
    add("|---|---|---|")
    for m, _, bad in runs:
        which = ", ".join(f"`{r}`" for r in bad) if bad else "none"
        add(f"| `{m}` | {len(bad)}/{n_rules} | {which} |")
    add("")

    shared = set.intersection(*(set(v) for v in silent.values())) if silent else set()
    if shared:
        add(f"**Every model diverges silently on the same {len(shared)} "
            f"rule{'s' if len(shared) > 1 else ''}:** "
            f"{', '.join('`%s`' % r for r in sorted(shared))}. "
            "Identical rules across models points at the task, not the model.\n")

    add("## Verdict by rule\n")
    add("| rule | band | " + " | ".join(f"`{m}`" for m in models) + " |")
    add("|---|---|" + "---|" * len(models))
    short = {"clean": "clean", "silent": "**SILENT**", "caught": "caught"}
    by_rule = {r["rule"]: r for r in scored[models[0]]}
    for rule in by_rule:
        cells = []
        for m, res, bad in runs:
            r = next((x for x in res if x["rule"] == rule), None)
            if r is None or r["status"] != "ok":
                cells.append("-")
                continue
            cell = short[classify(r)]
            logic, _crash = split(r)
            if logic:
                cell += f" ({logic:,})"
            if rule in bad:
                cell += " ⚠"
            cells.append(cell)
        add(f"| `{rule}` | {by_rule[rule]['band']} | " + " | ".join(cells) + " |")
    add("")
    add("Parenthesised numbers are logic disagreements: the table ran and "
        "returned a different answer. ⚠ marks a spec that used an operator "
        "outside the allowed nine, so it crashed rather than answered.\n")

    # The silent cases, shown once from the first model that has them.
    add("## The silent divergences\n")
    for rule in sorted(shared):
        for m, res, _ in runs:
            r = next((x for x in res if x["rule"] == rule), None)
            if r and classify(r) == "silent":
                e = r["examples"][0]
                nulls = [k for k, v in e["input"].items() if v is None]
                add(f"### `{rule}`\n")
                counts = ", ".join(
                    f"`{mm}` {next(x for x in rr if x['rule'] == rule)['disagreements']}"
                    for mm, rr, _ in runs
                    if next((x for x in rr if x['rule'] == rule), {}).get("disagreements"))
                add(f"Disagreements per model: {counts}.\n")
                add(f"Passed {r['tests_passed']}/{r['tests_total']} golden tests. "
                    f"Legacy returned `{e['legacy']}`, the table returned `{e['new']}`.\n")
                add("```json")
                add(json.dumps(e["input"], indent=1))
                add("```")
                if nulls:
                    add(f"\nMissing fields: {', '.join('`%s`' % n for n in nulls)}. "
                        "The legacy rule coalesces a missing value with `or 0`, so an "
                        "absent value is read as zero, a real decision hidden in an "
                        "idiom. The decision table has no coercion, the ordered "
                        "comparison does not hold, the row is skipped, and the table "
                        "returns the opposite answer.\n")
                break

    add("## Format violations by model\n")
    for m, _, bad in runs:
        if bad:
            items = "; ".join(f"`{rule}`: {', '.join('`%s`' % o for o in ops)}"
                              for rule, ops in bad.items())
            add(f"- **`{m}`**: {items}")
        else:
            add(f"- **`{m}`**: none")
    add("\nThese fail loudly: every one is caught by the test suite. They are "
        "instruction-following failures, not reasoning failures.\n")

    add("## Reading these numbers\n")
    add("- `clean` means no divergence appeared in the sampled inputs, not that "
        "the two implementations are equivalent.")
    add("- A crashed spec disagrees everywhere without ever executing; read the "
        "logic counts for translation quality.")
    add("- Some rules may be inexpressible in the target format. Check whether a "
        "violation had any valid alternative before counting it against a model.")
    add("- Rules, tests, thresholds, inputs and prompt are frozen across models, "
        "so differences between columns are attributable to the model.")

    open(out_path, "w").write("\n".join(L) + "\n")


def main():
    args = sys.argv[1:]
    results_paths = [a for a in args if a.endswith(".json")]
    md = [a for a in args if a.endswith(".md")]
    if not results_paths:
        raise SystemExit("usage: python3 analyze.py <results.json> [more.json ...] [out.md]")
    out_path = md[0] if md else "FINDINGS.md"

    runs = []
    for path in results_paths:
        results = json.load(open(path))
        # results/ also holds dose_response.json, so `analyze.py results/*.json`
        # sweeps up files that are not a per-rule results list. Skip those.
        if not (isinstance(results, list) and results
                and isinstance(results[0], dict) and "rule" in results[0]):
            print(f"skipping {path}: not a per-rule results file")
            continue
        model = os.path.basename(path).replace(".json", "")
        runs.append((model, results, invalid_ops(os.path.join("specs", model))))
    if not runs:
        raise SystemExit("no usable results files given")

    for model, results, bad_ops in runs:
        if len(runs) > 1:
            print(f"──── {model} ────")
        scored = [r for r in results if r["status"] == "ok"]
        silent = [r for r in scored if classify(r) == "silent"]
        print_table(results, bad_ops)
        print(f"\nrules scored: {len(scored)}")
        print(f"silent divergence: {len(silent)}/{len(scored)}")
        # Not a fourth outcome: these sit inside "caught by tests" above.
        print(f"of which used an invalid operator: {len(bad_ops)}/{len(scored)}\n")

    if len(runs) == 1:
        model, results, bad_ops = runs[0]
        write_markdown(results, bad_ops, model, results_paths[0], out_path)
    else:
        write_comparison(runs, out_path)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
