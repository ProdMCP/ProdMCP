---
name: prodmcp_usage
description: End-to-end instructions for creating Model Context Protocol (MCP) servers using the ProdMCP Python package, including tools, prompts, resources, security, middleware, dependency injection, and generating OpenMCP specifications.
---

# Using ProdMCP

ProdMCP is a production-grade framework built on top of [FastMCP](https://github.com/fastmcp/fastmcp). It provides a FastAPI-like developer experience tailored for the Model Context Protocol (MCP), offering schema-first design, input/output validation, robust security, middleware hooks, dependency injection, and automatic OpenMCP specification generation.

When interacting with a codebase using ProdMCP, follow these comprehensive instructions to build or maintain MCP servers.

---

## 1. Installation & Initialization

You can install ProdMCP securely via `pip`. To expose the application as a FastAPI REST application or run the SSE Server, you must install the `[rest]` extra.

```bash
# Basic installation
pip install prodmcp

# With REST API and SSE support
pip install prodmcp[rest]
```

### Initializing the App
```python
from prodmcp import ProdMCP

app = ProdMCP(
    name="MyServer", 
    version="1.0.0", 
    description="A robust MCP server built with ProdMCP.",
    strict_output=True # If True (default), output validation errors explicitly raise Exceptions. If False, they log warnings.
)
```

---

## 2. Defining Schemas and Validation

ProdMCP strictly relies on **Pydantic** (`BaseModel`) or raw JSON Schema dictionaries for data validation mapping. It wraps handlers to ensure inputs and outputs conform perfectly to schema definitions.

If validation fails, it raises `ProdMCPValidationError`.

```python
from pydantic import BaseModel

class UserInput(BaseModel):
    user_id: str

class UserOutput(BaseModel):
    name: str
    email: str
    role: str = "member"
```

---

## 3. Creating MCP Entities

ProdMCP groups standard MCP capabilities into Decorator APIs (`@app.tool`, `@app.prompt`, `@app.resource`). 

### Tools
Tools are actionable handlers invoked by an MCP client. They enforce inputs, outputs, security, and middleware.
```python
@app.tool(
    name="get_user",
    description="Fetch a user's details by their ID.",
    input_schema=UserInput,
    output_schema=UserOutput,
    tags={"users", "read"}
)
def get_user(user_id: str) -> dict:
    """The input parameter 'user_id' is destructured automatically."""
    # Data is automatically validated against UserOutput
    return {"name": "Alice", "email": f"alice_{user_id}@example.com"}
```
*(Async functions `async def` are fully supported for all entities).*

### Prompts
Prompts return conversational templates to the MCP client.
```python
@app.prompt(
    name="explain_topic",
    description="Generate a detailed prompt asking to explain a specific topic.",
    input_schema=UserInput,
)
def explain_topic(user_id: str) -> str:
    return f"Explain the system constraints for user {user_id}."
```

### Resources
Resources provide identifiable data URIs that the client can read.
```python
@app.resource(
    uri="data://users/all",
    name="user_database",
    output_schema=UserOutput,     # Validates the returned items
    mime_type="application/json"  # Optional metadata
)
def fetch_users() -> list:
    return [{"name": "Alice", "email": "alice@example.com"}]
```

---

## 4. Security & Authentication

ProdMCP features a dedicated `SecurityManager` mimicking OpenAPI's robust security schemes. Authentication requirements map directly to OpenMCP exports.

If security checks fail, a `ProdMCPSecurityError` is raised.

### Registering Security Schemes
You can name and register schemes globally:
```python
from prodmcp import BearerAuth, ApiKeyAuth, CustomAuth

app.add_security_scheme("bearerAuth", BearerAuth(scopes=["admin", "user"]))

# API Keys can be located in 'header', 'query', or 'cookie'
app.add_security_scheme("apiKeyAuth", ApiKeyAuth(key_name="X-API-Key", location="header"))

# Custom Auth function
def my_auth_extractor(context: dict) -> 'prodmcp.security.SecurityContext':
    token = context.get("headers", {}).get("Authorization")
    if token != "my-secret":
        raise Exception("Invalid token")
    from prodmcp.security import SecurityContext
    return SecurityContext(token=token, scopes=["user"])

app.add_security_scheme("customAuth", CustomAuth(extractor=my_auth_extractor))
```

### Applying Security Requirements
Pass a list of standard dictionaries to the `security` parameter. The lists act as a logical **OR** (requiring at least one match). Inside each dict, multiple keys act as a logical **AND**.
```python
@app.tool(
    name="delete_user",
    input_schema=UserInput,
    # Requires either Admin Bearer Token OR a valid API Key
    security=[
        {"bearerAuth": ["admin"]},
        {"apiKeyAuth": []}
    ]
)
def delete_user(user_id: str) -> dict:
    return {"status": "success"}
```

You can also use quick **shorthand configurations** without naming schemes:
```python
@app.tool(
    name="get_secure_data",
    security=[{"type": "bearer", "scopes": ["read"]}]
    # Also supports: {"type": "apikey", "key_name": "API-KEY", "in": "header"}
)
def get_secure_data() -> dict:
    return {"data": "secret"}
```

---

## 5. Dependency Injection

ProdMCP supports FastAPI-like dependency injection using `Depends()`. Dependencies are evaluated per-request and can be cached. They automatically receive the request `context` if they define a parameter named `context`.

```python
from prodmcp import Depends

async def get_current_user(context: dict) -> dict:
    # `context` contains HTTP headers, query parameters, metadata etc.
    token = context.get('headers', {}).get('authorization')
    return {"user_id": "123", "role": "admin", "token": token}

@app.tool(
    name="my_secure_tool",
    security=[{"bearerAuth": []}]
)
# `Depends` automatically resolves the user payload before invoking the tool
async def my_secure_tool(user_payload: dict = Depends(get_current_user)):
    return {"handled_for": user_payload["user_id"]}
```

---

## 6. Middleware

Middleware taps into the execution lifecycle via `before` and `after` asynchronous hooks. Standard use cases include request tracing, metrics, and rate limiting. 

```python
from prodmcp import Middleware, MiddlewareContext
import time

class ResponseLogger(Middleware):
    async def before(self, context: MiddlewareContext) -> None:
        # Context comes with: entity_type ('tool', 'prompt'), entity_name, and metadata
        context.metadata["start_time"] = time.time()

    async def after(self, context: MiddlewareContext) -> None:
        duration = time.time() - context.metadata["start_time"]
        print(f"[{context.entity_type}:{context.entity_name}] took {duration:.4f}s")
```

**Register Middleware:**
```python
# Apply globally to everything
app.add_middleware(ResponseLogger())

from prodmcp import LoggingMiddleware
app.add_middleware(LoggingMiddleware(), name="standard_logger")

# Apply explicitly to a specific tool via its assigned name or instance
@app.tool(
    name="slow_task",
    middleware=["standard_logger", ResponseLogger()]
)
def slow_task() -> str:
    return "Done"
```

---

## 7. Running the Server

ProdMCP abstracts application network protocols by delegating to `FastMCP`.

**Standard I/O (Default MCP Mode)**
Commonly used for local terminal and LLM app ingestion plugins.
```python
if __name__ == "__main__":
    app.run() # Defaults to transport="stdio"
```

**Streamable HTTP (SSE Transport)** 
If connecting across a web network, FastMCP uses Server-Sent Events (SSE). Requires `starlette` and `uvicorn`.
```python
if __name__ == "__main__":
    app.run(transport="sse", host="0.0.0.0", port=8000)
    # The MCP Connect Endpoint for Web clients will be: http://localhost:8000/sse
```

**FastAPI Full Bridge Integration** 
ProdMCP comes directly with a bridge that compiles all MCP entities strictly to documented FastAPI REST routes (`/tools/...`, `/prompts/...`, `/resources/...`). 
```python
fastapi_app = app.test_mcp_as_fastapi() 
# Run via terminal: uvicorn my_file:fastapi_app --reload
```

---

## 8. OpenMCP Specification Generation

ProdMCP analyzes your codebase and auto-generates a machine-readable specification formatted using the OpenMCP (OpenAPI-like) pattern.

```python
# Export the entire specification as a native python dictionary
spec_dict = app.export_openmcp()

# Export specification as a formatted JSON String
json_spec = app.export_openmcp_json(indent=2)
print(json_spec)
```
