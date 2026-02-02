"""LLM consultation protocol for sieve verification.

This module handles the formatting of consultation requests to be sent
to the calling LLM, and parsing of responses back into structured data.

Since MCP servers cannot call LLMs directly, the protocol works by:
1. Returning a formatted prompt to the calling LLM via the MCP tool response
2. The LLM analyzes and responds with structured JSON
3. A follow-up tool call processes the response
"""

import json
import re
from typing import Any

from darnit.core.logging import get_logger

from .models import (
    LLMConsultationRequest,
    LLMConsultationResponse,
    PassOutcome,
)

logger = get_logger("sieve.llm_protocol")


def format_consultation_prompt(request: LLMConsultationRequest) -> str:
    """
    Format an LLM consultation request as a prompt string.

    This is returned to the calling LLM (Claude) via the MCP tool response.
    The LLM can then analyze and respond with the structured format.

    Args:
        request: The consultation request with context and prompt

    Returns:
        Formatted prompt string for LLM analysis
    """
    # Format context as JSON, handling non-serializable objects
    try:
        context_json = json.dumps(request.context, indent=2, default=str)
        # Truncate very long context
        if len(context_json) > 8000:
            context_json = context_json[:8000] + "\n... [truncated]"
    except (TypeError, ValueError):
        context_json = str(request.context)[:8000]

    # Format analysis hints as bullet points
    hints_section = ""
    if request.analysis_hints:
        hints_section = "### Analysis Hints\n" + "\n".join(
            f"- {hint}" for hint in request.analysis_hints
        )

    prompt = f"""## Security Compliance Verification Required

**Control ID:** {request.control_id}
**Control Name:** {request.control_name}

### Requirement
{request.control_description or "See control specification"}

### Context Gathered
```json
{context_json}
```

### Analysis Question
{request.prompt}

{hints_section}

### Required Response Format
Please analyze the context and respond with a JSON object:
```json
{request.expected_response}
```

**Important:**
- Set `status` to "PASS" if the requirement is clearly met
- Set `status` to "FAIL" if the requirement is clearly NOT met
- Set `status` to "INCONCLUSIVE" if you cannot determine with confidence
- Set `confidence` to a value between 0.0 and 1.0 reflecting your certainty
- Provide clear `reasoning` explaining your analysis
- List specific `evidence` from the context that supports your conclusion

Provide your analysis below:"""

    return prompt


def parse_llm_response(response_text: str) -> LLMConsultationResponse | None:
    """
    Parse an LLM response into a structured consultation response.

    Attempts to extract JSON from the response text using multiple strategies.

    Args:
        response_text: Raw text response from the LLM

    Returns:
        Parsed LLMConsultationResponse, or None if parsing fails
    """
    data = None

    # Strategy 1: Look for JSON in code block
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 2: Look for JSON in generic code block
    if not data:
        code_match = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
        if code_match:
            try:
                data = json.loads(code_match.group(1))
            except json.JSONDecodeError:
                pass

    # Strategy 3: Look for JSON object pattern
    if not data:
        obj_match = re.search(r"\{[^{}]*\}", response_text, re.DOTALL)
        if obj_match:
            try:
                data = json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                pass

    # Strategy 4: Try parsing the whole response as JSON
    if not data:
        try:
            data = json.loads(response_text.strip())
        except json.JSONDecodeError:
            pass

    if not data:
        return None

    # Map status string to PassOutcome
    status_map = {
        "PASS": PassOutcome.PASS,
        "FAIL": PassOutcome.FAIL,
        "INCONCLUSIVE": PassOutcome.INCONCLUSIVE,
        "pass": PassOutcome.PASS,
        "fail": PassOutcome.FAIL,
        "inconclusive": PassOutcome.INCONCLUSIVE,
    }

    status_str = data.get("status", "INCONCLUSIVE")
    status = status_map.get(status_str, PassOutcome.INCONCLUSIVE)

    # Parse confidence, handling various formats
    confidence = data.get("confidence", 0.5)
    if isinstance(confidence, str):
        try:
            # Handle percentage strings like "80%" or "0.8"
            confidence = float(confidence.replace("%", "")) / (
                100 if "%" in str(data.get("confidence", "")) else 1
            )
        except (ValueError, TypeError):
            confidence = 0.5

    # Ensure confidence is in valid range
    confidence = max(0.0, min(1.0, float(confidence)))

    # Parse evidence, handling string or list
    evidence = data.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]
    elif not isinstance(evidence, list):
        evidence = []

    return LLMConsultationResponse(
        status=status,
        confidence=confidence,
        reasoning=str(data.get("reasoning", "")),
        evidence_cited=evidence,
    )


def format_consultation_result(
    control_id: str, response: LLMConsultationResponse
) -> dict[str, Any]:
    """
    Format a consultation response as a result dict.

    This creates a structured result that can be included in audit output.

    Args:
        control_id: The control that was analyzed
        response: The parsed LLM response

    Returns:
        Dict with consultation result details
    """
    return {
        "control_id": control_id,
        "llm_status": response.status.name,
        "llm_confidence": response.confidence,
        "llm_reasoning": response.reasoning,
        "llm_evidence": response.evidence_cited,
        "meets_threshold": response.confidence >= 0.8,
    }


def create_verification_request_for_pending(
    pending_result: dict[str, Any]
) -> str | None:
    """
    Create a verification prompt from a PENDING_LLM result.

    This extracts the consultation request from a SieveResult with
    PENDING_LLM status and formats it for the calling LLM.

    Args:
        pending_result: Dict from SieveResult.to_legacy_dict() or similar

    Returns:
        Formatted prompt string, or None if no consultation request found
    """
    evidence = pending_result.get("evidence", {})
    consultation = evidence.get("llm_consultation")

    if not consultation:
        return None

    # Handle both LLMConsultationRequest objects and dicts
    if isinstance(consultation, LLMConsultationRequest):
        return format_consultation_prompt(consultation)
    elif isinstance(consultation, dict):
        # Reconstruct request from dict
        request = LLMConsultationRequest(
            control_id=consultation.get("control_id", ""),
            control_name=consultation.get("control_name", ""),
            control_description=consultation.get("control_description", ""),
            prompt=consultation.get("prompt", ""),
            context=consultation.get("context", {}),
            analysis_hints=consultation.get("analysis_hints", []),
            expected_response=consultation.get("expected_response", ""),
        )
        return format_consultation_prompt(request)

    return None
