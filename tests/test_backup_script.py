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


def _stub(bin_dir: Path, name: str, script: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / name
    stub.write_text(f"#!/bin/sh\n{script}", newline="\n")
    stub.chmod(0o755)


def _stub_pg_isready(bin_dir: Path, not_ready_times: int) -> None:
    # Reports "not ready" for the first N calls, then ready; every call is counted.
    calls = (bin_dir / "pg_isready.calls").as_posix()
    _stub(
        bin_dir,
        "pg_isready",
        f"n=$(cat '{calls}' 2>/dev/null || echo 0)\nn=$((n + 1))\necho $n > '{calls}'\n"
        f"[ $n -gt {not_ready_times} ]\n",
    )


def _isready_calls(tmp_path: Path) -> int:
    return int((tmp_path / "bin" / "pg_isready.calls").read_text())


def _run(tmp_path: Path, body: str, rc: int, not_ready_times: int = 0) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "pg_dump", f"printf '%s' '{body}'\nexit {rc}\n")
    _stub_pg_isready(bin_dir, not_ready_times)
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
        VITALS_BACKUP_DIR=(tmp_path / "backups").as_posix(),
        VITALS_GARMIN_SESSION_DIR=(tmp_path / "no_garmin").as_posix(),
        VITALS_BACKUP_ONCE="1",
        VITALS_BACKUP_DB_WAIT_ATTEMPTS="5",
        VITALS_BACKUP_DB_WAIT_POLL_SECONDS="0",
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


def test_the_dump_waits_for_a_database_that_is_still_starting(tmp_path):
    # Host reboot: the sidecar comes up before Postgres accepts connections.
    result = _run(tmp_path, GOOD_DUMP, 0, not_ready_times=3)

    assert result.returncode == 0, result.stderr
    assert _isready_calls(tmp_path) == 4
    assert len(_dumps(tmp_path)) == 1
    assert not _marker(tmp_path).exists()


def test_a_database_that_never_comes_up_fails_the_pass_instead_of_hanging(tmp_path):
    result = _run(tmp_path, "", 1, not_ready_times=100)

    assert result.returncode != 0
    assert _isready_calls(tmp_path) == 5
    assert "not ready after 5 attempts" in result.stderr
    assert _dumps(tmp_path) == []
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
    response = await client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["backup"] == "failed"


async def test_health_is_silent_about_backups_without_the_sidecar(client, redis, tmp_path, monkeypatch):
    await redis.set("scheduler:last_run:keepalive", str(int(time.time())))
    monkeypatch.setenv("VITALS_BACKUP_STATUS_DIR", str(tmp_path / "absent"))

    body = (await client.get("/health")).json()
    assert body["status"] == "ok"
    assert "backup" not in body
