# Contributing to widget

## How to contribute

1. Open an issue describing the change you propose.
2. Fork the repository and create a branch from `main`.
3. Make the change, with tests.
4. Open a pull request against `main`. A maintainer reviews every pull
   request; at least one approval from a maintainer other than the author is
   required before merging.

## Requirements for acceptable contributions

- Every change that alters behavior adds or updates tests in `tests/`, and
  the full test suite passes in CI.
- Every commit carries a `Signed-off-by` line (Developer Certificate of
  Origin); use `git commit -s`.
- Code follows the existing style; run `python -m ruff check .` before
  pushing.

## Running the tests

    python -m pip install -e ".[test]"
    python -m pytest
