# Changelog

All notable changes to ProdMCP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [0.3.9] — 2026-04-06

### 🐛 Critical Runtime Fix (Bug 9)

#### Fixed

- **`router.py` — FastMCP lifespan regression** (`Bug 9`): `create_unified_app()` constructed `FastAPI()` before calling `mcp_instance.http_app()`, so `lifespan=` was always `None`. FastMCP's `StreamableHTTPSessionManager` task group never initialized on startup — every MCP request raised `RuntimeError: Task group is not initialized. Make sure to use run()`. This is a regression of the original Bug 6 fix (applied in v0.3.4 as a site-package patch but never merged into the source). Fixed by building `mcp_asgi` first, extracting `mcp_asgi.lifespan`, and passing it to `FastAPI(lifespan=mcp_lifespan)`. The duplicate mcp_asgi construction block in the mount step is removed; the single `mcp_asgi` built in Step 1 is reused for both lifespan wiring and mounting.

---

## [0.3.5] — 2026-04-06

### 🐛 Critical Security & DI Bug Fixes (Bugs 3, 4, 5)

#### Fixed

- **`app.py` — `fastapi.Depends` silently ignored** (`Bug 3`): `_build_handler()` used `isinstance(param.default, Depends)` which only matched ProdMCP's own `Depends` class. Users importing `from fastapi import Depends` (the natural instinct for a FastAPI drop-in) would have their dependencies unresolved — security chains, rate-limiters, and audit-loggers silently no-op'd. Fixed with a duck-type check on `.dependency` callable attribute, matching both implementations. Applied in `_build_handler()`, `resolve_dependencies()`, and `_call_dependency()`.

- **`router.py` — `@app.common(security=...)` not applied to REST routes** (`Bug 4`): Decorators execute bottom-up, so `@app.common()` fires and writes `fn.__prodmcp_common__` *before* `@app.get/@app.post` writes the registry entry with `security=None`. `_add_api_route()` read only from the registry and never inspected `__prodmcp_common__`, leaving every HTTP REST route **completely unauthenticated** when security was declared via `@app.common()`. The matching MCP tool version was correctly secured — the asymmetry was invisible. Fixed by reading `handler_fn.__prodmcp_common__` lazily at `create_unified_app()` time, mirroring what `_finalize_pending()` does for MCP tools.

- **`dependencies.py` — `_call_dependency` only injected params named `"context"`** (`Bug 5`): Any FastAPI-idiomatic dependency using `credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())` would receive `None` for `credentials` — the entire Bearer token auth chain silently produced `None` then crashed with `AttributeError: 'NoneType'.credentials`. Fixed with a four-rule injection hierarchy: (1) duck-typed `Depends` recursion, (2) `context`-named or `dict`-annotated params get the full context, (3) `credentials`/`authorization`-named params or `HTTPAuthorizationCredentials`-annotated params get a synthesised credentials object parsed from the `Authorization` header, (4) params matching a top-level context key receive it directly.

#### Other

- **`README.md`** — Replaced failing FOSSA dynamic badge (live endpoint returning error image) with a static shields.io badge. Updated PyPI badge to v0.3.5.

---

## [0.3.4] — 2026-04-06

### 🧪 Test Suite Hardening, Zero-Blind-Spot Coverage & Deep Runtime Hardening

Major quality initiative combining three independent audit passes — eliminating 28 test blind spots and 17 source bugs found across five complete code-review passes of every module.

#### Bug Fixes — Pass 5 & 6 (D/E-series, 17 bugs)

- **`middleware.py` — Phase 2 pairing invariant** (`D1`): `build_middleware_chain`'s handler-failure cleanup loop did not wrap `after()` calls in `try/except`. If any `after()` raised, subsequent middlewares' `after()` hooks were skipped. B4 fixed Phase 3 (success path) but Phase 2 was missed.
- **`app.py` — `inspect.signature` hot path** (`D2`): `_wrap_with_security` called `inspect.signature(handler)` on every request to check for `__security_context__`. Now pre-computed once at closure-creation time.
- **`middleware.py` — `wrapped(*args)` calling convention** (`D4`): `wrapped(**kwargs)` rejected positional arguments despite `__signature__` advertising them. Now `wrapped(*args, **kwargs)`.
- **`app.py` — O(n²) `_finalize_pending`** (`D5`): `list.pop(0)` (O(n) per call) replaced with snapshot + clear (O(n) total).
- **`app.py` — Duplicate API route warning** (`D6`): Stacking two `@app.get(path)` on the same path silently overwrote the first handler. Now emits `UserWarning` (matching B12 for resources).
- **`__init__.py` — Stale `__version__`** (`D7`): Hardcoded `"0.3.0"` not updated when pyproject.toml was bumped. Now uses `importlib.metadata.version("prodmcp")` with fallback.
- **`app.py` — Prompt double middleware wrapping** (`D8`): `_register_prompt` never stored the pre-built handler in the registry. `_add_prompt_route` called `_build_handler()` again, doubling the middleware chain. Now stores and reuses `"wrapped"` key (mirrors B2 for tools).
- **`app.py` — Bearer scope merging** (`D9`): Shorthand `{"type": "bearer"}` auto-registration kept only the first tool's scopes. Later tools' scopes were silently dropped from `components.securitySchemes`. Now merges scopes across all tools sharing `bearerAuth`.
- **`middleware.py` — Dead `execute_before/execute_after`** (`D10`): Both methods were unreachable by the runtime and lacked the pairing invariant. Now emit `DeprecationWarning`.
- **`fastapi.py` — `ImportError` too broad** (`E1`): `except ImportError` caught sub-import failures inside installed packages and reported them as "FastAPI not installed". Narrowed to `except ModuleNotFoundError`.
- **`fastapi.py` — Prompt route double wrapping** (`E2`): `_add_prompt_route` always called `app._build_handler()` on the raw function. Fixed by reusing `meta["wrapped"]`.
- **`fastapi.py` — Array body crash in prompt routes** (`E3`): `dict(body)` in `_add_prompt_route.dict_route_handler` raised `TypeError` on JSON array bodies. Same B8 pattern applied to tool routes but missed here. Now returns HTTP 422.
- **`fastapi.py` — Resource route swallows all errors as 404** (`E4`): Outer `try/except Exception → 404` wrapped the entire `resource_route_handler`, converting registry errors and handler crashes to wrong-status 404s. Now only the FastMCP fallback call is 404-protected.
- **`validation.py` — Output validation truthiness** (`E5`): `if output_schema:` in both async and sync paths skipped validation for falsy schemas like `{}`. Now uses `if output_schema is not None:`, matching the Bug-F fix on input validation.
- **`security/__init__.py` — `Depends` re-exported from security** (`E6`): `Depends` is a DI primitive, not a security primitive. Removed from `prodmcp.security`; import from `prodmcp` or `prodmcp.dependencies` instead.
- **`pyproject.toml` — `anyio` missing from `[dev]`** (`E7`): Async tests silently depended on `fastmcp`'s transitive `anyio` install. Now explicitly declared.

#### Breaking Changes

- `from prodmcp.security import Depends` now raises `ImportError`. Use `from prodmcp import Depends` instead.

Major test quality initiative across two independent audit passes, eliminating 28 distinct test blind spots — cases where the test suite was either tautological, missed entire code paths, or accepted incorrect behavior through overly permissive assertions.

#### Bug Fixes (Source Code)

- **`schemas.py` — `resolve_schema(dict)` deep copy** (`P2-11`): raw dict schemas now return `deepcopy(schema)` instead of the original reference. Previously, spec generation (`_rewrite_refs`) could silently mutate a tool's stored `input_schema` through the shared reference.
- **`fastapi.py` — Exception propagation to FastAPI handlers** (`P2-10`): `_execute_wrapped` (tool and prompt routes) converted from a broad `except Exception` catch to typed `except ProdMCPSecurityError / ProdMCPValidationError / HTTPException` clauses. Non-ProdMCP exceptions (e.g. `ValueError`) now propagate to FastAPI's custom exception handler chain — `app.add_exception_handler(ValueError, ...)` is now effective for tool errors.

#### Regression Tests Added

- **`tests/regression/test_regression_pass1.py`** (59 tests — Audit Pass 1): security scope validation, AND/OR semantics, RFC 7230 case-insensitive API key headers, middleware before/after pairing on failure, empty-kwargs validation, JSON Schema array/scalar/enum types, `resolve_schema` isolation, multiline docstring handling, `@app.common()` security shorthand, spec generation idempotency.
- **`tests/regression/test_regression_pass2.py`** (38 tests — Audit Pass 2): Pydantic input coercion verified end-to-end, `BaseModel` output serialized to dict, `__security_context__` injection guard, dict schema without `properties` routable, parameterized URI resource routing (`data://{item_id}`), `_match_uri_template` multi-var and slash edge cases, `resolve_schema` raw dict isolation, duplicate tool name contract, empty app spec cleanliness, non-strict output swallow path.

#### Test Assertion Tightening (Existing Tests)

- `test_mcp_bridge.py` — prompt response now asserts exact content (`== "Summary: hello world"`) instead of substring prefix.
- `test_mcp_bridge.py` — `as_fastapi()` backward-compat check uses `isinstance(fa, FastAPI)` instead of `type(x).__name__` string comparison.
- `test_run_method.py` — SSE middleware forwarding test now verifies exhaustive keyword set `{"transport","host","port","middleware"}` instead of spot-checking two keys.
- `test_fastapi.py` — exception handler test now asserts `status == 400` and exact body content instead of `status in (400, 500)`.
- `test_schemas.py` — `test_dict_passthrough` updated to assert `result == raw and result is not raw` (copy semantics), replacing the identity check `result is raw` that encoded the bug.

#### pytest-asyncio Resolved

- `pytest-asyncio` was declared in `[project.optional-dependencies] dev` but never installed in the active environment, silently disabling 13 async tests (`test_fastapi.py`, `test_middleware.py`, `test_validation.py`). Resolved — `asyncio_mode = "auto"` now activates correctly.

#### Test Suite Restructured

Tests reorganised from a flat directory into 10 thematic subfolders with `__init__.py` and a `tests/tests.md` reference document:

```
tests/
├── core/          constructors, decorators, stacking, deferred registration, edge cases
├── validation/    schema resolution, validation engine
├── security/      security schemes and manager
├── middleware/    middleware chain and hooks
├── bridge/        FastAPI bridge, MCP bridge, HTTP methods, unified router
├── spec/          OpenMCP spec generation
├── transport/     run() and transport selection
├── compat/        FastMCP/FastAPI migration compatibility
├── regression/    blind-spot regression suites (2 passes, 97 tests)
└── integration/   end-to-end multi-component tests
```

**Total: 383 tests, 0 failures.**

---

## [0.3.3] — 2026-04-03

### ✅ Code Quality & Cache Cleanup
- **🧹 Cleanup**: Removed SonarCloud `.scannerwork/` cache artifacts that were inadvertently committed to the repository source.
- **✨ Formatting**: Applied global `ruff` autoformatting and standard lint repairs.

---
## [0.3.1] — 2026-04-03

### ✅ Enterprise Compliance & Security
- **FOSSA Integration**: Added FOSSA `.fossa.yml` pipeline scanning for License policy compliance and security vulnerability monitoring.
- **SonarCloud Integration**: Setup native Github Actions for SonarQube/SonarCloud.
- **CodeQL (SAST)**: Added GitHub advanced security static analysis workflow.
- **Security Dependency Bumps**: Enforced `fastmcp>=3.2.0`, `fastapi>=0.109.1`, and `pydantic>=2.10.0` to resolve CVSS high/medium vulnerabilities.
- **Refactor (Maintainability)**: Resolved 24 SonarCloud Python Code Smells (variable naming, unused local variables, nested blocks). Resulting in a perfect 'A' maintainability grade and 83.9% Test Coverage.

---
## [0.3.0] — 2026-04-01

### ✨ Highlights

ProdMCP 0.3.0 is the **Unified Framework** release — a single `ProdMCP` instance now serves as a drop-in replacement for *both* FastAPI and FastMCP.  
Write one handler, expose it as a REST endpoint *and* an MCP tool simultaneously, with shared validation, security, and middleware.

### Added

- **Unified Architecture** — `ProdMCP` now accepts both FastAPI-style (`@app.get()`, `@app.post()`, etc.) and FastMCP-style (`@app.tool()`, `@app.prompt()`, `@app.resource()`) decorators on the same class.
- **Decorator Stacking** — Stack `@app.tool()` + `@app.get()` (or any HTTP method) on a single handler function. Both the MCP tool and the REST route share the same implementation.
- **`@app.common()` Decorator** — New cross-cutting concerns decorator that lets you define `input_schema`, `output_schema`, `security`, `middleware`, and `tags` once, shared across all stacked decorators.
- **Deferred Registration** — MCP registrations (`@app.tool`, `@app.prompt`, `@app.resource`) are now deferred until `run()`, `export_openmcp()`, or `test_mcp_as_fastapi()` to ensure `@app.common()` metadata is available.
- **Unified Server Mode** — `app.run()` defaults to `transport="unified"`, serving REST routes at `/` and MCP SSE at `/mcp/sse` on a single HTTP server.
- **HTTP Method Decorators** — Full FastAPI-identical decorator surface: `@app.get()`, `@app.post()`, `@app.put()`, `@app.delete()`, `@app.patch()` with `response_model`, `status_code`, `tags`, `summary`, `deprecated`, `operation_id`, and more.
- **Unified Router** (`src/prodmcp/router.py`) — New module that builds a single Starlette/ASGI app serving both REST API routes and the MCP SSE endpoint.
- **FastAPI Constructor Compatibility** — `ProdMCP()` now accepts both `ProdMCP("name")` (FastMCP-style) and `ProdMCP(title="name")` (FastAPI-style).
- **`mcp_path` Parameter** — Configure the sub-path where MCP SSE is mounted (default `/mcp`).
- **`list_api_routes()`** — New introspection method to list all registered REST API routes.
- **`HTTPException` Re-export** — `from prodmcp import HTTPException` now works for FastAPI migration compatibility, with a built-in fallback if FastAPI is not installed.
- **Expanded Security Schemes**:
  - `HTTPBasicAuth` — Basic HTTP authentication.
  - `HTTPDigestAuth` — Digest HTTP authentication.
  - `APIKeyHeader`, `APIKeyQuery`, `APIKeyCookie` — Fine-grained API key placement.
  - `OAuth2PasswordBearer` — OAuth2 Password flow.
  - `OAuth2AuthorizationCodeBearer` — OAuth2 Authorization Code flow.
  - `OAuth2ClientCredentialsBearer` — OAuth2 Client Credentials flow.
  - `OpenIdConnect` — OpenID Connect authentication.
- **Security Package Restructure** — Security module refactored from a single file into a `security/` package with dedicated modules: `base.py`, `http.py`, `api_key.py`, `oauth2.py`, `open_id.py`.
- **`$ref` Rewriting in OpenMCP Spec** — Pydantic v2 `$defs` references are now correctly rewritten to `#/components/schemas/` in the generated OpenMCP specification.
- **New Examples**:
  - `examples/unified_example.py` — Demonstrates the unified REST + MCP architecture.
  - `examples/fastapi_migration.py` — Step-by-step FastAPI migration guide.
  - `examples/fastmcp_migration.py` — Step-by-step FastMCP migration guide.
- **New Test Suites**: `test_common_decorator.py`, `test_constructor.py`, `test_deferred_registration.py`, `test_edge_cases.py`, `test_http_methods.py`, `test_imports.py`, `test_mcp_bridge.py`, `test_migration_compat.py`, `test_run_method.py`, `test_stacking.py`, `test_unified_router.py`.

### Changed

- **`app.run()` Signature** — Now accepts `host`, `port`, and `transport` keyword arguments. Default transport changed from plain FastMCP delegation to `"unified"` (REST + MCP).
- **`as_fastapi()` Renamed** — Renamed to `test_mcp_as_fastapi()` to clarify it is for testing MCP handlers via HTTP, not for production REST serving (which uses `@app.get()` etc.). `as_fastapi` remains as a backward-compatible alias.
- **Description Updated** — Package description now reads "Unified production framework for both REST APIs and MCP servers" reflecting the expanded scope.
- **`export_openmcp()` / `export_openmcp_json()`** — Now call `_finalize_pending()` before generating the spec to ensure deferred registrations are processed.
- **Introspection Methods** — `list_tools()`, `list_prompts()`, `list_resources()`, `get_tool_meta()`, `get_prompt_meta()`, `get_resource_meta()` now call `_finalize_pending()`.
- **All Examples Updated** — Existing examples updated to showcase v0.3.0 stacking patterns and unified mode.

### Fixed

- **Schema `$ref` Paths** — Nested Pydantic model references in OpenMCP specs now correctly point to `#/components/schemas/` instead of `#/$defs/`.
- **Security Config Propagation** — Security configuration from `Depends(SecurityScheme)` is now correctly propagated to the registry metadata via `__security_config__` attribute.
- **Auto-generated Security Scheme Names** — API key security schemes now receive unique auto-generated names (e.g., `apiKeyAuth_header_X-API-Key`) to avoid collisions when multiple schemes are used.

### Dependencies

- **New optional dependency group**: `pip install prodmcp[rest]` installs `fastapi>=0.100.0` and `uvicorn[standard]>=0.22.0` for the unified server and REST features.

---

## [0.2.0] — 2026-03-28

### ✨ Highlights

Initial public API release of ProdMCP — a FastAPI-like production layer on top of FastMCP.

### Added

- **Decorator API** — `@app.tool()`, `@app.prompt()`, `@app.resource()` with schema, security, and middleware support.
- **Schema-First Validation** — Native Pydantic `BaseModel` integration for input/output validation with `strict_output` toggle.
- **Advanced Security Manager** — `BearerAuth`, `ApiKeyAuth`, `CustomAuth` schemes with shorthand inline definitions.
- **Dependency Injection** — `Depends()` support for async resolution of context into tool arguments.
- **Middleware Hooks** — Global and entity-specific `before`/`after` lifecycle hooks via `MiddlewareContext`.
- **Network Transports** — `stdio` and SSE transport support.
- **OpenMCP Specification Engine** — `app.export_openmcp()` generates machine-readable specs.
- **REST Bridge** — `app.as_fastapi()` converts MCP setup into a FastAPI router.
- **SKILL.md** — End-to-end skill file for AI agent consumption.
- **SSE Example** — `examples/sse_example.py` demonstrating streamable HTTP MCP.

---

## [0.1.0] — 2026-03-25

### Added

- Initial internal release with core ProdMCP class, validation engine, and security framework.
