"""Feature 033 US3 fixture package.

Exists solely to verify the entry-point discovery mechanism against a
real installed distribution -- not for production use.
"""

from example_store_plugin.backend import ExampleAttestationStore

__all__ = ["ExampleAttestationStore"]
