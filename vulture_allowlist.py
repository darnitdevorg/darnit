# Vulture allowlist — false positives and intentional unused code
#
# These entries suppress vulture warnings for code that appears unused but is
# intentionally kept. Vulture allowlists use attribute access to mark names used.

# MCP tool parameters: part of the public MCP tool schema, exposed to AI
# assistants even though the function body doesn't use them yet.
# Removing them would change the tool's API contract.
_ = auto_init_config  # noqa: F821  # audit_openssf_baseline parameter
_ = attest  # noqa: F821  # audit_openssf_baseline parameter
