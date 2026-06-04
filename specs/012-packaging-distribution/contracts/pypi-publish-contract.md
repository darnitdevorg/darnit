# Contract: PyPI Publishing

## Scope

Publishes sdist + wheel for each package listed in `packaging/pypi/public-packages.txt` to PyPI (stable tags) or TestPyPI (pre-release tags).

## Package set

The authoritative list lives in `packaging/pypi/public-packages.txt`. v1 contents:

```
darnit
darnit-baseline
darnit-gittuf
darnit-mcp
```

Any package not in this list MUST NOT be uploaded. A CI lint asserts that every package in this list exists in `packages/*/pyproject.toml`.

## Build

For each `<pkg>`:

```bash
uv build --package <pkg> --out-dir dist/<pkg>/
```

Produces:
- `dist/<pkg>/<dist_name>-<version>.tar.gz` (sdist)
- `dist/<pkg>/<dist_name>-<version>-py3-none-any.whl` (wheel)

Where `<dist_name>` is the normalized PEP 503 name.

## Publish

Uses `pypa/gh-action-pypi-publish` with Trusted Publishing (OIDC) — no API tokens.

```yaml
- uses: pypa/gh-action-pypi-publish@release/v1
  with:
    packages-dir: dist/<pkg>/
    repository-url: ${{ env.PYPI_INDEX_URL }}  # https://upload.pypi.org/legacy/ or TestPyPI
    attestations: true                          # PEP 740 attestations enabled
```

`PYPI_INDEX_URL` is set per Release `kind`:
- stable → `https://upload.pypi.org/legacy/`
- prerelease → `https://test.pypi.org/legacy/`

## Attestations

Sigstore bundle (`*.sigstore.json`) is generated and uploaded alongside each wheel and sdist. The signing identity is the release workflow's OIDC identity at the tagged commit.

## Smoke test

Per-package, in a clean container:

```bash
pip install --index-url $INDEX --pre $PKG==$VERSION
darnit --version  # for darnit-mcp; "$PKG --help" or import smoke for others
```

`pip install --verify-attestations $PKG==$VERSION` runs additionally for stable releases on `pypi.org`, where the attestation API is available.

## Pre-flight assertions (per package)

| Check | Fail behavior |
|---|---|
| `version` in `pyproject.toml` matches tag | Workflow stops in preflight, before any upload. |
| Package name matches a line in `public-packages.txt` | Job fails before upload. |
| sdist + wheel both built without warnings | Job fails (warnings are escalated). |

## Behavior on partial failure

If 3 of 4 packages upload successfully and the 4th fails, the 3 stay published. A `release-failure` issue names the failed package. Recovery is documented in `packaging/RECOVERY.md` under `pypi`.
