"""Configuration: defaults merged with data/config.json (editable from the UI)."""

import copy
import json
import os
import threading

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("HOUSING_ATLAS_DATA") or os.path.join(ROOT_DIR, "data")
WEB_DIR = os.path.join(ROOT_DIR, "web")

ALL_LEVELS = ["us", "state", "metro", "county", "zip"]

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 8765, "open_browser": True},
    # Some agencies (BLS) require a contact e-mail in the User-Agent of automated downloads.
    "contact_email": "",
    # Optional free keys. Without a Census key the app downloads the (larger) ACS summary files.
    "census_api_key": "",
    "bea_api_key": "",
    "bls_api_key": "",
    # Weekly automatic refresh while the server is running (weekday: 0=Mon ... 6=Sun).
    "schedule": {"enabled": True, "weekday": 6, "hour": 3},
    # Assumptions used by affordability / investing metrics. Editable in Settings.
    "affordability": {
        "down_payment_pct": 10.0,
        "loan_years": 30,
        "insurance_rate_pct": 0.5,
        "pmi_rate_pct": 0.0,
        "affordable_dti_pct": 30.0,
        "expense_ratio_pct": 40.0,
        "rate_override_pct": None,
        "default_property_tax_pct": 1.0,
    },
    "sources": {
        "boundaries": {"enabled": True, "zip_shapes": True},
        "census_pep": {"enabled": True},
        "zillow": {"enabled": True, "levels": ALL_LEVELS, "extended": True},
        "realtor": {"enabled": True, "levels": ALL_LEVELS, "hotness": True},
        "redfin": {"enabled": True, "levels": ALL_LEVELS, "weekly": True},
        "census_acs": {"enabled": True, "mode": "auto", "year": None},
        "census_bps": {"enabled": True, "history_years": 15},
        "bea": {"enabled": True},
        "bls": {"enabled": True, "county_history": False},
        "fred": {"enabled": True},
        "fhfa": {"enabled": True},
        "fema_nri": {"enabled": False},
    },
    # Override any download URL by its key (see Sources page). Useful when a provider moves a file.
    "url_overrides": {},
    # Advanced/testing: list of [prefix, replacement] applied to every URL before downloading.
    "url_rewrite": [],
    "download": {"timeout": 120, "retries": 3, "keep_raw_files": True},
}

_lock = threading.Lock()


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config_path():
    return os.path.join(DATA_DIR, "config.json")


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    user = {}
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
        except Exception:
            user = {}
    cfg = _merge(DEFAULTS, user)
    for env, key in ENV_OVERRIDES:
        if os.environ.get(env, "").strip():
            cfg[key] = os.environ[env].strip()
    return cfg


# Settings that can come from environment variables (used by the GitHub publishing workflow, where they are
# stored as repository secrets/variables). They are never written back to config.json.
ENV_OVERRIDES = (("HOUSING_ATLAS_CONTACT_EMAIL", "contact_email"), ("HOUSING_ATLAS_CENSUS_API_KEY", "census_api_key"),
                 ("HOUSING_ATLAS_BEA_API_KEY", "bea_api_key"), ("HOUSING_ATLAS_BLS_API_KEY", "bls_api_key"))


def save_config(cfg):
    """Persist only the values that differ from defaults (keeps the file readable)."""
    def diff(base, cur):
        out = {}
        for k, v in cur.items():
            if k not in base:
                out[k] = v
            elif isinstance(v, dict) and isinstance(base[k], dict):
                d = diff(base[k], v)
                if d:
                    out[k] = d
            elif v != base[k]:
                out[k] = v
        return out

    out = diff(DEFAULTS, cfg)
    for env, key in ENV_OVERRIDES:
        if os.environ.get(env, "").strip():
            out.pop(key, None)
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, config_path())


def update_config(patch):
    cfg = load_config()
    cfg = _merge(cfg, patch)
    save_config(cfg)
    return cfg
