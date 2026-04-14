"""Tree-sitter queries for YAML discovery.

v1 scope for YAML is deliberately narrow — GitHub Actions workflow files
are the only threat-model-relevant YAML in darnit's typical target
repositories. Asset discovery for YAML is limited to workflow ``on:`` and
``permissions:`` top-level keys so ``generators.py`` can note the workflow
attack surface in the Asset Inventory section.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..parsing import make_query

#: Top-level ``on:`` block — identifies workflow trigger events.
#: Captures: @key @value
YAML_TOP_KEY = make_query(
    "yaml",
    """
(block_mapping_pair
  key: (flow_node (plain_scalar) @key)
  value: (_) @value)
""",
)


@dataclass(frozen=True)
class YamlQuery:
    id: str
    query: Any
    intent: str
    mitigation_hint: str = ""


QUERY_REGISTRY: dict[str, YamlQuery] = {
    "yaml.structure.top_key": YamlQuery(
        id="yaml.structure.top_key",
        query=YAML_TOP_KEY,
        intent="structural",
    ),
}


__all__ = ["YAML_TOP_KEY", "YamlQuery", "QUERY_REGISTRY"]
