"""Read and write individual keys in the project's .env file.

Deliberately simple: reads the file line-by-line, replaces matching
``KEY=value`` lines in-place, appends new keys at the end, and writes
the file back atomically (write to .env.tmp → rename). Comments and
blank lines are preserved verbatim.

Thread-safety: a module-level lock serialises concurrent writes.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

_LOCK = threading.Lock()

# Resolve .env relative to the repo root (two levels up from this file:
# web/services/ → web/ → repo root).
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"


def _find_env_path() -> Path:
    """Return the .env path.  Respects ``VITALS_ENV_FILE`` override (tests)."""
    override = os.getenv("VITALS_ENV_FILE")
    return Path(override) if override else _ENV_PATH


def read_key(key: str) -> str:
    """Return the value for *key* from the .env file, or an empty string if
    the key is absent or the file does not exist."""
    path = _find_env_path()
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        if k.strip() == key:
            return v.strip()
    return ""


def write_keys(updates: dict[str, str]) -> None:
    """Write *updates* (``{KEY: value}``) into the .env file.

    Existing keys are updated in-place; new keys are appended.  The write
    is atomic on POSIX (rename) and best-effort on Windows (overwrite).

    Rejects values containing ``\\n``/``\\r``: unescaped, they'd break out of
    their ``KEY=value`` line and let a saved field inject or overwrite an
    arbitrary env var (e.g. ``VITALS_SESSION_SECRET``) on the next write.
    """
    for key, value in updates.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"Value for {key!r} contains a newline character")

    path = _find_env_path()
    with _LOCK:
        # Read existing lines (tolerate missing file).
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            lines = []

        remaining = set(updates.keys())
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                k = k.strip()
                if k in remaining:
                    # Replace value, preserve trailing newline style.
                    nl = "\n" if not line.endswith("\r\n") else "\r\n"
                    new_lines.append(f"{k}={updates[k]}{nl}")
                    remaining.discard(k)
                    continue
            new_lines.append(line)

        # Append genuinely new keys.
        for key in remaining:
            new_lines.append(f"{key}={updates[key]}\n")

        content = "".join(new_lines)
        tmp = path.with_suffix(".env.tmp")
        tmp.write_text(content, encoding="utf-8")
        try:
            tmp.replace(path)  # atomic on POSIX; best-effort on Windows
        except OSError:
            # Fallback for Windows cross-device rename edge cases.
            path.write_text(content, encoding="utf-8")
            tmp.unlink(missing_ok=True)
