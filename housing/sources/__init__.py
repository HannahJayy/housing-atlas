"""Data source registry. Each module exposes INFO (shown on the Sources page) and run(ctx)."""

import importlib

SOURCE_ORDER = [
    "boundaries",   # Census cartographic boundaries + ZIP->county relationship
    "census_pep",   # population, migration, county->metro crosswalk
    "zillow",
    "realtor",
    "redfin",
    "census_acs",
    "census_bps",
    "bea",
    "bls",
    "fred",
    "fhfa",
    "fema_nri",
]


def get_module(name):
    return importlib.import_module("housing.sources." + name)


def all_info(cfg=None):
    out = []
    for name in SOURCE_ORDER:
        mod = get_module(name)
        info = dict(mod.INFO)
        if cfg is not None and hasattr(mod, "file_list"):
            try:
                info["files"] = mod.file_list(cfg)
            except Exception:
                info["files"] = []
        out.append(info)
    return out
