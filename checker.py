"""
DiffCheck: the new side, and the comparison.

THE SPEC FORMAT (what the LLM must produce for each rule): a decision table.

    {
      "rows": [
        {"if": [ {"field": "...", "op": "...", "value": ...}, ... ],   # all must hold (AND)
         "then": <result: true/false/"label">},
        ...
      ],
      "else": <result>
    }

  The first row whose conditions all hold wins. If none match, "else" applies.
  Allowed ops: ==  !=  >  >=  <  <=  in  is_null  not_null
    - "in": value is a list.
    - ordered ops (> >= < <=) on a missing (None) field DO NOT hold.
    - "is_null" holds when the field is missing; it needs no "value".

run_table() below executes a spec. It is 25 lines. That is the entire engine.

Also here: input generation (random + boundary, fixed seed) and the
differential check itself. Run:  python3 checker.py --specs specs/<model>
"""
import argparse, json, os, random
from rules import RULES

# ---------- the whole spec engine ----------

def cond_holds(c, order):
    v = order.get(c["field"])
    op = c["op"]
    if op == "is_null":  return v is None
    if op == "not_null": return v is not None
    if op == "==":       return v == c["value"]
    if op == "!=":       return v != c["value"]
    if op == "in":       return v in c["value"]
    if v is None:        return False          # ordered comparison on missing field
    if op == ">":        return v > c["value"]
    if op == ">=":       return v >= c["value"]
    if op == "<":        return v < c["value"]
    if op == "<=":       return v <= c["value"]
    raise ValueError("unknown op " + op)

def run_table(spec, order):
    for row in spec["rows"]:
        if all(cond_holds(c, order) for c in row["if"]):
            return row["then"]
    return spec["else"]

# ---------- input generation (seeded, declared before any translation) ----------

COUNTRIES = ["US", "CA", "GB", "DE", "IN", "JP", "BR"]
TIERS = ["basic", "plus", "pro"]
COUPONS = [None, None, "SAVE10", "SAVE20", "SAVE5", "FREESHIP", "VIP", "BOGUS"]
CATEGORIES = ["electronics", "books", "apparel", "grocery", "furniture"]
# every threshold that appears in rules.py, +/- 1 and +/- 0.01 around each
AMOUNTS = sorted({t + d for t in (0, 50, 100, 200, 300, 500, 750, 1000)
                        for d in (-1, -0.01, 0, 0.01, 1) if t + d >= 0})
AGES    = sorted({t + d for t in (0, 7, 14, 30) for d in (-1, 0, 1) if t + d >= 0})
WEIGHTS = sorted({t + d for t in (0, 10, 20, 30) for d in (-1, -0.01, 0, 0.01, 1) if t + d >= 0})

def make_input(rng, boundary, null_rate=0.05):
    # One fake order: boundary=False picks numbers freely from the full range, boundary=True picks them from the cutoffs +/- a little.
    # null_rate is how often a field goes missing. 0.0 models the fully populated
    # orders a person writes by hand; the 0.05 default is what all_inputs uses.
    def maybe_none(v):
        return None if rng.random() < null_rate else v
    return {
        "amount":           maybe_none(rng.choice(AMOUNTS) if boundary else round(rng.uniform(0, 1500), 2)),
        "item_count":       maybe_none(rng.randint(0, 20)),
        "country":          maybe_none(rng.choice(COUNTRIES)),
        "tier":             maybe_none(rng.choice(TIERS)),
        "account_age_days": maybe_none(rng.choice(AGES) if boundary else rng.randint(0, 800)),
        "coupon":           rng.choice(COUPONS),
        "category":         maybe_none(rng.choice(CATEGORIES)),
        "weight_kg":        maybe_none(rng.choice(WEIGHTS) if boundary else round(rng.uniform(0, 40), 2)),
        "is_return":        rng.random() < 0.25,
    }

def all_inputs(n_each=2000, seed=2026):
    # 4000 order records from make_input, all sharing one seeded rng so the whole set is reproducible.
    rng = random.Random(seed)
    # 2000 orders with freely picked numbers, then 2000 with numbers on the cutoffs; each is tagged so a disagreement can be traced to its kind.
    return ([("random", make_input(rng, False)) for _ in range(n_each)] +
            [("boundary", make_input(rng, True)) for _ in range(n_each)])

# ---------- the differential check ----------

def check(spec_dir, out_path):
    tests = json.load(open("tests.json"))
    # Prepare the 4000 inputs once, then run each rule's legacy function and the LLM translation on all of them.
    inputs = all_inputs()
    results = []
    for name, fn, band in RULES:
        path = os.path.join(spec_dir, name + ".json")
        if not os.path.exists(path):
            results.append({"rule": name, "band": band, "status": "missing"})
            continue
        try:
            spec = json.load(open(path))
        except Exception as e:
            results.append({"rule": name, "band": band, "status": "bad json: %s" % e})
            continue

        # step 1: would this translation have shipped? (the frozen 5-case suite)
        tests_passed = sum(1 for t in tests[name]
                           if _safe(spec, t["input"]) == t["expected"])

        # step 2: differential execution against the legacy function
        disagreements = []
        # Two very different failures share the "disagreement" label: the spec ran
        # and gave a wrong answer, or it could not run at all (an operator the
        # engine does not have). Count the second kind separately.
        spec_errors = 0
        # kind is "random" or "boundary"; order is one fake record, e.g.
        # {"amount": 178.68, "item_count": 16, "country": "US", "tier": "pro",
        #  "account_age_days": 430, "coupon": "BOGUS", "category": "furniture",
        #  "weight_kg": 0.1, "is_return": False}      (any field can be None)
        for kind, order in inputs:
            legacy = fn(order)
            new = _safe(spec, order)
            if legacy != new:
                if isinstance(new, str) and new.startswith("SPEC_ERROR"):
                    spec_errors += 1
                disagreements.append({"kind": kind, "input": order,
                                      "legacy": legacy, "new": new})
        results.append({
            "rule": name, "band": band, "status": "ok",
            "tests_passed": tests_passed, "tests_total": len(tests[name]),
            "inputs": len(inputs), "disagreements": len(disagreements),
            "spec_errors": spec_errors,
            "logic_diffs": len(disagreements) - spec_errors,
            "examples": disagreements[:5],
        })
    json.dump(results, open(out_path, "w"), indent=1)
    print("wrote", out_path)

def _safe(spec, order):
    try:
        return run_table(spec, order)
    except Exception as e:
        return "SPEC_ERROR:" + type(e).__name__

# ---------- self-test: prove the engine + the check work before any LLM is involved ----------

# Disabled for now. Restore this block (and the --selftest flag below) to
# re-enable: it is what proves a "0 disagreements" result is meaningful.
#
# GOLD_FREE_SHIPPING = {   # hand translation of free_shipping: should NEVER disagree
#     "rows": [{"if": [{"field": "amount", "op": ">=", "value": 50}], "then": True}],
#     "else": False}
# BROKEN_FREE_SHIPPING = { # off-by-boundary (> instead of >=): MUST be caught
#     "rows": [{"if": [{"field": "amount", "op": ">", "value": 50}], "then": True}],
#     "else": False}
#
# def selftest():
#     from rules import free_shipping
#     inputs = all_inputs()
#     gold = sum(1 for _, o in inputs if free_shipping(o) != run_table(GOLD_FREE_SHIPPING, o))
#     broken = sum(1 for _, o in inputs if free_shipping(o) != run_table(BROKEN_FREE_SHIPPING, o))
#     print("hand translation disagreements (want 0):   ", gold)
#     print("broken translation disagreements (want >0):", broken)
#     assert gold == 0 and broken > 0
#     print("selftest ok: the engine is faithful and the check can catch a wrong spec")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--specs", help="directory of <rule>.json decision tables")
    p.add_argument("--out", default="results/results.json")
    # p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    # if a.selftest:
    #     selftest()
    # else:
    os.makedirs("results", exist_ok=True)
    check(a.specs, a.out)
