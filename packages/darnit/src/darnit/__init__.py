"""darnit - Generic compliance audit framework with plugin architecture.

This framework provides the core infrastructure for running compliance audits
against various standards. Implementations register via Python entry points.

Usage:
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    if impl:
        controls = impl.get_all_controls()
"""

__version__ = "0.1.0"
