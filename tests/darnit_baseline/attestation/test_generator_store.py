"""Feature 033 T027 / T029: AttestationStore-backed write path."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


class TestAttestationStoreWritePath:
    def test_store_receives_bundle(self, tmp_path: Path):
        from darnit_testchecks.stores import InMemoryAttestationStore

        from darnit_baseline.attestation.generator import (
            generate_attestation_from_results,
        )

        store = InMemoryAttestationStore()

        audit_result = MagicMock()
        audit_result.commit = "deadbeef"
        audit_result.owner = "acme"
        audit_result.repo = "widget"
        audit_result.ref = "main"
        audit_result.level = 1
        audit_result.all_results = []
        audit_result.project_config = None
        audit_result.local_path = str(tmp_path)

        result = generate_attestation_from_results(
            audit_result=audit_result,
            sign=False,
            attestation_store=store,
        )

        assert len(store._state) == 1
        bundle_id, bundle_bytes, content_type = store._state[0]
        assert bundle_id == "widget-baseline-attestation"
        assert content_type == "application/vnd.in-toto+json"
        assert b'"predicateType"' in bundle_bytes
        # No file created on disk when the store is used.
        assert list(tmp_path.iterdir()) == []
        # Function still returns the payload JSON string.
        assert '"predicateType"' in result

    def test_store_sigstore_content_type_when_signed(self, tmp_path: Path):
        """Signed bundle uses the Sigstore content-type."""
        from darnit_baseline.attestation.generator import ATTESTATION_AVAILABLE
        if not ATTESTATION_AVAILABLE:
            import pytest
            pytest.skip("Signing deps not installed")

        # We only care about the write-side branch, not the signing;
        # test via monkeypatch to skip actual signing.
        from darnit_testchecks.stores import InMemoryAttestationStore

        import darnit_baseline.attestation.generator as gen

        store = InMemoryAttestationStore()
        audit_result = MagicMock()
        audit_result.commit = "abc"
        audit_result.owner = "o"
        audit_result.repo = "r"
        audit_result.ref = "main"
        audit_result.level = 1
        audit_result.all_results = []
        audit_result.project_config = None
        audit_result.local_path = str(tmp_path)

        # Stub the signer to avoid Sigstore network I/O.
        gen.sign_attestation = lambda **kw: {"stubbed": True}  # type: ignore[assignment]
        try:
            gen.generate_attestation_from_results(
                audit_result=audit_result,
                sign=True,
                attestation_store=store,
            )
        finally:
            # Reload the real symbol from signing module to avoid leaking.
            from darnit_baseline.attestation import signing as _signing
            gen.sign_attestation = _signing.sign_attestation  # type: ignore[assignment]

        assert store._state
        _, _, content_type = store._state[0]
        assert content_type == "application/vnd.dev.sigstore.bundle+json"
