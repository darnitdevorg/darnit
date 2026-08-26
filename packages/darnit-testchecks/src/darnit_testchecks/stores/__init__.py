"""In-memory reference store backends for testing.

Feature 033 T020. These backends are shipped by darnit-testchecks so
they are only available in dev/test environments (they are NOT a
runtime dependency of darnit-core). They exist to:

* Prove the pluggable-stores machinery works end-to-end (US1 equivalence
  test) without needing a real filesystem-free storage backend.
* Give internal + external tests a zero-dependency, easily-inspectable
  reference implementation to seed and assert against.

Each backend exposes a ``_state`` attribute tests can read for
assertions.
"""

from darnit_testchecks.stores.in_memory_attestation import InMemoryAttestationStore
from darnit_testchecks.stores.in_memory_cache import InMemoryAuditCacheStore
from darnit_testchecks.stores.in_memory_project import InMemoryProjectStateStore
from darnit_testchecks.stores.in_memory_report import InMemoryReportStore

__all__ = [
    "InMemoryAttestationStore",
    "InMemoryAuditCacheStore",
    "InMemoryProjectStateStore",
    "InMemoryReportStore",
]
