"""Tests for the StoresConfig / StoreBlock schema + per-kind merger.

Feature 033 T013.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from darnit.config.framework_schema import (
    FrameworkConfig,
    FrameworkMetadata,
    StoreBlock,
    StoresConfig,
)
from darnit.config.merger import merge_configs
from darnit.config.user_schema import UserConfig


def _fw(**stores_kwargs):
    return FrameworkConfig(
        metadata=FrameworkMetadata(
            name="t", display_name="T", version="0.0.1", spec_version="v0",
        ),
        stores=StoresConfig(**stores_kwargs),
    )


class TestExtraForbid:
    def test_unknown_store_kind_rejected(self):
        with pytest.raises(ValidationError) as exc:
            StoresConfig(audit_log={"backend": "postgres"})
        assert "audit_log" in str(exc.value)

    def test_typo_rejected(self):
        with pytest.raises(ValidationError):
            StoresConfig(projact={"backend": "postgres"})


class TestExtraAllow:
    def test_backend_specific_keys_pass_through(self):
        block = StoreBlock(backend="postgres", dsn="postgres://x", pool_size=5)
        extras = block.model_extra or {}
        assert extras.get("dsn") == "postgres://x"
        assert extras.get("pool_size") == 5

    def test_missing_backend_rejected(self):
        with pytest.raises(ValidationError):
            StoreBlock(dsn="x")


class TestVarSubstitution:
    def test_substitutes_str_extras(self, monkeypatch):
        monkeypatch.setenv("TEST_DSN", "postgres://real")
        sc = StoresConfig(attestation=StoreBlock(backend="postgres", dsn="$TEST_DSN"))
        assert sc.attestation.model_extra["dsn"] == "postgres://real"

    def test_substitutes_backend_field(self, monkeypatch):
        monkeypatch.setenv("STORE_KIND", "postgres")
        sc = StoresConfig(project=StoreBlock(backend="$STORE_KIND"))
        assert sc.project.backend == "postgres"

    def test_non_string_extras_pass_through(self):
        sc = StoresConfig(cache=StoreBlock(backend="fs", ttl=60, enabled=True))
        assert sc.cache.model_extra["ttl"] == 60
        assert sc.cache.model_extra["enabled"] is True

    def test_unset_var_substitutes_empty(self, monkeypatch):
        monkeypatch.delenv("UNSET_STORE_VAR", raising=False)
        sc = StoresConfig(project=StoreBlock(backend="fs", dsn="$UNSET_STORE_VAR"))
        assert sc.project.model_extra["dsn"] == ""


class TestPerKindMerger:
    def test_user_replaces_framework_for_same_kind(self):
        fw = _fw(project=StoreBlock(backend="fw-project"))
        usr = UserConfig(
            stores=StoresConfig(project=StoreBlock(backend="usr-project"))
        )
        eff = merge_configs(fw, usr)
        assert eff.stores.project.backend == "usr-project"

    def test_disjoint_kinds_coexist(self):
        fw = _fw(attestation=StoreBlock(backend="fw-att"))
        usr = UserConfig(
            stores=StoresConfig(project=StoreBlock(backend="usr-project"))
        )
        eff = merge_configs(fw, usr)
        assert eff.stores.project.backend == "usr-project"
        assert eff.stores.attestation.backend == "fw-att"

    def test_user_only(self):
        fw = _fw()
        usr = UserConfig(
            stores=StoresConfig(project=StoreBlock(backend="usr-project"))
        )
        eff = merge_configs(fw, usr)
        assert eff.stores.project.backend == "usr-project"
        assert eff.stores.attestation is None

    def test_framework_only(self):
        fw = _fw(project=StoreBlock(backend="fw-project"))
        eff = merge_configs(fw, None)
        assert eff.stores.project.backend == "fw-project"

    def test_neither_set(self):
        fw = _fw()
        eff = merge_configs(fw, None)
        for kind in ("project", "attestation", "report", "cache"):
            assert getattr(eff.stores, kind) is None
