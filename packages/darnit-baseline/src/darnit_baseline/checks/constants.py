"""Constants used by OpenSSF Baseline check functions."""

# OSI-approved license SPDX identifiers (lowercase for comparison)
OSI_LICENSES = {
    "mit", "apache-2.0", "gpl-2.0", "gpl-3.0", "lgpl-2.1", "lgpl-3.0",
    "bsd-2-clause", "bsd-3-clause", "mpl-2.0", "cc0-1.0", "unlicense",
    "isc", "artistic-2.0", "zlib", "ofl-1.1", "ncsa", "postgresql",
    "0bsd", "afl-3.0", "agpl-3.0", "bsl-1.0", "cecill-2.1", "ecl-2.0",
    "epl-1.0", "epl-2.0", "eupl-1.1", "eupl-1.2"
}

# Binary file extensions that shouldn't be in version control
BINARY_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib", ".o", ".obj",
    ".class", ".jar", ".war", ".ear", ".pyc", ".pyo", ".wasm",
    ".bin", ".dat", ".db", ".sqlite", ".sqlite3"
}

# Common dependency manifest files by ecosystem
DEPENDENCY_FILES = [
    # JavaScript/Node
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    # Python
    "requirements.txt", "Pipfile", "Pipfile.lock", "pyproject.toml", "poetry.lock",
    # Ruby
    "Gemfile", "Gemfile.lock",
    # Go
    "go.mod", "go.sum",
    # Rust
    "Cargo.toml", "Cargo.lock",
    # Java
    "pom.xml", "build.gradle", "build.gradle.kts",
    # PHP
    "composer.json", "composer.lock"
]

# Lockfile patterns for dependency pinning verification
LOCKFILE_PATTERNS = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "pdm.lock", "uv.lock",
    "Gemfile.lock", "Cargo.lock", "go.sum",
    "composer.lock", "mix.lock", "pubspec.lock",
]

# Common secret file patterns that should be gitignored
DANGEROUS_SECRET_FILES = [
    ".env", ".env.local", "credentials.json", "secrets.json", ".aws/credentials"
]

# Dangerous GitHub Actions contexts that can lead to injection
DANGEROUS_CONTEXTS = [
    "github.event.issue.title", "github.event.issue.body",
    "github.event.pull_request.title", "github.event.pull_request.body",
    "github.event.comment.body", "github.event.review.body",
    "github.event.discussion.title", "github.event.discussion.body"
]

# Secret patterns to detect hardcoded credentials
SECRET_PATTERNS = [
    r'(?i)(password|passwd|pwd)\s*[=:]\s*["\'][^"\']+["\']',
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\'][^"\']+["\']',
    r'(?i)(secret[_-]?key|secretkey)\s*[=:]\s*["\'][^"\']+["\']',
    r'(?i)(access[_-]?token|accesstoken)\s*[=:]\s*["\'][^"\']+["\']',
    r'(?i)aws[_-]?secret[_-]?access[_-]?key\s*[=:]\s*["\'][^"\']+["\']',
    r'ghp_[a-zA-Z0-9]{36}',  # GitHub PAT
    r'github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}',  # Fine-grained PAT
]

# Governance documentation files
GOVERNANCE_FILES = [
    "GOVERNANCE.md", "MAINTAINERS.md", "CODEOWNERS",
    ".github/CODEOWNERS", "OWNERS"
]

# Design documentation files
DESIGN_DOCS = [
    "ARCHITECTURE.md", "DESIGN.md",
    "docs/architecture.md", "docs/design.md"
]

# API documentation files
API_DOCS = [
    "API.md", "docs/api.md",
    "openapi.yaml", "openapi.json",
    "swagger.yaml", "swagger.json"
]

# Security assessment documentation
SECURITY_DOCS = [
    "SECURITY.md", "docs/security.md",
    "THREAT_MODEL.md", "docs/threat-model.md"
]

# Threat model documentation locations
THREAT_MODEL_DOCS = [
    "THREAT_MODEL.md", "threat_model.md", "threat-model.md",
    "docs/THREAT_MODEL.md", "docs/threat_model.md", "docs/threat-model.md",
    "docs/security/THREAT_MODEL.md", "docs/security/threat-model.md",
    "security/THREAT_MODEL.md", "security/threat-model.md"
]

# SCA (Software Composition Analysis) tool patterns
SCA_TOOL_PATTERNS = [
    (r'dependency-review-action|actions/dependency-review', 'dependency-review-action'),
    (r'npm\s+audit', 'npm audit'),
    (r'yarn\s+audit', 'yarn audit'),
    (r'safety\s+check', 'safety check'),
    (r'pip-audit', 'pip-audit'),
    (r'kusari\s+repo\s+scan', 'Kusari repo scan'),
    (r'kusari\s+risk-check', 'Kusari risk-check'),
    (r'kusari-action|kusariapp', 'Kusari Action'),
]
