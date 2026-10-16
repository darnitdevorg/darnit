# Vulture allowlist — false positives and intentional unused code
#
# These entries suppress vulture warnings for code that appears unused but is
# intentionally kept. Vulture allowlists use attribute access to mark names used.

# MCP tool parameter kept on the public schema. Vulture allowlists use
# attribute access to mark a name used.
_ = attest  # noqa: F821  # audit_openssf_baseline parameter
