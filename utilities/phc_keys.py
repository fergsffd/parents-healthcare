"""
Secret loading for Parents' Healthcare scripts.
Modeled on CoS cos_secrets.py, but reads ~/.config/phc/ so PHC keys can be
rotated independently of CoS. (Named phc_keys, not phc_secrets, because
.gitignore blocks *secret*.)

One-time setup (per host):
    mkdir -p ~/.config/phc && chmod 700 ~/.config/phc
    nano ~/.config/phc/anthropic_key && chmod 600 ~/.config/phc/anthropic_key

Env var override (checked first): PHC_ANTHROPIC_KEY. Deliberately not
ANTHROPIC_API_KEY, which Claude Code itself reads to choose API billing.
"""

import os
import stat
import sys

SECRETS_DIR = os.path.expanduser("~/.config/phc")


def _check_permissions(path):
    """Warn (don't fail) if a secret file is more permissive than 600."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            print(f"WARNING: {path} has mode {oct(mode)}. Run: chmod 600 {path}",
                  file=sys.stderr)
    except OSError:
        pass


def get_secret(name, env_var=None):
    """Load a named secret: env_var first (if given), then ~/.config/phc/<name>."""
    if env_var:
        v = os.environ.get(env_var)
        if v:
            return v.strip()
    path = os.path.join(SECRETS_DIR, name)
    if os.path.exists(path):
        _check_permissions(path)
        with open(path) as f:
            v = f.read().strip()
        if v:
            return v
    sys.exit(f"ERROR: secret '{name}' not found. Create {path} (chmod 600)"
             + (f" or set {env_var}." if env_var else "."))


def get_anthropic_key():
    return get_secret("anthropic_key", "PHC_ANTHROPIC_KEY")
