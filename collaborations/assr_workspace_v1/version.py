# This file is auto-updated by the CI build workflow.
# Do not edit manually — the value is injected at build time.
# When running from source (unfrozen), the latest git tag is used as a fallback.

import os
import subprocess
import sys

_INJECTED = "build-0"   # CI replaces this line with the real build tag


def _git_tag() -> str | None:
    """Return the latest reachable git tag, or None if unavailable."""
    if getattr(sys, 'frozen', False):
        return None   # bundled binary — trust the injected value
    try:
        tag = subprocess.check_output(
            ['git', 'describe', '--tags', '--abbrev=0'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode().strip()
        return tag or None
    except Exception:
        return None


# In CI builds _INJECTED is the real build tag; in dev runs fall back to git.
CURRENT_VERSION: str = (_git_tag() if _INJECTED == "build-0" else None) or _INJECTED
