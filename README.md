# DiffCheck

When a business rule is migrated from imperative code to a declarative spec, how
often does the new version **pass its tests and still behave differently**?

**Silent divergence** = passes all 5 golden tests AND disagrees with the legacy
rule on at least one input. That translation would have shipped.

## Result

3 models (`gpt-4o-mini`, `gpt-4o`, `gpt-4.1-mini`) x 2 runs = **6 model-runs**.
11 rules, 4000 inputs per rule, identical prompt and identical inputs throughout.

**A silent divergence is reported only if it reproduces in every run of that
model.** Two rules qualify:

| rule | silent in | disagreements, every run |
|---|---|---|
| `return_eligible` | 6/6 model-runs | 132 |
| `new_account_hold` | 6/6 model-runs | 88 |

Same rules, same counts, across three models and two runs each. Capability does
not help: `gpt-4.1-mini` has the fewest failures overall and gets both of these
exactly as wrong.

**Single-run silent divergences are excluded, deliberately.** `order_status` for
`gpt-4o-mini` and `priority` for `gpt-4o` each appeared in one run of two.
Translations are generated at temperature 0, but output still varies between
calls, so a divergence seen once is not distinguishable from sampling noise.
Counting it would inflate the result with variance. Excluding it is why the
headline is a reproducible pair rather than a per-model rate, and per-model
totals in `FINDINGS.md` (2/11 or 3/11) include the excluded cases.

Distinguishing the two properly would take 3 to 5 runs per model. With two runs
the honest claim is the reproducible core, which is the claim this project makes.

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

A separate failure mode, invented operators such as `not in` and `not_in`, fails
**loudly**: every such spec is caught by the suite. It is a failure to follow the
output format, not a mistranslation, and it is not a third outcome; those specs
sit inside "caught by tests". Complexity band predicts loud failure; the semantic
gap predicts silent failure, and the band label misses it.

## Does a bigger test suite help?

No. `dose_response.py` varies suite size and, crucially, how test inputs are drawn:

```
suite size                        5       10       25       50      100      200      400
fields always present          7.65     7.05     6.62     6.47     6.25     6.08     6.00
fields sometimes missing       6.60     5.67     3.12     1.80     0.55     0.05     0.00
```

silent divergences out of 33 translations, mean of 40 drawn suites

Every field populated, which is how people write tests: **flat at 6 from N=25 on**.
400 cases catch what 25 catch. Fields missing 5% of the time: all found by 200.
**Suite size does not predict migration safety; suite distribution does.**

Both conditions test null *values*; they differ in whether a field can be absent.
Chart: `charts/dose_response.png`.

## Run

API key in `.env` (gitignored) as `OPENAI_API_KEY=sk-...`.

```
for m in gpt-4o-mini gpt-4o gpt-4.1-mini; do
  python3 translate.py $m                                  # 11 API calls each
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
| `rules.py` | 11 legacy rules, plain Python classifiers over an order record, in 3 complexity bands |
| `make_tests.py` -> `tests.json` | 5 golden tests per rule, answers taken from the legacy rule, **frozen before any translation** |
| `translate.py` | one frozen prompt per rule, temp 0, raw output saved to `specs/<model>/raw/` |
| `checker.py` | 19-line decision-table engine + differential run on 4000 seeded inputs (2000 random, 2000 on the thresholds) |
| `analyze.py` -> `FINDINGS.md` | summary table and generated write-up; takes one results file or several |
| `charts.py` -> `charts/` | the two charts that carry the finding |
| `dose_response.py` | suite size vs input distribution |

## Why it holds up

- The engine is 19 lines (`cond_holds` + `run_table`). Nothing is hidden.
- Rules, tests, thresholds and seed are fixed before any translation exists and
  never edited after. Raw model output is kept beside every parsed table.
- "No divergence found" means none appeared in 4000 inputs, not "proven equal".

## Limits

- **The rules are mine.** I wrote the `or 0` that produces the core finding. The
  class of bug is demonstrated; the *rate* needs rules mined from real codebases.
- **The core rests on one idiom.** Two instances, one mechanism, one field type.
- **Two runs per model is thin.** It is enough to separate a reproducible result
  from a single-run one, not enough to estimate how often the single-run kind
  occurs. 3 to 5 runs per model would settle it.
- **One rule was removed, not scored around.** `coupon_kind` classified coupons by
  prefix, which the nine allowed operators cannot express, so no correct answer
  existed and it tested nothing about translation. It is out of the rule set; its
  raw responses remain in `specs/<model>/raw/`.
- **The harness is unverified.** Nothing checks that the engine interprets a
  correct spec faithfully, or that 4000 inputs are sharp enough to catch a
  boundary error. Those two properties are what make a disagreement count mean
  anything, and they currently rest on inspection alone.
- Synthetic rules, one domain, classification only. Differential testing finds
  divergence but cannot prove its absence.
