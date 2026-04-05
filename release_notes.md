# Release Notes

## Version 0.3.4 — Test Suite Hardening, Zero-Blind-Spot Coverage & Deep Runtime Hardening

> **383 tests, 0 failures.** Five complete code-review passes of every module, eliminating 28 test blind spots and 39 source bugs (B1–B12, C1–C11, D1–D10, E1–E7).

### 🐛 Bug Fixes — Pass 5 & 6 (D/E-series, 17 new bugs fixed)

#### Middleware

| ID | Severity | Fix |
|----|----------|-----|
| **D1** | 🔴 High | `build_middleware_chain` Phase 2 (handler failure path) — `after()` hooks were not individually wrapped in `try/except`, breaking the before↔after pairing invariant. B4 had fixed Phase 3 (success) but Phase 2 was missed. |
| **D4** | 🟡 Med | `wrapped(**kwargs)` rejected positional arguments despite `__signature__` advertising them. Now `wrapped(*args, **kwargs)`. |
| **D10** | 🟢 Low | `MiddlewareManager.execute_before/execute_after` were dead code never called by the runtime. Both now emit `DeprecationWarning`. |

#### App Core

| ID | Severity | Fix |
|----|----------|-----|
| **D2** | 🟡 Med | `_wrap_with_security` called `inspect.signature(handler)` on **every request**. Now pre-computed once at closure-creation time. |
| **D5** | 🟢 Low | `_finalize_pending` used `list.pop(0)` (O(n) per call → O(n²) total). Now uses snapshot + clear for O(n). |
| **D6** | 🟡 Med | Duplicate `@app.get/@app.post` on the same path+method silently overwrote the first handler. Now emits `UserWarning` (matching B12 for resources). |
| **D7** | 🔴 High | `__version__ = "0.3.0"` was hardcoded and stale. Now reads dynamically from `importlib.metadata.version("prodmcp")`. |
| **D8** | 🔴 High | `_register_prompt` never stored the pre-built `wrapped` handler. `_add_prompt_route` always called `_build_handler()` again → double middleware wrapping. Now mirrors the B2 fix applied to tools. |
| **D9** | 🟡 Med | Shorthand bearer only stored the first tool's scopes. Subsequent tools' different scopes were silently omitted from `components.securitySchemes`. Now merges scopes across all tools. |

#### FastAPI Bridge

| ID | Severity | Fix |
|----|----------|-----|
| **E1** | 🟡 Med | `except ImportError` was too broad — a broken Pydantic plugin triggered `"FastAPI is required"` even when FastAPI was installed. Narrowed to `except ModuleNotFoundError`. |
| **E2** | 🔴 High | `_add_prompt_route` confirmed D8 in the bridge layer: always re-called `_build_handler()`. Fixed by reusing `meta["wrapped"]`. |
| **E3** | 🔴 High | `dict(body)` in `_add_prompt_route.dict_route_handler` was unguarded against JSON array bodies — exact same B8 pattern applied to tool routes but missed here. Now returns HTTP 422. |
| **E4** | 🟡 Med | `_add_resource_route` outer `try/except Exception → 404` wrapped the entire handler body. Registry `AttributeError`s became wrong-status 404s. Now only the FastMCP fallback is 404-protected. |

#### Validation & Dependencies

| ID | Severity | Fix |
|----|----------|-----|
| **E5** | 🟡 Med | Output validation used `if output_schema:` (truthiness) in both async/sync paths, inconsistent with Bug-F fix on input. A falsy `{}` schema silently skipped validation. Both paths now use `is not None`. |
| **E6** | 🟢 Low | `Depends` was re-exported from `prodmcp.security` — a DI primitive does not belong in the security package. Removed; import from `prodmcp` or `prodmcp.dependencies`. |
| **E7** | 🟡 Med | `anyio` was missing from `[dev]` in `pyproject.toml`. Async tests only worked via `fastmcp`'s transitive dep. Now explicitly declared. |

#### ⚠️ Breaking Change

`from prodmcp.security import Depends` now raises `ImportError`. Use `from prodmcp import Depends` instead.

---

### 🔬 Test Blind Spots (Pass 1 & 2 — 97 Regression Tests)


> **383 tests, 0 failures.** Two independent audit passes eliminated 28 test blind spots, fixed 2 source bugs, resolved a silent pytest-asyncio misconfiguration, and restructured the test suite into 10 thematic groups.

### 🔬 Two Audit Passes, 97 New Regression Tests

#### Pass 1 — Security, Middleware & Validation (59 tests)

| Area | What was covered |
|------|-----------------|
| Security | `scope_validator` enforcement; AND vs OR multi-scheme semantics; RFC 7230 case-insensitive API key headers (5 variants) |
| Middleware | `before`/`after` hook pairing on failure — `after[0]` runs even if `before[1]` raises |
| Validation | Empty-kwargs + required schema raises `ProdMCPValidationError`; JSON Schema `array`, scalar, and `enum` types |
| Schema | `resolve_schema` returns isolated copy; `generate_security_spec()` is idempotent |
| Spec | `@app.common()` security shorthand registers scheme at finalization |

#### Pass 2 — Bridge, URI Routing & Edge Cases (38 tests)

| Area | What was covered |
|------|-----------------|
| Validation | Pydantic coercion (`"3"` → `int`) verified end-to-end; `BaseModel` return → `dict` serialization |
| Bridge | `__security_context__` not injected when `security=None`; dict schema without `properties` still creates route |
| URI Routing | **Parameterized resource URIs** (`data://{item_id}`) — entire feature was untested; now fully covered |
| Schema | `resolve_schema(dict)` returns deep copy (P2-11 fix); spec export cannot corrupt stored schemas |
| Contracts | Duplicate tool name = last-writer-wins; empty app has no `components` key |
| Validation | Non-strict output swallow path exercised with actually-invalid outputs |

### 🐛 Source Bug Fixes

**`schemas.py` — Missing deepcopy for raw dict schemas**

`resolve_schema(dict)` returned the original dict reference. OpenMCP spec generation (`_rewrite_refs`) would mutate it, potentially corrupting the schema stored in `tool_meta["input_schema"]`. Now returns `deepcopy(schema)`.

**`fastapi.py` — Custom exception handlers were silently bypassed**

`_execute_wrapped` used a broad `except Exception` that re-wrapped every tool error as `HTTPException(500)`, making `app.add_exception_handler(ValueError, my_handler)` completely ineffective for tool errors. Now uses typed `except ProdMCPSecurityError / ProdMCPValidationError / HTTPException` — other exceptions propagate naturally to FastAPI's handler chain.

```python
# Now works as expected:
app.add_exception_handler(ValueError, my_handler)  # → 400 when tool raises ValueError
```

### 🗂️ Test Suite Restructured

Tests moved from a flat directory into 10 thematic subfolders. A `tests/tests.md` reference document describes every file and test class.

```
tests/
├── core/        ├── validation/   ├── security/    ├── middleware/
├── bridge/      ├── spec/         ├── transport/   ├── compat/
├── regression/  └── integration/
```

### 🔧 pytest-asyncio Misconfiguration Fixed

`pytest-asyncio` was listed in `pyproject.toml` dev dependencies but not installed, silently disabling 13 async tests. Install with:

```bash
pip install -e ".[dev,rest]"
```

---

## Version 0.3.0 — Unified Framework Release


> **One framework. Both worlds.** ProdMCP 0.3.0 makes `ProdMCP` a true drop-in replacement for FastAPI *and* FastMCP — write a handler once and expose it as a REST endpoint and an MCP tool simultaneously.

### 🏗️ Unified Architecture

ProdMCP now accepts both **FastAPI-style** and **FastMCP-style** decorators on a single class:

```python
from prodmcp import ProdMCP

app = ProdMCP("MyServer", version="1.0.0")

# Same handler → REST endpoint AND MCP tool
@app.common(input_schema=UserInput, output_schema=UserOutput)
@app.tool(name="get_user")
@app.get("/users/{user_id}")
def get_user(user_id: str) -> dict:
    return {"name": "Alice", "email": "alice@example.com"}

app.run()  # REST at / + MCP SSE at /mcp/sse
```

### 🔌 Decorator Stacking with `@app.common()`

The new `@app.common()` decorator defines cross-cutting concerns (schemas, security, middleware, tags) once for all stacked decorators — eliminating duplication between your MCP and REST definitions.

### 🌐 HTTP Method Decorators

Full FastAPI-identical surface:

- `@app.get()`, `@app.post()`, `@app.put()`, `@app.delete()`, `@app.patch()`
- All support `response_model`, `status_code`, `tags`, `summary`, `deprecated`, `operation_id`

### 🚀 Unified Server Mode

`app.run()` now defaults to `transport="unified"` — a single HTTP server serving:

- **REST API** at `/` (Swagger UI at `/docs`)
- **MCP SSE** at `/mcp/sse`
- Pure MCP: `app.run(transport="stdio")` or `app.run(transport="sse")`

### 🔒 Expanded Security Schemes

New first-class security primitives aligned with OpenAPI 3.1:

| Scheme | Class |
|--------|-------|
| HTTP Bearer | `HTTPBearer` |
| HTTP Basic | `HTTPBasicAuth` |
| HTTP Digest | `HTTPDigestAuth` |
| API Key (header) | `APIKeyHeader` |
| API Key (query) | `APIKeyQuery` |
| API Key (cookie) | `APIKeyCookie` |
| OAuth2 Password | `OAuth2PasswordBearer` |
| OAuth2 Auth Code | `OAuth2AuthorizationCodeBearer` |
| OAuth2 Client Credentials | `OAuth2ClientCredentialsBearer` |
| OpenID Connect | `OpenIdConnect` |

### 📦 Migration Guides & Examples

- `examples/fastapi_migration.py` — Step-by-step for FastAPI users
- `examples/fastmcp_migration.py` — Step-by-step for FastMCP users
- `examples/unified_example.py` — Showcase of the unified architecture

### 🐛 Bug Fixes

- Fixed `$ref` paths in OpenMCP spec for nested Pydantic models
- Proper security config propagation via `Depends(SecurityScheme)`
- Auto-generated unique names for multiple API key schemes

### 📋 Install

```bash
pip install prodmcp              # Core (MCP only)
pip install prodmcp[rest]        # + FastAPI + Uvicorn for unified server
```

---

## Version 0.2.0 — Initial Public API Release

This release brings the full production-ready capability of ProdMCP, featuring:

- **Decorator API**: Elegantly define tools, prompts, and resources using `@app.tool()`, `@app.prompt()`, and `@app.resource()`.
- **Schema-First Validation**: Native integration with Pydantic (`BaseModel`) allowing inputs/outputs validation to be rigorously enforced via `strict_output` toggle.
- **Advanced Security Manager**: Includes native `BearerAuth`, `ApiKeyAuth`, and `CustomAuth` schemes. Features shorthand inline security definitions (e.g. `{"type": "bearer", "scopes": ["admin"]}`).
- **Dependency Injection**: First-class `Depends()` support, mimicking FastAPI, enabling asynchronous resolution of context (Headers, Request parameters) into tool arguments automatically.
- **Middleware Hooks**: Global and entity-specific lifecycle hooks (`before`, `after`) using `MiddlewareContext` for request logging, metrics, and granular control.
- **Network Transports**: Support for basic `stdio` execution and streamable HTTP endpoints using Server-Sent Events (`sse`).
- **OpenMCP Specification Engine**: Auto-generates native OpenSpec definitions to define endpoints programmatically (`app.export_openmcp()`).
- **REST Bridge**: Instantly convert an MCP setup into a fully documented FastAPI router endpoint (`app.as_fastapi()`).

**Documentation Improvements:**
- Added robust examples covering SSE Server capabilities (`examples/sse_example.py`).
- Integrated end-to-end `SKILL.md` for AI agent consumption.
