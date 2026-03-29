# ProdMCP

> **FastAPI-like production layer on top of FastMCP** — schema-driven development, validation, security, middleware, and automatic OpenMCP specification generation.

## Installation

```bash
pip install prodmcp
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


# --- Define a Tool ---

@app.tool(
    name="get_user",
    input_schema=UserInput,
    output_schema=UserOutput,
    security=[{"type": "bearer", "scopes": ["user"]}],
)
def get_user(user_id: str) -> dict:
    return {"name": "Alice", "email": "alice@example.com"}


# --- Define a Prompt ---

@app.prompt(
    name="summarize",
    input_schema=UserInput,
)
def summarize(user_id: str) -> str:
    return f"Please summarize data for user {user_id}"


# --- Define a Resource ---

@app.resource(
    uri="data://users",
    name="user_db",
    output_schema=UserOutput,
)
def fetch_users() -> list:
    return [{"name": "Alice", "email": "alice@example.com"}]


# --- Export OpenMCP Spec ---

spec = app.export_openmcp()
print(spec)

# --- Run the server ---

if __name__ == "__main__":
    app.run()
```

## Features

- **Decorator API** — `@app.tool()`, `@app.prompt()`, `@app.resource()` with schema, security, and middleware support
- **Schema-First** — Pydantic models or raw JSON Schema for input/output definitions
- **Validation Engine** — Automatic input/output validation with structured error reporting
- **Security Layer** — Bearer tokens, API keys, custom auth providers
- **Middleware System** — Global before/after hooks (logging, rate limiting, tracing)
- **Dependency Injection** — Composable dependencies injected into handlers
- **OpenMCP Spec** — Auto-generated, machine-readable specification from code

## License

MIT

---

## Release Notes

### Version 0.2.0

**Initial Public API Release**

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
