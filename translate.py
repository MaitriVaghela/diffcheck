"""
Ask an LLM to migrate each legacy rule to a decision table.

One frozen prompt (below). The model sees the decision-table format and ONE
rule's Python source (plus helper rules it calls), and must answer with only
the JSON table. Raw responses are saved to specs/<model>/raw/ so every table
is auditable.

The OpenAI API key is read from the gitignored .env file in the current
directory:

  OPENAI_API_KEY=sk-...

Run from the project root:

  python3 translate.py gpt-4o-mini
"""
import inspect, json, os, sys, urllib.request

import rules
from rules import RULES

# Rules that call other rules: the helper source is inlined into the prompt,
# because a decision table cannot make function calls.
HELPERS = {"order_status": ["fraud_band", "new_account_hold", "return_eligible"]}

FORMAT_DOC = """A decision table is a JSON object:
{
  "rows": [
    {"if": [ {"field": "<name>", "op": "<op>", "value": <v>}, ... ],
     "then": <true | false | "label">},
    ...
  ],
  "else": <result when no row matches>
}
Rules of the format:
- Conditions in one row are ANDed. The FIRST row whose conditions all hold wins.
- Allowed ops: ==  !=  >  >=  <  <=  in  is_null  not_null
- "in" takes a list as value. "is_null"/"not_null" take no value.
- Ordered comparisons (>, >=, <, <=) on a missing (null) field DO NOT hold.
- "then"/"else" must be literals (true/false or a string label). No expressions.
"""


# ---------- credentials ----------

def get_key(env_name):
    """Read one API key from the gitignored .env file in the current directory.
    .env lines look like:  OPENAI_API_KEY=sk-...   (quotes optional)
    """
    key = None
    if os.path.exists(".env"):
        for line in open(".env"):
            name, sep, value = line.partition("=")
            if sep and name.strip() == env_name:
                key = value.strip().strip("\"'")
    if not key:
        raise SystemExit(f"No API key: put {env_name}=... in .env (gitignored)")
    return key


# ---------- the prompt ----------

PROMPT = """You are migrating business rules from a legacy Python system to a declarative decision-table engine.

Translate the Python function `{name}` into ONE decision table that returns exactly the same
value as the function for every possible order record, including records with null fields.
Helper functions are shown so you can inline their logic; the table has no function calls.

The order record fields: amount, item_count, country, tier, account_age_days, coupon, category, weight_kg, is_return. Any field can be null.

{format_doc}
Legacy Python:
```python
{src}```

Answer with ONLY the JSON decision table."""


def build_prompt(name):
    """The frozen prompt for one rule: format doc + that rule's Python source."""
    # Helper rules first, then the rule itself, so the model sees every
    # definition it needs before the function that calls them.

    # examplnames = [] + ["free_shipping"]   →   ["free_shipping"]
    names = HELPERS.get(name, []) + [name]
    
    # example: src = 'def free_shipping(o):\n    """Free shipping at 50 or more."""\n    return (o["amount"] or 0) >= 50\n'
    src = "\n".join(inspect.getsource(getattr(rules, n)) for n in names)
    return PROMPT.format(name=name, format_doc=FORMAT_DOC, src=src)


# ---------- the model call (temperature 0 so a rerun reproduces) ----------

def post_json(url, payload, headers):
    """POST a JSON body and return the decoded JSON response."""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def call_openai(prompt, model):
    data = post_json(
        "https://api.openai.com/v1/chat/completions",
        {"model": model, "temperature": 0,
         "messages": [{"role": "user", "content": prompt}]},
        {"authorization": "Bearer " + get_key("OPENAI_API_KEY")})
    return data["choices"][0]["message"]["content"]


# ---------- response parsing ----------

def extract_spec(text):
    """Pull the decision table out of a raw model response.

    Models wrap the JSON in a ```json fence, add a sentence of preamble, append
    a note afterwards, or emit several blocks while thinking aloud. So scan for
    the first position that decodes as a complete JSON object and take that one.
    That is the direct answer to "answer with ONLY the JSON decision table".
    A first-brace-to-last-brace slice would span every block at once and fail.

    Raises ValueError if no complete JSON object is present.
    """
    decoder = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            return decoder.raw_decode(text, i)[0]
        except ValueError:
            i = text.find("{", i + 1)
    raise ValueError("no complete JSON object in response")


# ---------- main ----------

def write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


def translate_rule(name, model, spec_dir):
    """Ask the model to translate one rule and return the parsed decision table.

    Raises ValueError if the reply is not valid JSON.
    """
    text = call_openai(build_prompt(name), model)
    # Save the raw reply first, so even an unparseable one stays auditable.
    write_text(os.path.join(spec_dir, "raw", name + ".txt"), text)
    return extract_spec(text)


def main():
    # The one thing this script needs: which model to ask.
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 translate.py <model>   (e.g. gpt-4o-mini)")
    model = sys.argv[1]

    # One directory per model, e.g. specs/gpt-4o-mini/. Slashes in names like
    # "meta/llama-3" would otherwise create nested directories.
    spec_dir = os.path.join("specs", model.replace("/", "_"))
    # Creating raw/ creates specs/<model>/ too; exist_ok makes a rerun safe.
    os.makedirs(os.path.join(spec_dir, "raw"), exist_ok=True)

    # One API call per rule, in the order rules.py declares them.
    for name, _fn, _band in RULES:     # build_prompt looks the function up by name
        try:
            # Calls the model, saves the raw reply, returns the parsed table.
            spec = translate_rule(name, model, spec_dir)
        except ValueError as e:
            # The model answered with something that isn't JSON. Skip this rule
            # and keep going: the other 11 are still worth collecting. A network
            # error is NOT caught here, so a dropped connection stops the run.
            print(name, "PARSE ERROR", e)
            continue
        # The file checker.py will read: specs/<model>/<rule>.json
        write_text(os.path.join(spec_dir, name + ".json"), json.dumps(spec, indent=1))
        print(name, "ok")


if __name__ == "__main__":
    main()
