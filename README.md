# DiffCheck

When a business rule is migrated from imperative code to a declarative spec, how
often does the new version **pass its tests and still behave differently**?

**Silent divergence** = passes all 5 golden tests AND disagrees with the legacy
rule on at least one input. That translation would have shipped.

## Result

3 models (`gpt-4o-mini`, `gpt-4o`, `gpt-4.1-mini`), 2 runs each, identical prompt
and identical inputs throughout. 12 rules, 4000 inputs per rule.

**Core (reproducible).** `return_eligible` and `new_account_hold` diverge silently
in all 6 runs with the same counts every time: **132 and 88**. Capability does not
help; `gpt-4.1-mini` is the best translator overall and gets both exactly as wrong.

**Tail (noisy).** Other silent divergences appear and vanish between runs at
temperature 0. Per-model totals move between 2/12 and 3/12. Cite the core.

Per-run numbers are in `FINDINGS.md`, regenerated from the results.

## Cause

The legacy rule coalesces a missing value to zero:

```python
if (o["account_age_days"] or 0) < 7:     # None -> 0 -> 0 < 7 -> True
    return False
```

A *missing* age therefore means **day zero, a brand-new account**: a business
decision written as defensive boilerplate. The model transcribes the comparison
faithfully:

```json
{"field": "account_age_days", "op": "<", "value": 7}
```

A decision table has no coercion, so the condition does not hold on `null`, the
row is skipped, and the table returns the opposite answer. Right field, right
threshold, right operator, right row order.

Three things make it more than a bug report:

- **Fixable.** One `is_null` row takes `return_eligible` from 132 disagreements
  to 0. Every model had `is_null` and used it correctly elsewhere.
- **The rule was in the prompt.** It states that ordered comparisons do not hold
  on missing fields. Having the fact was not enough to connect it to `or 0`.
- **Null testing did not help, for a non-obvious reason.** The suite does test
  nulls. `insurance_required` even has a deliberate `amount=None` case, because
  that rule's source says `if amt is None` **visibly**, and it is never silent.
  Null testing tracks *visible* null handling; `or 0` does not look like any.

A separate failure mode, `starts_with` and `not in` and other invented operators,
fails **loudly**: caught by the suite every time. Complexity band predicts loud
failure; the semantic gap predicts silent failure, and the band label misses it.

## Does a bigger test suite help?

No. `dose_response.py` varies suite size and, crucially, how test inputs are drawn:

```
suite size                        5       10       25       50      100      200      400
fields always present          8.22     7.28     6.67     6.47     6.25     6.08     6.00
fields sometimes missing       7.17     5.90     3.17     1.80     0.55     0.05     0.00
```

silent divergences out of 36 translations, mean of 40 drawn suites

Every field populated, which is how people write tests: **flat at 6 from N=25 on**.
400 cases catch what 25 catch. Fields missing 5% of the time: all found by 200.
**Suite size does not predict migration safety; suite distribution does.**

Both conditions test null *values*; they differ in whether a field can be absent.
Chart: `charts/dose_response.png`.

## Run

API key in `.env` (gitignored) as `OPENAI_API_KEY=sk-...`.

```
for m in gpt-4o-mini gpt-4o gpt-4.1-mini; do
  python3 translate.py $m                                  # 12 API calls each
  python3 checker.py --specs specs/$m --out results/$m.json
done
python3 analyze.py results/*.json          # tables + comparison FINDINGS.md
python3 charts.py results/gpt-4o-mini.json # charts/*.png (needs matplotlib)
python3 dose_response.py results/*.json    # the suite-size study
```

Re-scoring specs already on disk is free and skips the model:

```
python3 checker.py --specs specs/gpt-4o-mini --out results/gpt-4o-mini.json && python3 analyze.py results/gpt-4o-mini.json
```

`make_tests.py` regenerates `tests.json`; it is already committed and frozen.

## Files

| file | what it is |
|---|---|
| `rules.py` | 12 legacy rules, plain Python classifiers over an order record, in 3 complexity bands |
| `make_tests.py` -> `tests.json` | 5 golden tests per rule, answers taken from the legacy rule, **frozen before any translation** |
| `translate.py` | one frozen prompt per rule, temp 0, raw output saved to `specs/<model>/raw/` |
| `checker.py` | 25-line decision-table engine + differential run on 4000 seeded inputs (2000 random, 2000 on the thresholds) |
| `analyze.py` -> `FINDINGS.md` | summary table and generated write-up; takes one results file or several |
| `charts.py` -> `charts/` | the two charts that carry the finding |
| `dose_response.py` | suite size vs input distribution |

## Why it holds up

- The engine is 25 lines (`run_table`). Nothing is hidden.
- Rules, tests, thresholds and seed are fixed before any translation exists and
  never edited after. Raw model output is kept beside every parsed table.
- `checker.py` has a self-test (currently commented out): a hand translation must
  give 0 disagreements, and a `>` for `>=` break must give more than 0. Both run
  before any model output exists.
- "No divergence found" means none appeared in 4000 inputs, not "proven equal".

## Limits

- **The rules are mine.** I wrote the `or 0` that produces the core finding. The
  class of bug is demonstrated; the *rate* needs rules mined from real codebases.
- **The core rests on one idiom.** Two instances, one mechanism, one field type.
- **Per-model totals are noisy** between runs at temperature 0.
- **`coupon_kind` is inexpressible, not mistranslated.** "Starts with SAVE" cannot
  be written with the nine allowed operators unless the prompt enumerates every
  coupon value, which it does not. Do not count it against a model.
- **The harness has no test suite.** The engine, generator and response parser are
  covered only by the commented-out self-test and ad-hoc checks.
- Synthetic rules, one domain, classification only. Differential testing finds
  divergence but cannot prove its absence.
