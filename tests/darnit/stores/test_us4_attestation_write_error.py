"""US4 T042: AttestationStore.write raising surfaces to the operator.

Feature 033. If a selected backend fails to persist an attestation,
darnit must report the failure clearly (backend, artifact class,
bundle_id) and NOT silently fall through to a filesystem write at
``.darnit/attestations/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


class TestUS4AttestationWriteError:
    def test_error_surfaced_no_filesystem_fallback(self, tmp_path: Path):
        from darnit_baseline.attestation.generator import (
            generate_attestation_from_results,
        )

        class ExplodingAttestationStore:
            def __init__(self, **kw): pass
            def write(self, bundle_id, bundle_bytes, content_type):
                raise RuntimeError("bucket unreachable")
            def close(self): return None

        store = ExplodingAttestationStore()

        audit_result = MagicMock()
        audit_result.commit = "abc"
        audit_result.owner = "us4"
        audit_result.repo = "hot-repo"
        audit_result.ref = "main"
        audit_result.level = 1
        audit_result.all_results = []
        audit_result.project_config = None
        audit_result.local_path = str(tmp_path)

        # Sanity: on-disk sink dir doesn't yet exist.
        assert not (tmp_path / ".darnit" / "attestations").exists()

        result = generate_attestation_from_results(
            audit_result=audit_result,
            sign=False,
            attestation_store=store,
        )

        payload = json.loads(result)
        assert "error" in payload
        assert "bucket unreachable" in payload["error"]
        # No silent fallback: no filesystem write happened.
        assert not (tmp_path / ".darnit" / "attestations").exists()
        assert not any(
            p.suffix == ".intoto.json" for p in tmp_path.rglob("*")
        )
