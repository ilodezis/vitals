# Contributing to Vitals

Thank you for your interest! Vitals is a personal project open-sourced for the community. Contributions are welcome in the form of bug reports, documentation improvements, and pull requests.

## How to Report a Bug

1. Search [existing issues](https://github.com/ilodezis/vitals/issues) first — it may already be reported.
2. Open a new issue using the **Bug Report** template.
3. Include: Python version, Docker version, OS, the exact steps to reproduce, and what you expected vs. what happened.

> [!CAUTION]
> **Never include real health data, API keys, or passwords in bug reports.** Sanitize all examples.

## How to Request a Feature

Open an issue using the **Feature Request** template. Describe the use case, not just the implementation idea.

## Pull Requests

1. **Fork** the repository and create a branch from `master` (`git checkout -b fix/your-fix`).
2. **Write tests** — all PRs must include tests for the changed behavior. Run `python -m pytest -q` before submitting.
3. **One concern per PR** — keep changes focused. A PR that fixes a bug + adds a feature is harder to review.
4. **Follow the existing style** — the project uses `ruff` for linting. Run `ruff check .` before submitting.
5. Open the PR against `master` with a clear description of *what* changed and *why*.

> [!NOTE]
> **Touching the interface?** It is a React app in `frontend/`. Run
> `npm --prefix frontend run check` (type check, tests, build, size budget) before
> submitting; the build output in `web/static/app` is not committed. See
> [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).
>
> **Bumping a dependency?** `docs/known-good-deps.txt` is a snapshot of what the
> author's production container actually runs — a reference point to diff against
> when something looks off after an upgrade. `garminconnect` and `fastmcp` are
> pinned exactly, and must stay pinned: the Docker image resolves requirements on
> every rebuild, so an open range lets an unattended deploy swap the login or MCP
> machinery underneath a working install.

## Development Setup

```bash
git clone https://github.com/ilodezis/vitals.git
cd vitals
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
pip install -r requirements-dev.txt
python run_local.py         # SQLite + FakeRedis, no Docker needed
```

Default login for local dev: `timur` / `password`.

## Running Tests

```bash
# Unit tests (SQLite, instant)
python -m pytest -q

# Integration tests (requires Docker)
bash scripts/test_postgres.sh
```

Run `git config core.hooksPath .githooks` once per clone to enable the pre-push
hook that runs the unit suite and blocks a push when it is red.

`scripts/test_postgres.sh` is only a convenience wrapper: the test suite reads
`VITALS_TEST_DATABASE_URL` and switches to Postgres whenever it points at one.
If Docker isn't available, any local Postgres 15 works — install it natively,
create an empty database, and run:

```bash
export VITALS_TEST_DATABASE_URL="postgresql+asyncpg://postgres:<pass>@127.0.0.1:5432/vitals_test"
python -m pytest -m integration -q
```

Without that variable the `integration` tests are skipped, not failed — they
cover the things SQLite only pretends to support (JSONB containment, GIN,
partial-unique indexes, `func.date` semantics).

## Code of Conduct

Be respectful. This is a one-person project — patience is appreciated.
