"""Asset discovery for threat modeling.

This module provides functions to discover security-relevant assets
in a codebase, including entry points, authentication mechanisms,
data stores, sensitive data, and secrets.
"""

import os
import re
from typing import Any

from darnit.core.logging import get_logger

from .models import (
    AssetInventory,
    AuthMechanism,
    DataStore,
    EntryPoint,
    SecretReference,
    SensitiveData,
)
from .patterns import (
    AUTH_PATTERNS,
    DATASTORE_PATTERNS,
    FRAMEWORK_PATTERNS,
    INJECTION_PATTERNS,
    SECRET_PATTERNS,
    SENSITIVE_DATA_PATTERNS,
    SKIP_DIRECTORIES,
    SOURCE_EXTENSIONS,
)

logger = get_logger("threat_model.discovery")


def detect_frameworks(local_path: str) -> list[str]:
    """Detect frameworks used in the project.

    Args:
        local_path: Path to the repository

    Returns:
        List of detected framework names
    """
    detected = []

    for framework, config in FRAMEWORK_PATTERNS.items():
        for indicator in config["indicators"]:
            filename, pattern = indicator
            if filename:
                # Check if file exists
                filepath = os.path.join(local_path, filename)
                if os.path.exists(filepath):
                    if pattern:
                        try:
                            with open(filepath, errors='ignore') as f:
                                content = f.read()
                                if re.search(pattern, content):
                                    detected.append(framework)
                                    break
                        except OSError:
                            pass
                    else:
                        detected.append(framework)
                        break
            elif pattern:
                # Search for pattern in source files
                for root, dirs, files in os.walk(local_path):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]
                    for fn in files:
                        if fn.endswith(SOURCE_EXTENSIONS):
                            filepath = os.path.join(root, fn)
                            try:
                                with open(filepath, errors='ignore') as f:
                                    content = f.read(10000)  # Read first 10KB
                                    if re.search(pattern, content):
                                        detected.append(framework)
                                        break
                            except OSError:
                                pass
                    if framework in detected:
                        break

    return list(set(detected))


def discover_entry_points(local_path: str, frameworks: list[str]) -> list[EntryPoint]:
    """Discover API entry points in the codebase.

    Args:
        local_path: Path to the repository
        frameworks: List of detected frameworks

    Returns:
        List of discovered entry points
    """
    entry_points = []
    entry_id = 0

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]

        for filename in files:
            if not filename.endswith(SOURCE_EXTENSIONS):
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, local_path)

            try:
                with open(filepath, errors='ignore') as f:
                    content = f.read()
                    lines = content.split('\n')
            except OSError:
                continue

            # Check Next.js API routes
            if "nextjs" in frameworks:
                # App Router API routes
                if re.match(r"app/api/.*/route\.(ts|js)x?$", rel_path.replace("\\", "/")):
                    methods = []
                    for method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                        if re.search(rf"export\s+(async\s+)?function\s+{method}\b", content):
                            methods.append(method)

                    for method in methods or ['ALL']:
                        entry_id += 1
                        api_path = "/" + "/".join(rel_path.replace("\\", "/").split("/")[:-1])
                        api_path = api_path.replace("/app", "").replace("/route", "")
                        has_auth = bool(re.search(r"getServerSession|auth\(|currentUser|useAuth", content))

                        entry_points.append(EntryPoint(
                            id=f"EP-{entry_id:03d}",
                            entry_type="api_route",
                            path=api_path,
                            method=method,
                            file=rel_path,
                            line=1,
                            authentication_required=has_auth,
                            framework="nextjs"
                        ))

                # Server Actions
                if "'use server'" in content or '"use server"' in content:
                    for i, line in enumerate(lines):
                        if re.match(r"^export\s+(async\s+)?function\s+\w+", line):
                            func_match = re.search(r"function\s+(\w+)", line)
                            if func_match:
                                entry_id += 1
                                entry_points.append(EntryPoint(
                                    id=f"EP-{entry_id:03d}",
                                    entry_type="server_action",
                                    path=func_match.group(1),
                                    method="POST",
                                    file=rel_path,
                                    line=i + 1,
                                    authentication_required=False,
                                    framework="nextjs"
                                ))

            # Check Express routes
            if "express" in frameworks:
                for i, line in enumerate(lines):
                    match = re.search(
                        r"(?:app|router)\.(get|post|put|delete|patch|all)\s*\(\s*['\"]([^'\"]+)['\"]",
                        line, re.IGNORECASE
                    )
                    if match:
                        entry_id += 1
                        entry_points.append(EntryPoint(
                            id=f"EP-{entry_id:03d}",
                            entry_type="api_route",
                            path=match.group(2),
                            method=match.group(1).upper(),
                            file=rel_path,
                            line=i + 1,
                            authentication_required=False,
                            framework="express"
                        ))

            # Check FastAPI routes
            if "fastapi" in frameworks:
                for i, line in enumerate(lines):
                    match = re.search(
                        r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
                        line, re.IGNORECASE
                    )
                    if match:
                        entry_id += 1
                        entry_points.append(EntryPoint(
                            id=f"EP-{entry_id:03d}",
                            entry_type="api_route",
                            path=match.group(2),
                            method=match.group(1).upper(),
                            file=rel_path,
                            line=i + 1,
                            authentication_required=False,
                            framework="fastapi"
                        ))

            # Check Django URLs
            if "django" in frameworks:
                for i, line in enumerate(lines):
                    match = re.search(r"path\s*\(\s*['\"]([^'\"]+)['\"]", line)
                    if match:
                        entry_id += 1
                        entry_points.append(EntryPoint(
                            id=f"EP-{entry_id:03d}",
                            entry_type="api_route",
                            path=match.group(1),
                            method="ANY",
                            file=rel_path,
                            line=i + 1,
                            authentication_required=False,
                            framework="django"
                        ))

            # Check Flask routes
            if "flask" in frameworks:
                for i, line in enumerate(lines):
                    match = re.search(r"@\w+\.route\s*\(\s*['\"]([^'\"]+)['\"]", line)
                    if match:
                        methods_match = re.search(
                            r"methods\s*=\s*\[([^\]]+)\]",
                            lines[i] if i < len(lines) else ""
                        )
                        methods = "GET"
                        if methods_match:
                            methods = methods_match.group(1).replace("'", "").replace('"', "").strip()

                        entry_id += 1
                        entry_points.append(EntryPoint(
                            id=f"EP-{entry_id:03d}",
                            entry_type="api_route",
                            path=match.group(1),
                            method=methods,
                            file=rel_path,
                            line=i + 1,
                            authentication_required=False,
                            framework="flask"
                        ))

    return entry_points


def discover_authentication(local_path: str) -> list[AuthMechanism]:
    """Discover authentication mechanisms in the codebase.

    Args:
        local_path: Path to the repository

    Returns:
        List of discovered authentication mechanisms
    """
    auth_mechanisms = []
    auth_id = 0

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]

        for filename in files:
            if not filename.endswith(('.ts', '.tsx', '.js', '.jsx', '.py')):
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, local_path)

            try:
                with open(filepath, errors='ignore') as f:
                    content = f.read()
            except OSError:
                continue

            for auth_type, config in AUTH_PATTERNS.items():
                matches = list(re.finditer(config["pattern"], content))
                if matches:
                    first_match = matches[0]
                    line_num = content[:first_match.start()].count('\n') + 1

                    auth_id += 1
                    auth_mechanisms.append(AuthMechanism(
                        id=f"AUTH-{auth_id:03d}",
                        auth_type=auth_type,
                        file=rel_path,
                        line=line_num,
                        framework=config["framework"],
                        assets=config["assets"]
                    ))
                    break  # Only record first occurrence per file

    return auth_mechanisms


def discover_sensitive_data(local_path: str) -> list[SensitiveData]:
    """Discover sensitive data fields in the codebase.

    Args:
        local_path: Path to the repository

    Returns:
        List of discovered sensitive data references
    """
    sensitive_data = []
    data_id = 0

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]

        for filename in files:
            if not filename.endswith(('.ts', '.tsx', '.js', '.jsx', '.py', '.prisma', '.graphql', '.gql')):
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, local_path)

            try:
                with open(filepath, errors='ignore') as f:
                    content = f.read()
                    lines = content.split('\n')
            except OSError:
                continue

            for data_type, config in SENSITIVE_DATA_PATTERNS.items():
                for pattern in config["patterns"]:
                    for i, line in enumerate(lines):
                        matches = re.findall(pattern, line, re.IGNORECASE)
                        for match in matches:
                            field_name = match if isinstance(match, str) else match[0] if match else ""
                            if field_name:
                                data_id += 1
                                sensitive_data.append(SensitiveData(
                                    id=f"SD-{data_id:03d}",
                                    data_type=data_type,
                                    field_name=field_name,
                                    file=rel_path,
                                    line=i + 1,
                                    context=line.strip()[:100]
                                ))

    return sensitive_data


def discover_secrets(local_path: str) -> list[SecretReference]:
    """Discover potential secrets in the codebase.

    Args:
        local_path: Path to the repository

    Returns:
        List of discovered potential secrets
    """
    secrets = []
    secret_id = 0

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]

        for filename in files:
            if not any(filename.endswith(ext) for ext in
                      ['.ts', '.tsx', '.js', '.jsx', '.py', '.env', '.json', '.yaml', '.yml', '.toml']):
                continue

            # Skip lock files
            if 'lock' in filename.lower():
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, local_path)

            try:
                with open(filepath, errors='ignore') as f:
                    content = f.read()
                    lines = content.split('\n')
            except OSError:
                continue

            for secret_type, config in SECRET_PATTERNS.items():
                for i, line in enumerate(lines):
                    if re.search(config["pattern"], line, re.IGNORECASE):
                        # Skip if it's a reference to env variable
                        if re.search(r"process\.env|os\.environ|getenv|ENV\[", line):
                            continue
                        # Skip if in example/test file
                        if any(x in rel_path.lower() for x in ['example', 'test', 'mock', 'fixture']):
                            continue

                        secret_id += 1
                        secrets.append(SecretReference(
                            id=f"SEC-{secret_id:03d}",
                            secret_type=secret_type,
                            name=line.strip()[:50],
                            file=rel_path,
                            line=i + 1,
                            severity=config["severity"]
                        ))

    return secrets


def discover_data_stores(local_path: str) -> list[DataStore]:
    """Discover data stores used in the project.

    Args:
        local_path: Path to the repository

    Returns:
        List of discovered data stores
    """
    data_stores = []
    store_id = 0
    found_stores = set()

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]

        for filename in files:
            if not filename.endswith(('.ts', '.tsx', '.js', '.jsx', '.py', '.prisma')):
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, local_path)

            try:
                with open(filepath, errors='ignore') as f:
                    content = f.read()
            except OSError:
                continue

            for store_name, config in DATASTORE_PATTERNS.items():
                if store_name in found_stores:
                    continue

                for pattern in config["patterns"]:
                    match = re.search(pattern, content)
                    if match:
                        line_num = content[:match.start()].count('\n') + 1
                        store_id += 1
                        data_stores.append(DataStore(
                            id=f"DS-{store_id:03d}",
                            store_type=config["type"],
                            technology=store_name,
                            file=rel_path,
                            line=line_num
                        ))
                        found_stores.add(store_name)
                        break

    return data_stores


def discover_injection_sinks(local_path: str) -> list[dict[str, Any]]:
    """Discover potential injection vulnerabilities.

    Args:
        local_path: Path to the repository

    Returns:
        List of potential injection sinks with metadata
    """
    sinks = []

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]

        for filename in files:
            if not filename.endswith(('.ts', '.tsx', '.js', '.jsx', '.py')):
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, local_path)

            try:
                with open(filepath, errors='ignore') as f:
                    content = f.read()
                    lines = content.split('\n')
            except OSError:
                continue

            for injection_type, config in INJECTION_PATTERNS.items():
                for pattern in config["patterns"]:
                    for i, line in enumerate(lines):
                        if re.search(pattern, line):
                            sinks.append({
                                "type": injection_type,
                                "file": rel_path,
                                "line": i + 1,
                                "snippet": line.strip()[:100],
                                "severity": config["severity"],
                                "cwe": config["cwe"],
                                "recommendation": config["recommendation"]
                            })

    return sinks


def discover_all_assets(local_path: str, frameworks: list[str] | None = None) -> AssetInventory:
    """Discover all security-relevant assets in the codebase.

    Args:
        local_path: Path to the repository
        frameworks: Optional list of frameworks (auto-detected if not provided)

    Returns:
        Complete asset inventory
    """
    if not frameworks:
        frameworks = detect_frameworks(local_path)

    return AssetInventory(
        entry_points=discover_entry_points(local_path, frameworks),
        data_stores=discover_data_stores(local_path),
        sensitive_data=discover_sensitive_data(local_path),
        secrets=discover_secrets(local_path),
        authentication=discover_authentication(local_path),
        frameworks_detected=frameworks
    )


__all__ = [
    "detect_frameworks",
    "discover_entry_points",
    "discover_authentication",
    "discover_sensitive_data",
    "discover_secrets",
    "discover_data_stores",
    "discover_injection_sinks",
    "discover_all_assets",
]
