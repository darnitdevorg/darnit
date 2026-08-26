"""US3 T038: duplicate entry-point names raise StoreNameCollision.

Feature 033. Two packages registering the same backend name under the
same group is an operator-visible error at discovery time. Message
includes both package names so the operator can identify + uninstall
the conflict.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestUS3NameCollision:
    def test_duplicate_registration_raises(self, monkeypatch):
        from darnit.stores import discovery
        from darnit.stores.errors import StoreNameCollision

        class BackendA:
            pass

        class BackendB:
            pass

        def _fake_ep(name, cls, package):
            ep = MagicMock()
            ep.name = name
            ep.value = f"{cls.__module__}:{cls.__qualname__}"
            ep.load.return_value = cls
            dist = MagicMock()
            dist.metadata = {"Name": package}
            ep.dist = dist
            return ep

        eps = [
            _fake_ep("s3", BackendA, "pkg-alpha"),
            _fake_ep("s3", BackendB, "pkg-bravo"),
        ]
        monkeypatch.setattr(
            discovery.metadata,
            "entry_points",
            lambda group=None: eps,
        )
        discovery._reset_discovery_cache()

        with pytest.raises(StoreNameCollision) as exc:
            discovery.discover_stores("darnit.stores.attestation")

        assert exc.value.name == "s3"
        msg = str(exc.value)
        assert "pkg-alpha" in msg
        assert "pkg-bravo" in msg
