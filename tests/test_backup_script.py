"""scripts/backup.sh run for real against a stubbed pg_dump.

The sidecar is plain /bin/sh without pipefail, so these drive the script through
``sh`` with a fake ``pg_dump`` first on PATH and check what lands in the backup
directory: a broken dump must never be promoted, the failure must leave the
marker /health reads, and rotation must keep the last good copy.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="needs a POSIX sh")

GOOD_DUMP = "-- PostgreSQL database dump\nCREATE TABLE t (id int);\n-- PostgreSQL database dump complete\n"


def _stub_pg_dump(bin_dir: Path, body: str, rc: int) -> None:
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "pg_dump"
    stub.write_text(f"#!/bin/sh\nprintf '%s' '{body}'\nexit {rc}\n", newline="\n")
    stub.chmod(0o755)


def _run(tmp_path: Path, body: str, rc: int) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    _stub_pg_dump(bin_dir, body, rc)
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
        VITALS_BACKUP_DIR=(tmp_path / "backups").as_posix(),
        VITALS_GARMIN_SESSION_DIR=(tmp_path / "no_garmin").as_posix(),
        VITALS_BACKUP_ONCE="1",
    )
    return subprocess.run([SH, SCRIPT.as_posix()], env=env, capture_output=True, text=True)


def _dumps(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "backups").glob("vitals_*.sql.gz"))


def _marker(tmp_path: Path) -> Path:
    return tmp_path / "backups" / "status" / "backup_failed"


def _leftovers(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "backups").iterdir() if p.name.endswith(".tmp")]


def test_a_good_dump_is_promoted_and_clears_the_marker(tmp_path):
    (tmp_path / "backups" / "status").mkdir(parents=True)
    _marker(tmp_path).write_text("old failure\n")

    result = _run(tmp_path, GOOD_DUMP, 0)

    assert result.returncode == 0, result.stderr
    assert len(_dumps(tmp_path)) == 1
    assert not _marker(tmp_path).exists()
    assert _leftovers(tmp_path) == []


def test_a_failing_pg_dump_is_never_promoted(tmp_path):
    # Partial output, then a non-zero exit: piped into gzip, this used to become a
    # tiny archive renamed into place as a normal backup.
    result = _run(tmp_path, "-- PostgreSQL database dump\n", 1)

    assert result.returncode != 0
    assert _dumps(tmp_path) == []
    assert _leftovers(tmp_path) == []
    assert "ERROR" in result.stderr
    assert _marker(tmp_path).exists()


def test_a_dump_without_the_completion_trailer_is_rejected(tmp_path):
    result = _run(tmp_path, "-- PostgreSQL database dump\nCREATE TABLE t (id int);\n", 0)

    assert result.returncode != 0
    assert _dumps(tmp_path) == []
    assert "incomplete" in result.stderr
    assert _marker(tmp_path).exists()


def test_rotation_keeps_the_newest_good_dump_through_a_failing_streak(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    month_ago = time.time() - 30 * 86400
    older = backups / "vitals_20260801_210000.sql.gz"
    newest = backups / "vitals_20260901_210000.sql.gz"
    for path in (older, newest):
        path.write_bytes(b"gz")
        os.utime(path, (month_ago, month_ago))

    result = _run(tmp_path, "", 1)

    assert result.returncode != 0
    # Both are past the 7-day window; only the last good one survives.
    assert _dumps(tmp_path) == [newest]


async def test_health_turns_red_while_the_last_backup_failed(client, redis, tmp_path, monkeypatch):
    await redis.set("scheduler:last_run:keepalive", str(int(time.time())))
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    monkeypatch.setenv("VITALS_BACKUP_STATUS_DIR", str(status_dir))

    body = (await client.get("/health")).json()
    assert body["status"] == "ok"
    assert body["backup"] == "ok"

    (status_dir / "backup_failed").write_text("20261008_210516 pg_dump exited with an error\n")
    body = (await client.get("/health")).json()
    assert body["status"] == "error"
    assert body["backup"] == "failed"


async def test_health_is_silent_about_backups_without_the_sidecar(client, redis, tmp_path, monkeypatch):
    await redis.set("scheduler:last_run:keepalive", str(int(time.time())))
    monkeypatch.setenv("VITALS_BACKUP_STATUS_DIR", str(tmp_path / "absent"))

    body = (await client.get("/health")).json()
    assert body["status"] == "ok"
    assert "backup" not in body
