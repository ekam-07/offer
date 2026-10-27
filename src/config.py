"""Loads the offer catalog and business rules from config/*.yaml."""
import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def _load(name):
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def default_customers_file():
    """Generated customers if they exist (python generate_data.py), else the hand-made samples."""
    generated = DATA_DIR / "customers.json"
    return generated if generated.exists() else DATA_DIR / "sample_customers.json"


def _rules_version():
    """Short hash of the rule and offer files, stored with every decision for reproducibility."""
    h = hashlib.sha256()
    for name in ("rules.yaml", "offers.yaml"):
        h.update((CONFIG_DIR / name).read_bytes())
    return h.hexdigest()[:12]


RULES_VERSION = _rules_version()
CATALOG = _load("offers.yaml")
RULES = _load("rules.yaml")
OFFERS = CATALOG["offers"]
