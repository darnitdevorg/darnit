"""Unit tests for Sigstore attestation signing (darnit_baseline.attestation.signing)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sigstore")

import darnit_baseline.attestation.signing as signing_mod
from darnit_baseline.attestation.signing import sign_attestation


@pytest.mark.unit
class TestSignAttestationMissingDeps:
    """Tests for error handling when optional dependencies are absent."""

    def test_raises_runtime_error_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(signing_mod, "ATTESTATION_AVAILABLE", False)

        with pytest.raises(RuntimeError, match="darnit-core\\[attestation\\]"):
            sign_attestation(
                predicate={"foo": "bar"},
                predicate_type="https://example.com/predicate/v1",
                subject_name="git+https://github.com/test/repo",
                commit="0123456789abcdef0123456789abcdef01234567",
            )


@pytest.mark.unit
class TestSignAttestationV3:
    """Tests for Sigstore signing via the v3 API (sigstore >= 3.0 / 4.x)."""

    def test_sign_attestation_v3_production(self) -> None:
        mock_bundle = MagicMock()
        mock_bundle.to_json.return_value = json.dumps({"mediaType": "bundle/v3", "verificationMaterial": {}})

        mock_signer = MagicMock()
        mock_signer.sign_dsse.return_value = mock_bundle
        mock_signer_ctx = MagicMock()
        mock_signer_ctx.__enter__.return_value = mock_signer
        mock_signer_ctx.__exit__.return_value = None

        mock_signing_ctx = MagicMock()
        mock_signing_ctx.signer.return_value = mock_signer_ctx

        mock_trust_config = MagicMock()
        mock_trust_config.signing_config.get_oidc_url.return_value = "https://oauth2.sigstore.dev/auth"

        mock_issuer = MagicMock()
        mock_issuer.identity_token.return_value = "fake-oidc-token-v3"

        mock_builder = MagicMock()
        mock_stmt = MagicMock()
        mock_builder.return_value.build.return_value = mock_stmt

        with (
            patch.object(signing_mod, "ClientTrustConfig") as mock_ctc,
            patch.object(signing_mod, "SigningContext") as mock_sc,
            patch.object(signing_mod, "Issuer", return_value=mock_issuer),
            patch.object(signing_mod, "StatementBuilder", mock_builder),
            patch.object(signing_mod, "Subject"),
            patch.object(signing_mod, "DigestSet"),
        ):
            mock_ctc.production.return_value = mock_trust_config
            mock_sc.from_trust_config.return_value = mock_signing_ctx

            res = sign_attestation(
                predicate={"decision": "PASS"},
                predicate_type="https://darnit.dev/predicate/v1",
                subject_name="git+https://github.com/owner/repo",
                commit="11223344556677889900aabbccddeeff11223344",
                use_staging=False,
            )

            mock_ctc.production.assert_called_once()
            mock_sc.from_trust_config.assert_called_once_with(mock_trust_config)
            mock_signing_ctx.signer.assert_called_once_with("fake-oidc-token-v3", cache=True)
            mock_signer.sign_dsse.assert_called_once_with(mock_stmt)
            assert res == {"mediaType": "bundle/v3", "verificationMaterial": {}}

    def test_sign_attestation_v3_staging(self) -> None:
        mock_bundle = MagicMock()
        mock_bundle.to_json.return_value = json.dumps({"mediaType": "bundle/v3-staging"})

        mock_signer = MagicMock()
        mock_signer.sign_dsse.return_value = mock_bundle
        mock_signer_ctx = MagicMock()
        mock_signer_ctx.__enter__.return_value = mock_signer
        mock_signer_ctx.__exit__.return_value = None

        mock_signing_ctx = MagicMock()
        mock_signing_ctx.signer.return_value = mock_signer_ctx

        mock_trust_config = MagicMock()
        mock_trust_config.signing_config.get_oidc_url.return_value = "https://oauth2.staging.sigstore.dev/auth"

        mock_issuer = MagicMock()
        mock_issuer.identity_token.return_value = "fake-staging-token"

        with (
            patch.object(signing_mod, "ClientTrustConfig") as mock_ctc,
            patch.object(signing_mod, "SigningContext") as mock_sc,
            patch.object(signing_mod, "Issuer", return_value=mock_issuer),
            patch.object(signing_mod, "StatementBuilder"),
            patch.object(signing_mod, "Subject"),
            patch.object(signing_mod, "DigestSet"),
        ):
            mock_ctc.staging.return_value = mock_trust_config
            mock_sc.from_trust_config.return_value = mock_signing_ctx

            res = sign_attestation(
                predicate={"decision": "PASS"},
                predicate_type="https://darnit.dev/predicate/v1",
                subject_name="git+https://github.com/owner/repo",
                commit="11223344556677889900aabbccddeeff11223344",
                use_staging=True,
            )

            mock_ctc.staging.assert_called_once()
            assert res == {"mediaType": "bundle/v3-staging"}


@pytest.mark.unit
class TestSignAttestationStatementBuilding:
    """Tests for Subject and StatementBuilder parameter construction."""

    def test_subject_and_builder_parameters(self) -> None:
        captured_subject_args: dict = {}
        captured_builder_args: dict = {}

        def fake_subject(**kwargs):
            captured_subject_args.update(kwargs)
            return MagicMock()

        def fake_builder(**kwargs):
            captured_builder_args.update(kwargs)
            b = MagicMock()
            b.build.return_value = MagicMock()
            return b

        mock_bundle = MagicMock()
        mock_bundle.to_json.return_value = "{}"
        mock_signer = MagicMock()
        mock_signer.sign_dsse.return_value = mock_bundle
        mock_signer_ctx = MagicMock()
        mock_signer_ctx.__enter__.return_value = mock_signer

        mock_signing_ctx = MagicMock()
        mock_signing_ctx.signer.return_value = mock_signer_ctx

        mock_trust_config = MagicMock()
        mock_trust_config.signing_config.get_oidc_url.return_value = "https://oauth2.sigstore.dev"

        commit_sha = "abcdef0123456789abcdef0123456789abcdef01"
        expected_digest = signing_mod.hashlib.sha256(commit_sha.encode()).hexdigest()

        with (
            patch.object(signing_mod, "Subject", side_effect=fake_subject),
            patch.object(signing_mod, "StatementBuilder", side_effect=fake_builder),
            patch.object(signing_mod, "ClientTrustConfig") as mock_ctc,
            patch.object(signing_mod, "SigningContext") as mock_sc,
            patch.object(signing_mod, "Issuer"),
        ):
            mock_ctc.production.return_value = mock_trust_config
            mock_sc.from_trust_config.return_value = mock_signing_ctx

            sign_attestation(
                predicate={"level": 2},
                predicate_type="https://example.org/pred/v1",
                subject_name="git+https://github.com/foo/bar",
                commit=commit_sha,
            )

            assert captured_subject_args["name"] == f"git+https://github.com/foo/bar@{commit_sha}"
            assert captured_subject_args["digest"].root["sha256"] == expected_digest
            assert captured_builder_args["predicate_type"] == "https://example.org/pred/v1"
            assert captured_builder_args["predicate"] == {"level": 2}
            assert len(captured_builder_args["subjects"]) == 1
