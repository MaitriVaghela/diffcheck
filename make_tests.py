"""
Build tests.json: 5 golden test cases per rule, the way a migration team does it:
hand-picked inputs, expected value taken from the LEGACY rule (the legacy system
is the oracle). Frozen BEFORE any translation exists; never edited after.
"""
import json
from rules import RULES

BASE = {"amount": 120.0, "item_count": 3, "country": "US", "tier": "basic",
        "account_age_days": 400, "coupon": None, "category": "apparel",
        "weight_kg": 2.5, "is_return": False}

def v(**kw):
    d = dict(BASE); d.update(kw); return d

CASES = {
 "free_shipping":     [v(amount=20), v(amount=50), v(amount=80), v(amount=49.99), v(amount=500)],
 "domestic":          [v(country="US"), v(country="CA"), v(country="GB"), v(country="IN"), v(country="DE")],
 "heavy":             [v(weight_kg=2), v(weight_kg=25), v(weight_kg=20), v(weight_kg=20.5), v(weight_kg=0)],
 "return_eligible":   [v(), v(category="grocery"), v(weight_kg=35), v(account_age_days=3), v(category="books", weight_kg=29)],
 "express_eligible":  [v(tier="pro"), v(country="GB", tier="pro"), v(amount=250), v(amount=150, tier="basic"), v(weight_kg=12, tier="pro")],
 "tax_class":         [v(category="books"), v(category="grocery"), v(category="electronics", country="DE"), v(category="electronics", country="US"), v(category="furniture")],
 "new_account_hold":  [v(account_age_days=5, amount=600), v(account_age_days=5, amount=400), v(account_age_days=100, amount=900), v(account_age_days=29, amount=501), v(account_age_days=30, amount=800)],
 "fraud_band":        [v(), v(amount=1500), v(account_age_days=3, amount=1500), v(country="BR", is_return=True), v(amount=2000, account_age_days=1, country="IN", is_return=True)],
 "priority":          [v(tier="pro"), v(tier="plus", amount=400), v(tier="basic", amount=1200), v(tier="basic", amount=150), v(tier="pro", is_return=True)],
 "insurance_required":[v(amount=800), v(amount=400, category="electronics"), v(amount=250, country="GB"), v(amount=100), v(amount=None)],
 "order_status":      [v(), v(amount=2000, account_age_days=1, country="IN"), v(account_age_days=5, amount=900), v(is_return=True, category="grocery"), v(is_return=True)],
}

out = {}
for name, fn, band in RULES:
    assert len(CASES[name]) == 5, name
    out[name] = [{"input": c, "expected": fn(c)} for c in CASES[name]]
json.dump(out, open("tests.json", "w"), indent=1)
print("tests.json:", sum(len(x) for x in out.values()), "cases")
