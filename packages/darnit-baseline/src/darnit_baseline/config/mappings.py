"""OSPS-specific configuration mappings for OpenSSF Baseline."""

from typing import Dict, List, Set

# Re-export from darnit.config.schema for convenience
from darnit.config.schema import (
    ProjectType,
    ProjectConfig,
    ControlOverride,
    ControlStatusValue,
    PathRef,
    BaselineExtension,
)

# Re-export legacy ResourceReference for backward compatibility
from darnit.config import ResourceReference

# Also re-export discovery utilities
from darnit.config import (
    discover_files,
    sync_discovered_to_config,
)


# Controls excluded by default for each project type
PROJECT_TYPE_EXCLUSIONS: Dict[str, Set[str]] = {
    "software": set(),  # All controls apply

    "specification": {
        "OSPS-BR-02",      # SBOM - no distributable artifacts
        "OSPS-BR-03",      # Signing/provenance - no releases
        "OSPS-VM-05",      # SCA/dependency scanning - no deps
        "OSPS-QA-02",      # Automated testing - no code to test
    },

    "documentation": {
        "OSPS-BR-02",      # SBOM
        "OSPS-BR-03",      # Signing/provenance
        "OSPS-VM-05",      # SCA/dependency scanning
        "OSPS-QA-02",      # Automated testing
        "OSPS-SA-02",      # Vulnerability management
        "OSPS-SA-03",      # Threat modeling
    },

    "infrastructure": {
        "OSPS-BR-02",      # SBOM (may still apply in some cases)
    },

    "data": {
        "OSPS-BR-01",      # CI/CD security
        "OSPS-BR-02",      # SBOM
        "OSPS-BR-03",      # Signing/provenance
        "OSPS-QA-02",      # Automated testing
        "OSPS-QA-03",      # Code review
    },
}


# Mapping of OSPS controls to .project.yaml reference paths
# Format: "section.field" - resolver will check both standard and extension sections
CONTROL_REFERENCE_MAPPING: Dict[str, str] = {
    # Security (standard .project fields)
    # SECURITY.md addresses multiple controls (VM and DO domains)
    "OSPS-VM-01.01": "security.policy",           # SECURITY.md - vulnerability reporting contact
    "OSPS-VM-02.01": "security.policy",           # SECURITY.md - vulnerability reporting process
    "OSPS-VM-03.01": "security.policy",           # SECURITY.md - response timeline
    "OSPS-DO-02.01": "security.policy",           # SECURITY.md (documentation domain)
    "OSPS-SA-03.02": "security.threat_model",     # Threat model

    # Governance (standard .project fields)
    # CONTRIBUTING.md addresses multiple controls
    "OSPS-GV-03.01": "governance.contributing",   # CONTRIBUTING.md - contribution guide exists
    "OSPS-GV-03.02": "governance.contributing",   # CONTRIBUTING.md - development process documented
    "OSPS-DO-01.02": "governance.contributing",   # CONTRIBUTING.md (documentation domain)
    "OSPS-GV-04.01": "governance.codeowners",     # CODEOWNERS

    # Governance (extension fields - to be upstreamed)
    "OSPS-GV-01.01": "governance.maintainers",    # MAINTAINERS.md (extension)
    "OSPS-GV-01.02": "governance.code_of_conduct", # CODE_OF_CONDUCT.md (extension)

    # Legal (standard .project fields)
    "OSPS-LI-01.01": "legal.license",             # LICENSE

    # Legal (extension fields)
    "OSPS-LE-01.01": "legal.contributor_agreement",  # DCO/CLA (extension)

    # Artifacts (extension fields)
    "OSPS-BR-02.01": "artifacts.sbom",            # SBOM (extension)
    "OSPS-BR-03.01": "artifacts.signing",         # Release signing (extension)
    "OSPS-BR-03.02": "artifacts.provenance",      # Provenance (extension)

    # Quality (extension fields)
    "OSPS-DO-01.01": "quality.changelog",         # CHANGELOG (extension)

    # Documentation (standard .project fields)
    "OSPS-DO-01.03": "documentation.readme",      # README
    "OSPS-DO-03.01": "documentation.support",     # SUPPORT.md
}


# Default file locations for discovery
# These are used when no .project.yaml exists to auto-discover files
DEFAULT_FILE_LOCATIONS: Dict[str, List[str]] = {
    # Security documentation
    "security.policy": [
        "SECURITY.md", "security.md", ".github/SECURITY.md",
        "docs/SECURITY.md", "docs/security.md"
    ],
    "security.threat_model": [
        "THREAT_MODEL.md", "threat_model.md", "threat-model.md",
        "docs/THREAT_MODEL.md", "docs/threat_model.md", "docs/threat-model.md",
        "docs/security/THREAT_MODEL.md", "security/THREAT_MODEL.md"
    ],
    "security.secrets_policy": [
        "docs/SECRETS.md", "docs/secrets.md", "SECRETS.md",
        "docs/security/SECRETS.md"
    ],

    # Governance documentation (standard fields)
    "governance.contributing": [
        "CONTRIBUTING.md", "contributing.md", ".github/CONTRIBUTING.md",
        "docs/CONTRIBUTING.md"
    ],
    "governance.codeowners": [
        "CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"
    ],
    "governance.governance_doc": [
        "GOVERNANCE.md", "governance.md", "docs/GOVERNANCE.md",
        ".github/GOVERNANCE.md"
    ],

    # Governance documentation (extension fields)
    "governance.maintainers": [
        "MAINTAINERS.md", "MAINTAINERS", "maintainers.md",
        "docs/MAINTAINERS.md", ".github/MAINTAINERS.md"
    ],
    "governance.code_of_conduct": [
        "CODE_OF_CONDUCT.md", "code_of_conduct.md", ".github/CODE_OF_CONDUCT.md",
        "docs/CODE_OF_CONDUCT.md"
    ],

    # Legal documentation
    "legal.license": [
        "LICENSE", "LICENSE.md", "LICENSE.txt", "license", "COPYING"
    ],
    "legal.dco": [
        "DCO", "DCO.md", ".github/DCO", ".github/DCO.md"
    ],
    "legal.cla": [
        "CLA", "CLA.md", ".github/CLA", ".github/CLA.md"
    ],

    # Quality documentation (extension fields)
    "quality.changelog": [
        "CHANGELOG.md", "CHANGELOG", "changelog.md", "HISTORY.md",
        "docs/CHANGELOG.md", "CHANGES.md"
    ],

    # Project documentation (standard fields)
    "documentation.readme": [
        "README.md", "README", "readme.md", "README.rst"
    ],
    "documentation.support": [
        "SUPPORT.md", "support.md", ".github/SUPPORT.md",
        "docs/SUPPORT.md"
    ],
    "documentation.architecture": [
        "docs/ARCHITECTURE.md", "docs/architecture.md", "ARCHITECTURE.md",
        "docs/design/ARCHITECTURE.md", "architecture.md"
    ],
    "documentation.api": [
        "docs/API.md", "docs/api.md", "API.md",
        "docs/api/README.md", "api/README.md"
    ],

    # Build artifacts (extension fields)
    "artifacts.sbom": [
        "sbom.json", "sbom.xml", ".sbom/sbom.json", "bom.json",
        "sbom.spdx.json", "sbom.cdx.json"
    ],

    # Dependency management (extension fields)
    "dependencies.lockfile": [
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "Pipfile.lock", "poetry.lock", "pdm.lock", "uv.lock",
        "Gemfile.lock", "Cargo.lock", "go.sum",
        "composer.lock", "mix.lock", "pubspec.lock",
    ],
    "dependencies.manifest": [
        "package.json", "Cargo.toml", "go.mod", "Gemfile",
        "pyproject.toml", "requirements.txt", "setup.py", "composer.json"
    ],
    "dependencies.docs": [
        "DEPENDENCIES.md", "dependencies.md", "docs/DEPENDENCIES.md",
        "docs/dependencies.md"
    ],

    # Testing documentation
    "testing.docs": [
        "docs/TESTING.md", "docs/testing.md", "TESTING.md",
        "test/README.md", "tests/README.md"
    ],

    # Release documentation
    "releases.docs": [
        "docs/RELEASING.md", "docs/releasing.md", "RELEASING.md",
        "docs/RELEASE.md"
    ],

    # CI/CD configurations - GitHub
    "ci.github.dependabot": [
        ".github/dependabot.yml", ".github/dependabot.yaml"
    ],
    "ci.github.dco_config": [
        ".github/dco.yml", ".github/dco.yaml"
    ],
    "ci.github.codeql": [
        ".github/workflows/codeql.yml", ".github/workflows/codeql.yaml",
        ".github/workflows/codeql-analysis.yml"
    ],
    "ci.github.release": [
        ".github/workflows/release.yml", ".github/workflows/release.yaml",
        ".github/workflows/publish.yml", ".github/workflows/deploy.yml"
    ],

    # CI/CD configurations - Other providers
    "ci.gitlab": [
        ".gitlab-ci.yml", ".gitlab-ci.yaml"
    ],
    "ci.circleci": [
        ".circleci/config.yml", ".circleci/config.yaml"
    ],
    "ci.jenkins": [
        "Jenkinsfile", "jenkins/Jenkinsfile"
    ],
    "ci.travis": [
        ".travis.yml", ".travis.yaml"
    ],
    "ci.azure": [
        "azure-pipelines.yml", "azure-pipelines.yaml",
        ".azure-pipelines/azure-pipelines.yml"
    ],
}


def get_config_path(config: ProjectConfig, section: str, field: str) -> str | None:
    """Get a path from config, checking both standard and extension sections.

    This is a convenience wrapper around config.get_path() that handles
    the section/field resolution for OSPS controls.

    Args:
        config: ProjectConfig instance
        section: Section name (e.g., "security", "governance")
        field: Field name (e.g., "policy", "maintainers")

    Returns:
        Path string or None if not found
    """
    return config.get_path(section, field)


def resolve_control_path(config: ProjectConfig, control_id: str) -> str | None:
    """Resolve the file path for a control from the config.

    Args:
        config: ProjectConfig instance
        control_id: OSPS control ID (e.g., "OSPS-DO-02.01")

    Returns:
        Path string or None if not found
    """
    ref_path = CONTROL_REFERENCE_MAPPING.get(control_id)
    if not ref_path:
        return None

    parts = ref_path.split(".", 1)
    if len(parts) != 2:
        return None

    section, field = parts
    return config.get_path(section, field)


__all__ = [
    # Re-exports from darnit
    "ProjectType",
    "ProjectConfig",
    "ControlOverride",
    "ControlStatusValue",
    "PathRef",
    "BaselineExtension",
    "ResourceReference",
    "discover_files",
    "sync_discovered_to_config",
    # OSPS-specific
    "PROJECT_TYPE_EXCLUSIONS",
    "CONTROL_REFERENCE_MAPPING",
    "DEFAULT_FILE_LOCATIONS",
    # Helpers
    "get_config_path",
    "resolve_control_path",
]
