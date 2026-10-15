"""Sigstore signing uses the sigstore >= 3 API, the only one darnit supports."""

from __future__ import annotations

import contextlib
import importlib
import json

import pytest

pytest.importorskip("sigstore")

from darnit_baseline.attestation import signing  # noqa: E402


class _Bundle:
    def to_json(self) -> str:
        return json.dumps({"signed": True})


class _Signer:
    def sign_dsse(self, statement):
        assert statement is not None
        return _Bundle()


def _stub_sigstore(monkeypatch, calls: list[str]) -> None:
    class SigningConfig:
        def get_oidc_url(self) -> str:
            return "https://oauth2.example/auth"

    class ClientTrustConfig:
        signing_config = SigningConfig()

        @classmethod
        def production(cls):
            calls.append("production")
            return cls()

        @classmethod
        def staging(cls):
            calls.append("staging")
            return cls()

    class SigningContext:
        @classmethod
        def from_trust_config(cls, trust_config):
            assert isinstance(trust_config, ClientTrustConfig)
            return cls()

        @contextlib.contextmanager
        def signer(self, token, cache=True):
            assert token == "token-for:https://oauth2.example/auth"
            yield _Signer()

    class Issuer:
        def __init__(self, url: str) -> None:
            self.url = url

        def identity_token(self) -> str:
            return f"token-for:{self.url}"

    monkeypatch.setattr(signing, "ClientTrustConfig", ClientTrustConfig)
    monkeypatch.setattr(signing, "SigningContext", SigningContext)
    monkeypatch.setattr(signing, "Issuer", Issuer)


def test_installed_sigstore_is_the_supported_api() -> None:
    assert signing.is_attestation_available()
    assert signing.get_sigstore_api_version() == 3


@pytest.mark.parametrize("use_staging, instance", [(False, "production"), (True, "staging")])
def test_sign_attestation_signs_through_the_trust_config(monkeypatch, use_staging, instance) -> None:
    calls: list[str] = []
    _stub_sigstore(monkeypatch, calls)

    bundle = signing.sign_attestation(
        predicate={"summary": {}},
        predicate_type="https://openssf.org/baseline/assessment/v1",
        subject_name="git+https://github.com/o/r",
        commit="abc123",
        use_staging=use_staging,
    )

    assert calls == [instance]
    assert bundle == {"signed": True}


def test_sigstore_without_the_supported_api_is_unavailable(monkeypatch) -> None:
    import sigstore.sign

    monkeypatch.delattr(sigstore.sign, "ClientTrustConfig")
    try:
        importlib.reload(signing)
        assert not signing.is_attestation_available()
        assert signing.get_sigstore_api_version() == 0
        with pytest.raises(RuntimeError, match="requires optional dependencies"):
            signing.sign_attestation({}, "t", "s", "c")
    finally:
        monkeypatch.undo()
        importlib.reload(signing)
    assert signing.is_attestation_available()
