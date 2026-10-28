"""
Shared config loader for Parents' Healthcare scripts.
Every script imports get_config() instead of hardcoding paths.
Modeled on CoS cos_config_loader.py; reads phc-config.yaml at the repo root.
"""

import socket
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "phc-config.yaml"


def get_config(hostname: str | None = None) -> dict:
    """
    Return the merged config for the current (or given) host:
    defaults + host-specific overrides.
    """
    with open(CONFIG_PATH) as f:
        raw = yaml.safe_load(f)

    host = hostname or socket.gethostname().lower()

    if host not in raw:
        raise KeyError(
            f"No config section for host '{host}'. "
            f"Add one to {CONFIG_PATH.name} before running here."
        )

    merged = {**raw.get("defaults", {}), **raw[host]}
    merged["_hostname"] = host
    return merged


if __name__ == "__main__":
    # Quick sanity check: python phc_config_loader.py
    cfg = get_config()
    for k, v in cfg.items():
        print(f"{k}: {v}")
