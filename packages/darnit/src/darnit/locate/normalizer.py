"""Tool output normalizer.

This module provides functions to normalize external tool outputs
(like Scorecard, Trivy, Kusari) to the standardized CheckOutput format.

The normalizer uses JSONPath expressions from OutputMapping to extract
relevant fields from tool outputs.
"""

from typing import Any, Dict, Optional, Union

from darnit.core.logging import get_logger
from darnit.config.framework_schema import OutputMapping

from .models import CheckOutput, FoundEvidence, create_error_output

logger = get_logger("locate.normalizer")


def extract_jsonpath(data: Any, path: Optional[str]) -> Any:
    """Extract a value from data using a simple JSONPath expression.

    Supports a subset of JSONPath:
    - $.field - Root field access
    - $.field.nested - Nested field access
    - $.array[0] - Array index access
    - $.field[*].subfield - Not supported (returns None)

    Args:
        data: The data to extract from (dict or list)
        path: JSONPath expression (e.g., "$.checks.BranchProtection.pass")

    Returns:
        Extracted value or None if not found
    """
    if path is None or data is None:
        return None

    # Remove leading $. if present
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        path = path[1:]

    # Split path into segments
    segments = []
    current = ""
    i = 0
    while i < len(path):
        char = path[i]
        if char == ".":
            if current:
                segments.append(current)
                current = ""
        elif char == "[":
            if current:
                segments.append(current)
                current = ""
            # Find matching ]
            j = i + 1
            while j < len(path) and path[j] != "]":
                j += 1
            index_str = path[i + 1:j]
            if index_str.isdigit():
                segments.append(int(index_str))
            i = j
        else:
            current += char
        i += 1

    if current:
        segments.append(current)

    # Navigate through data
    result = data
    for segment in segments:
        if result is None:
            return None
        if isinstance(segment, int):
            if isinstance(result, list) and 0 <= segment < len(result):
                result = result[segment]
            else:
                return None
        elif isinstance(result, dict):
            result = result.get(segment)
        else:
            return None

    return result


def normalize_tool_output(
    raw_output: Union[Dict[str, Any], str],
    output_mapping: OutputMapping,
) -> CheckOutput:
    """Normalize external tool output to CheckOutput contract.

    Args:
        raw_output: Raw output from the tool (typically JSON dict)
        output_mapping: Mapping configuration for extraction

    Returns:
        Normalized CheckOutput
    """
    # Handle string input (try to parse as JSON)
    if isinstance(raw_output, str):
        import json
        try:
            raw_output = json.loads(raw_output)
        except json.JSONDecodeError:
            return create_error_output(
                message="Failed to parse tool output as JSON",
            )

    if not isinstance(raw_output, dict):
        return create_error_output(
            message=f"Expected dict output, got {type(raw_output).__name__}",
        )

    # Extract status
    status = _extract_status(raw_output, output_mapping)

    # Extract message
    message = _extract_message(raw_output, output_mapping, status)

    # Extract score and apply threshold
    score = None
    if output_mapping.score_path:
        score = extract_jsonpath(raw_output, output_mapping.score_path)
        if score is not None and output_mapping.pass_threshold is not None:
            try:
                score_float = float(score)
                if score_float >= output_mapping.pass_threshold:
                    status = "pass"
                else:
                    status = "fail"
            except (ValueError, TypeError):
                logger.warning(f"Could not convert score to float: {score}")

    # Extract found evidence
    found = _extract_found(raw_output, output_mapping)

    # Build confidence based on how complete the output is
    confidence = 1.0 if status in ("pass", "fail") else 0.5

    return CheckOutput(
        status=status,
        message=message,
        confidence=confidence,
        found=found,
        evidence={
            "raw_output": raw_output,
            "score": score,
        },
    )


def _extract_status(
    raw_output: Dict[str, Any],
    output_mapping: OutputMapping,
) -> str:
    """Extract status from raw output.

    Args:
        raw_output: Raw tool output
        output_mapping: Output mapping configuration

    Returns:
        Status string (pass, fail, error, inconclusive)
    """
    if not output_mapping.status_path:
        return "inconclusive"

    status_value = extract_jsonpath(raw_output, output_mapping.status_path)

    if status_value is None:
        return "inconclusive"

    # Handle boolean
    if isinstance(status_value, bool):
        return "pass" if status_value else "fail"

    # Handle string
    if isinstance(status_value, str):
        status_lower = status_value.lower()
        if status_lower in ("pass", "passed", "success", "true", "ok"):
            return "pass"
        elif status_lower in ("fail", "failed", "failure", "false", "error"):
            return "fail"
        elif status_lower in ("error", "exception"):
            return "error"
        else:
            return "inconclusive"

    # Handle numeric (treat non-zero as pass)
    if isinstance(status_value, (int, float)):
        return "pass" if status_value else "fail"

    return "inconclusive"


def _extract_message(
    raw_output: Dict[str, Any],
    output_mapping: OutputMapping,
    status: str,
) -> str:
    """Extract message from raw output.

    Args:
        raw_output: Raw tool output
        output_mapping: Output mapping configuration
        status: Extracted status

    Returns:
        Message string
    """
    if output_mapping.message_path:
        message = extract_jsonpath(raw_output, output_mapping.message_path)
        if message is not None:
            return str(message)

    # Generate default message
    if status == "pass":
        return "Check passed"
    elif status == "fail":
        return "Check failed"
    elif status == "error":
        return "Check encountered an error"
    else:
        return "Check result inconclusive"


def _extract_found(
    raw_output: Dict[str, Any],
    output_mapping: OutputMapping,
) -> Optional[FoundEvidence]:
    """Extract found evidence from raw output.

    Args:
        raw_output: Raw tool output
        output_mapping: Output mapping configuration

    Returns:
        FoundEvidence or None
    """
    if not output_mapping.found_path:
        return None

    found_value = extract_jsonpath(raw_output, output_mapping.found_path)
    if found_value is None:
        return None

    # Determine kind
    kind = output_mapping.found_kind_default
    if output_mapping.found_kind_path:
        extracted_kind = extract_jsonpath(raw_output, output_mapping.found_kind_path)
        if extracted_kind in ("file", "url", "api", "config"):
            kind = extracted_kind

    # Build FoundEvidence based on kind
    found_str = str(found_value)
    if kind == "file":
        return FoundEvidence(path=found_str, kind="file")
    elif kind == "url":
        return FoundEvidence(url=found_str, kind="url")
    elif kind == "api":
        return FoundEvidence(api_endpoint=found_str, kind="api")
    elif kind == "config":
        return FoundEvidence(path=found_str, kind="config")

    return None


def normalize_scorecard_output(
    raw_output: Dict[str, Any],
    check_name: str,
) -> CheckOutput:
    """Convenience function to normalize Scorecard output.

    Scorecard has a known output format, so we can use a predefined mapping.

    Args:
        raw_output: Scorecard JSON output
        check_name: Name of the check to extract (e.g., "BranchProtection")

    Returns:
        Normalized CheckOutput
    """
    # Scorecard uses 0-10 scale, 8.0+ is considered passing
    pass_threshold = 8.0

    # Find the check manually (JSONPath filter expressions not supported)
    checks = raw_output.get("checks", [])
    target_check = None
    for check in checks:
        if check.get("name") == check_name:
            target_check = check
            break

    if target_check is None:
        return CheckOutput(
            status="inconclusive",
            message=f"Check '{check_name}' not found in Scorecard output",
            confidence=0.5,
            evidence={"raw_output": raw_output},
        )

    # Extract from the check
    score = target_check.get("score", -1)
    reason = target_check.get("reason", "")

    # Scorecard uses -1 for inconclusive
    if score == -1:
        return CheckOutput(
            status="inconclusive",
            message=reason or f"Scorecard returned inconclusive for {check_name}",
            confidence=0.5,
            evidence={"raw_output": raw_output, "score": score},
        )

    # Apply threshold
    status = "pass" if score >= pass_threshold else "fail"

    return CheckOutput(
        status=status,
        message=reason or f"Scorecard {check_name}: score {score}/10",
        confidence=1.0 if status != "inconclusive" else 0.5,
        evidence={"raw_output": raw_output, "score": score},
    )


__all__ = [
    "extract_jsonpath",
    "normalize_tool_output",
    "normalize_scorecard_output",
]
