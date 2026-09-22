"""
DiffCheck: the legacy side.

12 order-handling rules written as ordinary Python functions, the way they
would exist in a legacy checkout system. Every rule CLASSIFIES an order:
it returns True/False or a short label. No rule computes a number.

The order record (any field can be None = missing):
    amount            order subtotal (float)
    item_count        number of items (int)
    country           "US","CA","GB","DE","IN","JP","BR"
    tier              "basic","plus","pro"
    account_age_days  days since signup (int)
    coupon            e.g. "SAVE10","SAVE20","FREESHIP","VIP", or None
    category          "electronics","books","apparel","grocery","furniture"
    weight_kg         shipment weight (float)
    is_return         True/False

Band A = 1-2 conditions, B = 3-5 conditions, C = nested / ordered / null-sensitive.
"""

# ---------------- band A ----------------

def free_shipping(o):
    """Free shipping at 50 or more."""
    return (o["amount"] or 0) >= 50

def domestic(o):
    """US and CA are domestic."""
    return o["country"] in ("US", "CA")

def heavy(o):
    """Heavy means strictly more than 20 kg."""
    return (o["weight_kg"] or 0) > 20

# coupon_kind was removed from the rule set. It classified a coupon by prefix
# ("SAVE10" and "SAVE20" both mean "save"), and prefix matching cannot be written
# with the nine operators the decision-table format allows, unless the prompt
# enumerates every coupon string the system will ever see. It was therefore not a
# test of translation fidelity: no correct answer existed. Its raw responses stay
# in specs/<model>/raw/ for anyone who wants to look at how each model coped.

# ---------------- band B ----------------

def return_eligible(o):
    """Returns allowed except: grocery, 30 kg or more, or account younger than 7 days."""
    if o["category"] == "grocery":
        return False
    if (o["weight_kg"] or 0) >= 30:
        return False
    if (o["account_age_days"] or 0) < 7:
        return False
    return True

def express_eligible(o):
    """Express needs: domestic, under 10 kg, and (pro tier or amount 200+)."""
    if o["country"] not in ("US", "CA"):
        return False
    if (o["weight_kg"] or 0) >= 10:
        return False
    return o["tier"] == "pro" or (o["amount"] or 0) >= 200

def tax_class(o):
    """books exempt; grocery reduced; electronics high in DE, standard elsewhere; all else standard."""
    cat = o["category"]
    if cat == "books":
        return "exempt"
    if cat == "grocery":
        return "reduced"
    if cat == "electronics" and o["country"] == "DE":
        return "high"
    return "standard"

def new_account_hold(o):
    """Hold if account younger than 30 days AND amount over 500."""
    return (o["account_age_days"] or 0) < 30 and (o["amount"] or 0) > 500

# ---------------- band C ----------------

def fraud_band(o):
    """Risk points: amount>1000 -> 2, age<14 -> 2, country outside US/CA/GB/DE -> 1, return -> 1.
    0-1 low, 2-3 medium, 4+ high."""
    s = 0
    if (o["amount"] or 0) > 1000:
        s += 2
    if (o["account_age_days"] or 0) < 14:
        s += 2
    if o["country"] not in ("US", "CA", "GB", "DE"):
        s += 1
    if o["is_return"]:
        s += 1
    if s <= 1:
        return "low"
    if s <= 3:
        return "medium"
    return "high"

def priority(o):
    """pro -> high; plus with amount>300 -> high; amount>1000 -> high; amount>=100 -> medium; else low.
    A return is never high: it drops to medium."""
    amt = o["amount"] or 0
    if o["tier"] == "pro":
        level = "high"
    elif o["tier"] == "plus" and amt > 300:
        level = "high"
    elif amt > 1000:
        level = "high"
    elif amt >= 100:
        level = "medium"
    else:
        level = "low"
    if o["is_return"] and level == "high":
        level = "medium"
    return level

def insurance_required(o):
    """Missing amount -> False. Then: amount>=750, or electronics with amount>=300,
    or international with amount>=200."""
    amt = o["amount"]
    if amt is None:
        return False
    if amt >= 750:
        return True
    if o["category"] == "electronics" and amt >= 300:
        return True
    if o["country"] not in ("US", "CA") and amt >= 200:
        return True
    return False

def order_status(o):
    """reject if fraud_band is high; review if new_account_hold; reject if a return that is
    not return_eligible; else accept. Checked in that order."""
    if fraud_band(o) == "high":
        return "reject"
    if new_account_hold(o):
        return "review"
    if o["is_return"] and not return_eligible(o):
        return "reject"
    return "accept"


RULES = [
    ("free_shipping", free_shipping, "A"),
    ("domestic", domestic, "A"),
    ("heavy", heavy, "A"),
    ("return_eligible", return_eligible, "B"),
    ("express_eligible", express_eligible, "B"),
    ("tax_class", tax_class, "B"),
    ("new_account_hold", new_account_hold, "B"),
    ("fraud_band", fraud_band, "C"),
    ("priority", priority, "C"),
    ("insurance_required", insurance_required, "C"),
    ("order_status", order_status, "C"),
]
