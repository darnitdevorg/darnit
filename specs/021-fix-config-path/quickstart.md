# Quickstart: Verifying the wheel-install config path fix

**Feature**: 021-fix-config-path
**Audience**: Maintainer running the fix locally to reproduce the bug and confirm the fix.

## Reproduce the bug (before-fix baseline)

From the repo root on `main` (or any commit before this feature lands):

```bash
# Build the darnit-baseline wheel
uv build --package darnit-baseline

# Create a fresh, isolated environment (no editable link)
python -m venv /tmp/darnit-wheel-repro
source /tmp/darnit-wheel-repro/bin/activate

# Install the wheel plus its runtime deps
pip install packages/darnit-baseline/dist/darnit_baseline-*.whl

# Try to load the framework config
python -c "
from darnit_baseline import get_framework_path
p = get_framework_path()
print('resolved:', p)
print('exists:', p.exists() if p else 'no path returned')
"
```

Expected (before fix): `exists: False`, or `FileNotFoundError` when a downstream caller tries to read the file. This proves the bug.

## Verify the fix

After feature 021 lands, repeat the same steps in a fresh venv. Expected:

```
resolved: /tmp/darnit-wheel-repro/lib/python3.12/site-packages/darnit_baseline/openssf-baseline.toml
exists: True
```

Then run `darnit list` in the same venv. Expected: `openssf-baseline` prints with a control count and no "error loading" text.

## Repeat for other implementations

```bash
# darnit-gittuf
uv build --package darnit-gittuf
pip install packages/darnit-gittuf/dist/darnit_gittuf-*.whl
python -c "from darnit_gittuf import get_framework_path; p = get_framework_path(); print(p, p.exists())"

# darnit-reproducibility
uv build --package darnit-reproducibility
pip install packages/darnit-reproducibility/dist/darnit_reproducibility-*.whl
python -c "from darnit_reproducibility import get_framework_path; p = get_framework_path(); print(p, p.exists())"
```

All three MUST report an existing path.

## Editable-install regression check

The fix must not regress the editable-install path. From the repo root:

```bash
uv sync
uv run python -c "
from darnit_baseline import get_framework_path
p = get_framework_path()
print('resolved:', p)
print('exists:', p.exists())
"
```

Expected (both before and after fix): `exists: True`. The path resolves to the file inside the installed package tree, which for editable installs is the source-tree location.

## CI coverage

The integration test added by this feature (final location decided in `/speckit-tasks`) runs the wheel-build + install cycle automatically. It MUST be part of the CI test matrix for every PR touching implementation packages.

## Cleanup

```bash
deactivate
rm -rf /tmp/darnit-wheel-repro
```
