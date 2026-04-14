# Dynamic import via importlib.import_module(module_path)

**STRIDE category:** Elevation of Privilege
**Rule ID:** `python.eop.dynamic_import_attr`
**Max severity:** MEDIUM

## Mitigation

> All dynamic imports enforce ALLOWED_MODULE_PREFIXES allowlist (darnit., darnit_baseline., darnit_plugins., darnit_testchecks.) before importing. Module paths come from TOML configuration, not external input.

*Applies to 4 of 4 instances.*

## Representative Examples

<details>
<summary><code>packages/darnit/src/darnit/core/registry.py:821</code></summary>

```
     811 | 
     812 |         # Security: Validate module path against allowlist to prevent arbitrary code loading
     813 |         if not any(module_path.startswith(prefix) for prefix in self.ALLOWED_MODULE_PREFIXES):
     814 |             logger.error(
     815 |                 f"Adapter {name}: module '{module_path}' not in allowed prefixes. "
     816 |                 f"Allowed: {self.ALLOWED_MODULE_PREFIXES}"
     817 |             )
     818 |             return None
     819 | 
     820 |         try:
>>>  821 |             module = importlib.import_module(module_path)
     822 |             adapter_class = getattr(module, class_name)
     823 |             return adapter_class()
     824 | 
     825 |         except ImportError as e:
     826 |             logger.error(f"Failed to import adapter {name}: {e}")
     827 |             return None
     828 |         except AttributeError as e:
     829 |             logger.error(f"Adapter {name}: class {class_name} not found: {e}")
     830 |             return None
     831 | 
```

*Dynamic imports allow loading arbitrary modules at runtime. If the module name originates from untrusted input, an attacker can achieve arbitrary code execution.*

</details>

<details>
<summary><code>packages/darnit/src/darnit/core/handlers.py:237</code></summary>

```
     227 |             module_path, func_name = path.rsplit(":", 1)
     228 | 
     229 |             # Validate module path against allowlist to prevent arbitrary imports
     230 |             if not any(module_path.startswith(prefix) for prefix in self.ALLOWED_MODULE_PREFIXES):
     231 |                 logger.warning(
     232 |                     f"Module path '{module_path}' not in allowed prefixes: "
     233 |                     f"{self.ALLOWED_MODULE_PREFIXES}"
     234 |                 )
     235 |                 return None
     236 | 
>>>  237 |             module = importlib.import_module(module_path)
     238 |             return getattr(module, func_name, None)
     239 |         except (ValueError, ImportError, AttributeError) as e:
     240 |             logger.warning(f"Failed to load handler from path '{path}': {e}")
     241 |             return None
     242 | 
     243 |     # =========================================================================
     244 |     # Pass Registration
     245 |     # =========================================================================
     246 | 
     247 |     def register_pass(
```

*Dynamic imports allow loading arbitrary modules at runtime. If the module name originates from untrusted input, an attacker can achieve arbitrary code execution.*

</details>

<details>
<summary><code>packages/darnit/src/darnit/core/adapters.py:666</code></summary>

```
     656 | 
     657 |         # Security: Validate module path against allowlist to prevent arbitrary code loading
     658 |         if not any(module_path.startswith(prefix) for prefix in self.ALLOWED_MODULE_PREFIXES):
     659 |             logger.error(
     660 |                 f"Adapter {name}: module '{module_path}' not in allowed prefixes. "
     661 |                 f"Allowed: {self.ALLOWED_MODULE_PREFIXES}"
     662 |             )
     663 |             return None
     664 | 
     665 |         try:
>>>  666 |             module = importlib.import_module(module_path)
     667 |             adapter_class = getattr(module, class_name)
     668 | 
     669 |             if not issubclass(adapter_class, expected_type):
     670 |                 logger.error(
     671 |                     f"Adapter {name}: {class_name} is not a {expected_type.__name__}"
     672 |                 )
     673 |                 return None
     674 | 
     675 |             return adapter_class()
     676 | 
```

*Dynamic imports allow loading arbitrary modules at runtime. If the module name originates from untrusted input, an attacker can achieve arbitrary code execution.*

</details>

## All Instances

| # | File | Line | Severity | Confidence | Status |
|---|------|------|----------|------------|--------|
| 1 | `packages/darnit/src/darnit/core/registry.py` | 821 | MEDIUM | 0.50 | Mitigated |
| 2 | `packages/darnit/src/darnit/core/handlers.py` | 237 | MEDIUM | 0.50 | Mitigated |
| 3 | `packages/darnit/src/darnit/core/adapters.py` | 666 | MEDIUM | 0.50 | Mitigated |
| 4 | `packages/darnit/src/darnit/server/registry.py` | 151 | MEDIUM | 0.50 | Mitigated |

*4 instances total.*

