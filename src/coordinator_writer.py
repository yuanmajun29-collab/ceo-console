from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _write_coordinator(key: str, value: str, reason: str) -> bool:
    """Best-effort write to Agent Coordinator state."""
    key_arg = shlex.quote(str(key))
    value_arg = shlex.quote(str(value))
    reason_arg = shlex.quote(str(reason))
    company_dir = shlex.quote(str(Path.home() / "company"))
    try:
        result = subprocess.run(
            [
                "bash",
                "-lc",
                f"cd {company_dir} && coordinator state set {key_arg} _ {value_arg} --tool ceo-console --reason {reason_arg}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if result.returncode != 0:
            logger.warning(
                "Coordinator state write failed for %s: %s",
                key,
                (result.stderr or result.stdout or "").strip(),
            )
            return False
        return True
    except Exception:
        logger.exception("Coordinator state write failed for %s", key)
        return False
