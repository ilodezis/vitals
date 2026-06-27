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

## Code of Conduct

Be respectful. This is a one-person project — patience is appreciated.
