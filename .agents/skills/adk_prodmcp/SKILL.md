---
name: adk_prodmcp_dev
description: Exhaustive guide for developing, testing, and securing Model Context Protocol (MCP) servers using ProdMCP and MCPcrunch within the Agent Development Kit (ADK).
---

# Comprehensive Guide to ProdMCP and MCPcrunch for ADK

This skills file provides an exhaustive, end-to-end reference for building production-grade MCP servers using **ProdMCP** and validating them using **MCPcrunch**. 

ProdMCP is a schema-driven framework that bridges FastAPI and FastMCP, providing an identical developer experience for both REST APIs and MCP tools. MCPcrunch is a comprehensive security auditing and conformance testing framework for OpenMCP specifications.

---

## 1. Defining APIs and MCP Entities

ProdMCP unifies the development of standard REST APIs and MCP entities (Tools, Prompts, Resources) under a single application instance.

### Initialization

```python
from prodmcp import ProdMCP, LoggingMiddleware

app = ProdMCP(
    name="MyAdvancedServer",
    version="1.0.0",
    description="A production-grade MCP server.",
    strict_output=True, # Validates output strictly against schemas
)
```

### Exhaustive List of Decorators

ProdMCP provides decorators that mirror both FastMCP (for MCP) and FastAPI (for HTTP REST).

#### MCP Decorators

1.  **`@app.tool`**: Defines an actionable tool that an LLM can invoke.
    *   **Parameters**: `name`, `description`, `input_schema`, `output_schema`, `security`, `middleware`, `tags`, `strict`
    *   **Usage**:
        ```python
        from pydantic import BaseModel

        class UserInput(BaseModel):
            user_id: str

        class UserOutput(BaseModel):
            name: str
            role: str

        @app.tool(
            name="get_user",
            description="Fetch user details.",
            input_schema=UserInput,
            output_schema=UserOutput,
            tags={"users"}
        )
        def get_user(user_id: str) -> dict:
            return {"name": "Alice", "role": "Admin"}
        ```

2.  **`@app.prompt`**: Defines a conversational template for the LLM.
    *   **Parameters**: `name`, `description`, `input_schema`, `output_schema`, `tags`
    *   **Usage**:
        ```python
        @app.prompt(
            name="review_code",
            description="Generate a prompt to review a code snippet.",
            input_schema=UserInput, # Reusing schema
        )
        def review_code(user_id: str) -> str:
            return f"Review the latest commits by user {user_id} for security flaws."
        ```

3.  **`@app.resource`**: Exposes readable data URIs to the LLM.
    *   **Parameters**: `uri`, `name`, `description`, `output_schema`, `tags`, `mime_type`
    *   **Usage**:
        ```python
        @app.resource(
            uri="data://users/{user_id}", # Supports URI templates
            name="user_profile",
            description="Read a user's raw profile data.",
            output_schema=UserOutput
        )
        def read_user_profile(user_id: str) -> dict:
            return {"name": "Alice", "role": "Admin"}
        ```

#### HTTP REST Decorators (FastAPI Identical)

ProdMCP allows you to expose standard HTTP methods. These are fully compatible with FastAPI's signature.

*   `@app.get(path, ...)`
*   `@app.post(path, ...)`
*   `@app.put(path, ...)`
*   `@app.delete(path, ...)`
*   `@app.patch(path, ...)`

**Parameters**: `response_model`, `status_code`, `tags`, `summary`, `description`, `dependencies`, `deprecated`, `operation_id`, `include_in_schema`, `response_class`, `responses`, `response_description`

#### Cross-Cutting Decorator

*   **`@app.common`**: Used to share configurations (schemas, security, middleware) when stacking decorators to expose the same handler via both MCP and REST.
    *   **Parameters**: `input_schema`, `output_schema` (or `response_model`), `security`, `middleware`, `tags`, `strict`
    *   **Usage**:
        ```python
        @app.common(
            output_schema=UserOutput,
            security=[{"bearerAuth": ["read_users"]}],
            middleware=["logging"]
        )
        @app.tool(name="fetch_user", description="Get user via MCP")
        @app.get("/users/{user_id}", tags=["Users"])
        def fetch_user(user_id: str) -> dict:
            return {"name": "Alice", "role": "Admin"}
        ```

---

## 2. Dependency Injection and Middleware

### Dependencies (`Depends`)
ProdMCP supports FastAPI-like dependency injection, crucial for resolving security contexts or database sessions before the handler executes.

```python
from prodmcp import Depends

async def extract_tenant(context: dict) -> str:
    # 'context' contains HTTP headers/query params injected by ProdMCP
    return context.get("headers", {}).get("x-tenant-id", "default")

@app.tool(name="get_tenant_data")
def get_tenant_data(tenant: str = Depends(extract_tenant)) -> dict:
    return {"data": f"Data for {tenant}"}
```

### Middleware
Middleware allows pre- and post-processing of requests (e.g., logging, metrics).

```python
from prodmcp import Middleware, MiddlewareContext

class MetricsMiddleware(Middleware):
    async def before(self, ctx: MiddlewareContext) -> None:
        print(f"Starting {ctx.entity_type} {ctx.entity_name}")
    
    async def after(self, ctx: MiddlewareContext) -> None:
        if ctx.error:
            print(f"Failed with {ctx.error}")

# Register globally
app.add_middleware(MetricsMiddleware())

# Register by name for selective use
app.add_middleware(MetricsMiddleware(), name="metrics")
```

---

*End of Part 1. Part 2 will cover the Manual Testing Bridge, Security, and MCPcrunch integration.*

## 3. Manual Testing Bridge (FastAPI Bridge)

ProdMCP includes a powerful testing bridge that automatically maps your MCP entities (Tools, Prompts, Resources) to standard FastAPI REST routes. This allows you to manually test your MCP capabilities using standard HTTP clients like `curl`, Postman, or Swagger UI, without needing an MCP client.

### Mapping
*   **Tools**: Mapped to `POST /tools/{name}`
*   **Prompts**: Mapped to `POST /prompts/{name}`
*   **Resources**: Mapped to `GET /resources/{uri}`

### Generating the Bridge App

```python
# Assuming 'app' is your ProdMCP instance
fastapi_app = app.test_mcp_as_fastapi()

# Run this script with Uvicorn:
# uvicorn my_app:fastapi_app --reload
```

### Manual Testing with the Bridge

Once running (e.g., at `http://localhost:8000`), you can test:

**Test a Tool:**
```bash
curl -X POST http://localhost:8000/tools/get_user \
     -H "Content-Type: application/json" \
     -d '{"user_id": "123"}'
```

**Test a Resource:**
```bash
curl -X GET http://localhost:8000/resources/data://users/123
```

**Swagger UI:**
Navigate to `http://localhost:8000/docs` in your browser. The bridge automatically generates complete OpenAPI documentation for all your MCP entities, including their Pydantic schemas, enabling interactive manual testing directly from the browser.

---

## 4. Security

ProdMCP features a dedicated `SecurityManager` that mimics OpenAPI's robust security schemes.

### Registering Security Schemes

```python
from prodmcp import BearerAuth, ApiKeyAuth

# Global registration
app.add_security_scheme("bearerAuth", BearerAuth(scopes=["admin", "user"]))
app.add_security_scheme("apiKeyAuth", ApiKeyAuth(key_name="X-API-Key", location="header"))
```

### Applying Security

Security is applied using the `security` parameter in decorators. It accepts a list of dictionaries representing logical **OR** combinations. Keys within a dictionary represent logical **AND**.

```python
@app.tool(
    name="delete_data",
    # Requires either Admin Bearer Token OR a valid API Key
    security=[
        {"bearerAuth": ["admin"]},
        {"apiKeyAuth": []}
    ]
)
def delete_data() -> dict:
    return {"status": "deleted"}
```

---

## 5. Testing MCP using MCPcrunch

**MCPcrunch** is the companion tool to ProdMCP, designed to audit and validate OpenMCP specifications and test live server conformance.

### Step 1: Export the OpenMCP Specification

First, use ProdMCP to auto-generate your OpenMCP specification.

```python
# In your server script
spec_json = app.export_openmcp_json(indent=2)
with open("spec.json", "w") as f:
    f.write(spec_json)
```

### Step 2: Security Audit (Static Analysis)

Run MCPcrunch to perform a deterministic audit against your `spec.json`. This checks for security flaws, missing documentation, and schema violations.

```bash
# Basic Audit
mcpcrunch spec.json

# Audit with LLM semantic analysis (checks for prompt injection, etc.)
mcpcrunch spec.json --llm gemini --api-key $GEMINI_API_KEY
```
MCPcrunch provides a partitioned score out of 100 (Security /30, Data Validation /70) and a component-wise breakdown, identifying exactly which tool/prompt is lowering your score.

### Step 3: Conformance Testing (Dynamic Analysis)

MCPcrunch can perform static and runtime conformance tests to ensure your MCP implementation adheres strictly to the protocol and handles errors correctly.

**Static Conformance Testing:**
Checks for `$ref` validity, schema strictness (`additionalProperties: false`), and property boundaries (`maxLength`, `maxItems`).

```bash
mcpcrunch conformance spec.json --static-only
```

**Runtime Conformance Testing:**
Connects to your running ProdMCP server via the testing bridge or live MCP SSE endpoint to verify actual runtime behaviour (e.g., ensuring 401 Unauthorized is returned when tokens are missing).

```bash
mcpcrunch conformance spec.json \
    --server-url http://localhost:8000/mcp \
    --bearer-token "your-test-token"
```

### Programmatic MCPcrunch Integration (Python API)

You can integrate MCPcrunch directly into your ADK testing pipelines using its Python API.

```python
import json
from mcpcrunch import MCPcrunch, ConformanceRunner

# Load the spec generated by ProdMCP
with open("spec.json") as f:
    spec = json.load(f)

# 1. Audit
crunch = MCPcrunch()
report = crunch.audit(spec)
print(f"Overall Audit Score: {report.deterministic.score}/100")

# 2. Conformance
runner = ConformanceRunner(spec_path="spec.json")
conf_report = runner.run_static()
print(f"Conformance Grade: {conf_report.summary.grade}")
```

### MCPcrunch Key Concepts
*   **OMCP-DOC Rules**: Flags missing descriptions on capabilities or responses.
*   **OMCP-SEC Rules**: Ensures security schemes are bound, API keys aren't in URLs, and proper HTTP error codes (401, 403, 406, 415, 429) are defined.
*   **Strictness**: Ensure `strict_output=True` is enabled in ProdMCP and all Pydantic models forbid extra properties to score high on MCPcrunch conformance.
