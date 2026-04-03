# Changelog

All notable changes to ProdMCP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
