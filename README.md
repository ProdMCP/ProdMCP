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
