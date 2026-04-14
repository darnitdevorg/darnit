# Unauthenticated mcp tool (mcp): (dynamic — registered from registry.tools)

**STRIDE category:** Spoofing
**Rule ID:** `python.entry.mcp_tool_imperative`
**Max severity:** MEDIUM

## Mitigation

> MCP servers operate over stdio transport — authentication is enforced by the MCP client (e.g., Claude Code), not by endpoint decorators. The scanner flagged missing decorator-level auth, which is an architectural pattern mismatch, not a real vulnerability.

*Applies to 2 of 2 instances.*

## Representative Examples

<details>
<summary><code>packages/darnit/src/darnit/server/factory.py:149</code></summary>

```
     139 |     server = FastMCP(server_name)
     140 | 
     141 |     # Register each tool
     142 |     registered_count = 0
     143 |     for name, spec in registry.tools.items():
     144 |         try:
     145 |             handler = registry.load_handler(spec, framework_name=framework_name)
     146 |             # Inject TOML config into handler if parameters are defined
     147 |             if spec.parameters:
     148 |                 handler = _bind_tool_config(handler, spec.parameters)
>>>  149 |             server.add_tool(handler, name=name, description=spec.description)
     150 |             registered_count += 1
     151 |             logger.debug(f"Registered tool: {name}")
     152 |         except (ImportError, AttributeError, ValueError) as e:
     153 |             logger.warning(f"Failed to load tool '{name}': {e}")
     154 |             continue
     155 | 
     156 |     logger.info(
     157 |         f"Created MCP server '{server_name}' with {registered_count} tools"
     158 |     )
     159 | 
```

*No authentication decorator was found on this endpoint. If the endpoint handles sensitive actions, it may be accessible to unauthenticated callers. Verify whether authentication is enforced at a different layer (middleware, reverse proxy, MCP client credential check).*

</details>

<details>
<summary><code>packages/darnit/src/darnit/server/factory.py:195</code></summary>

```
     185 | 
     186 |     registry = ToolRegistry.from_toml(config)
     187 |     server = FastMCP(server_name)
     188 | 
     189 |     for name, spec in registry.tools.items():
     190 |         try:
     191 |             handler = registry.load_handler(spec, framework_name=framework_name)
     192 |             # Inject TOML config into handler if parameters are defined
     193 |             if spec.parameters:
     194 |                 handler = _bind_tool_config(handler, spec.parameters)
>>>  195 |             server.add_tool(handler, name=name, description=spec.description)
     196 |         except (ImportError, AttributeError, ValueError) as e:
     197 |             logger.warning(f"Failed to load tool '{name}': {e}")
     198 | 
     199 |     return server
```

*No authentication decorator was found on this endpoint. If the endpoint handles sensitive actions, it may be accessible to unauthenticated callers. Verify whether authentication is enforced at a different layer (middleware, reverse proxy, MCP client credential check).*

</details>

## All Instances

| # | File | Line | Severity | Confidence | Status |
|---|------|------|----------|------------|--------|
| 1 | `packages/darnit/src/darnit/server/factory.py` | 149 | MEDIUM | 0.85 | Mitigated |
| 2 | `packages/darnit/src/darnit/server/factory.py` | 195 | MEDIUM | 0.85 | Mitigated |

*2 instances total.*

