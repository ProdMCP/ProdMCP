# Release Notes

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
