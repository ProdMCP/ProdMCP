# ProdMCP

[![FOSSA Status](https://app.fossa.com/api/projects/custom%2B61520%2Fprodmcp.svg?type=shield&issueType=license)](https://app.fossa.com/projects/custom%2B61520%2Fprodmcp?ref=badge_shield&issueType=license)

> **Unified production framework for both REST APIs and MCP servers.** Drop-in replacement for FastAPI and FastMCP with schema validation, security, middleware, dependency injection, and OpenMCP spec generation.

## Installation

```bash
pip install prodmcp              # Core (MCP tools, prompts, resources)
pip install prodmcp[rest]        # + FastAPI + Uvicorn for the unified server
```

## Quick Start

```python
from pydantic import BaseModel
from prodmcp import ProdMCP

app = ProdMCP("MyServer", version="1.0.0")


# --- Define Schemas ---

class UserInput(BaseModel):
    user_id: str

class UserOutput(BaseModel):
    name: str
    email: str


# --- Unified: Same handler as both MCP tool AND REST endpoint ---

@app.common(input_schema=UserInput, output_schema=UserOutput)
@app.tool(name="get_user", security=[{"type": "bearer", "scopes": ["user"]}])
@app.get("/users/{user_id}")
def get_user(user_id: str) -> dict:
    return {"name": "Alice", "email": "alice@example.com"}


# --- MCP-only Prompt ---

@app.prompt(name="summarize", input_schema=UserInput)
def summarize(user_id: str) -> str:
    return f"Please summarize data for user {user_id}"


# --- MCP-only Resource ---

@app.resource(uri="data://users", name="user_db", output_schema=UserOutput)
def fetch_users() -> list:
    return [{"name": "Alice", "email": "alice@example.com"}]


# --- Export OpenMCP Spec ---

spec = app.export_openmcp()
print(spec)

# --- Run the unified server ---

if __name__ == "__main__":
    app.run()  # REST at / (Swagger at /docs) + MCP SSE at /mcp/sse
```

## Features

- **Unified Framework** — One `ProdMCP` instance replaces both FastAPI and FastMCP
- **Decorator Stacking** — `@app.tool()` + `@app.get()` on the same handler with `@app.common()` for shared config
- **HTTP Methods** — `@app.get()`, `@app.post()`, `@app.put()`, `@app.delete()`, `@app.patch()` (FastAPI-identical)
- **MCP Primitives** — `@app.tool()`, `@app.prompt()`, `@app.resource()` (FastMCP-identical)
- **Schema-First** — Pydantic models or raw JSON Schema for input/output definitions
- **Validation Engine** — Automatic input/output validation with structured error reporting
- **Security Layer** — Bearer, Basic, Digest, API keys, OAuth2, OpenID Connect
- **Middleware System** — Global before/after hooks (logging, rate limiting, tracing)
- **Dependency Injection** — Composable dependencies injected into handlers
- **OpenMCP Spec** — Auto-generated, machine-readable specification from code
- **Unified Server** — REST + MCP SSE on a single HTTP server (`app.run()`)

## License

MIT

---

## Release Notes

### Version 0.3.0 — Unified Framework Release

**One framework. Both worlds.** ProdMCP 0.3.0 makes `ProdMCP` a true drop-in replacement for FastAPI *and* FastMCP.

Key changes:

- **Unified Architecture** — FastAPI-style HTTP decorators + FastMCP-style MCP decorators on a single class
- **`@app.common()`** — Define schemas, security, and middleware once for stacked decorators
- **`app.run(transport="unified")`** — REST at `/` + MCP SSE at `/mcp/sse` on one server (new default)
- **Expanded Security** — `HTTPBasicAuth`, `HTTPDigestAuth`, `APIKeyHeader/Query/Cookie`, `OAuth2PasswordBearer`, `OAuth2AuthorizationCodeBearer`, `OAuth2ClientCredentialsBearer`, `OpenIdConnect`
- **Migration Examples** — `fastapi_migration.py`, `fastmcp_migration.py`, `unified_example.py`
- **Bug Fixes** — Fixed `$ref` paths in OpenMCP spec, security config propagation, and API key scheme naming

See [CHANGELOG.md](CHANGELOG.md) for the full changelog.

### Version 0.2.0 — Initial Public API Release

- **Decorator API**: `@app.tool()`, `@app.prompt()`, `@app.resource()` with schema, security, and middleware support.
- **Schema-First Validation**: Pydantic `BaseModel` input/output validation with `strict_output` toggle.
- **Security Manager**: `BearerAuth`, `ApiKeyAuth`, `CustomAuth` with shorthand inline definitions.
- **Dependency Injection**: `Depends()` for async context resolution.
- **Middleware Hooks**: Global and entity-specific `before`/`after` lifecycle hooks.
- **OpenMCP Spec Engine**: `app.export_openmcp()` generates machine-readable specs.
- **REST Bridge**: `app.as_fastapi()` for MCP-to-REST testing.
