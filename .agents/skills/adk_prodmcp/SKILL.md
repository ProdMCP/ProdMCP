---
name: prodmcp_mcpcrunch_usage
description: Comprehensive guide for Agent Development Kits (ADK) on how to build production-grade Model Context Protocol (MCP) servers using ProdMCP, including an exhaustive list of decorators, the REST manual testing bridge, and rigorous validation and testing with MCPcrunch (the 42Crunch for OpenMCP specs).
---

# Building and Testing MCP Servers with ProdMCP and MCPcrunch

This skills file provides an exhaustive, production-ready guide for building Model Context Protocol (MCP) servers using the `ProdMCP` framework and validating them securely and structurally using `MCPcrunch`. 

`ProdMCP` provides a schema-first, FastAPI-like development experience for building MCP tools, prompts, and resources. 
`MCPcrunch` is an advanced security auditing and conformance testing engine (similar to 42Crunch but built for the OpenMCP Specification) that scores your specification from 0-100 across Security and Data Validation pools.

---

## 1. Defining MCP Entities in ProdMCP (Exhaustive Decorator List)

ProdMCP provides three core decorator APIs to expose MCP capabilities. All entities enforce strong typing using Pydantic `BaseModel` classes or raw JSON schemas, which are automatically translated into the OpenMCP specification.

### 1.1 `@app.tool`
Tools are state-mutating or action-oriented handlers invoked by an MCP client. They enforce strict input/output validation, security bindings, and middleware.

```python
from pydantic import BaseModel, Field
from prodmcp import ProdMCP

app = ProdMCP(name="ExampleApp", version="1.0.0")

class CreateTaskInput(BaseModel):
    title: str = Field(..., min_length=3, max_length=120, description="Task title")
    priority: str = Field(..., pattern="^(high|medium|low)$")

class TaskOutput(BaseModel):
    task_id: str = Field(..., max_length=36)
    status: str = Field(..., max_length=20)

@app.tool(
    name="create_task",
    description="Creates a new task. Strict validation ensures the title and priority are correct.",
    input_schema=CreateTaskInput,
    output_schema=TaskOutput,
    security=[{"bearerAuth": []}], # Requires authentication
    tags={"tasks", "write"},
    middleware=["standard_logger"]
)
async def create_task(title: str, priority: str) -> dict:
    return {"task_id": "uuid-1234", "status": "created"}
```

### 1.2 `@app.prompt`
Prompts are read-only templates that guide Large Language Models (LLMs) on how to behave or format data. They also accept schemas for template variables.

```python
class TopicInput(BaseModel):
    topic: str = Field(..., max_length=200, description="Topic to summarize")

@app.prompt(
    name="summarize_topic",
    description="Generate a prompt asking the LLM to summarize a specific topic.",
    input_schema=TopicInput,
    security=[{"bearerAuth": []}]
)
def summarize_topic(topic: str) -> str:
    return f"Please summarize the topic: {topic}. Be concise and use bullet points."
```

### 1.3 `@app.resource`
Resources represent read-only, identifiable data URIs that the client can fetch, such as logs, database dumps, or files.

```python
class LogOutput(BaseModel):
    log_lines: list[str] = Field(..., max_items=1000)
    total_count: int = Field(..., ge=0)

@app.resource(
    uri="data://system/logs/recent",
    name="recent_system_logs",
    description="Fetches the 1000 most recent system logs.",
    output_schema=LogOutput,
    mime_type="application/json",
    security=[{"bearerAuth": ["admin"]}] # Requires 'admin' scope
)
async def get_recent_logs() -> dict:
    return {"log_lines": ["System booted", "User logged in"], "total_count": 2}
```

---

## 2. Security and Middleware

### Registering Security Schemes
Security schemes must be registered globally before they are referenced in the `@app.tool`, `@app.prompt`, or `@app.resource` decorators. This mapping is vital for OpenMCP compliance.

```python
from prodmcp import BearerAuth, ApiKeyAuth

app.add_security_scheme("bearerAuth", BearerAuth(scopes=["admin", "user"]))
app.add_security_scheme("apiKeyAuth", ApiKeyAuth(key_name="X-API-Key", location="header"))
```

### Dependency Injection
Dependencies run before the main handler and can resolve Context/Authentication payloads.

```python
from prodmcp import Depends

async def get_user_session(context: dict) -> dict:
    token = context.get('headers', {}).get('authorization')
    return {"user_id": "123", "role": "admin"}

@app.tool(
    name="delete_account",
    security=[{"bearerAuth": []}]
)
async def delete_account(session: dict = Depends(get_user_session)):
    return {"deleted": session["user_id"]}
```

---

## 3. The Manual Testing Bridge (FastAPI REST Bridge)

While MCP communicates over standard stdio or SSE transports, manual testing of these binary/stream protocols is difficult via `curl` or Postman. 

ProdMCP provides a **FastAPI Bridge** (`test_mcp_as_fastapi()`) that compiles all your MCP tools, prompts, and resources directly into a standard FastAPI REST application.

### Using the Bridge
```python
# Create the REST application bridge
fastapi_app = app.test_mcp_as_fastapi() 

# Run this file using uvicorn:
# uvicorn my_app:fastapi_app --reload --port 8000
```

### Bridge Routes Generated:
1. `POST /tools/create_task` -> Tests the tool execution with JSON body payloads.
2. `POST /prompts/summarize_topic` -> Tests template generation.
3. `GET /resources/recent_system_logs` -> Tests resource fetching.

This allows you to manually verify inputs, outputs, and validation rules using standard HTTP clients or the built-in Swagger UI at `http://localhost:8000/docs`.

---

## 4. MCPcrunch Validation & Conformance Testing

`MCPcrunch` is the security auditing and runtime conformance engine for OpenMCP specifications. It acts identically to 42Crunch but is tailored for the MCP domain.

To use MCPcrunch, you must first export your ProdMCP app to the OpenMCP spec format:

```python
import json
with open("spec.json", "w") as f:
    f.write(app.export_openmcp_json(indent=2))
```

### 4.1 Security Auditing (Static Analysis)

The Security Audit analyzes the `spec.json` statically, scoring it out of 100. The score is partitioned into two pools:
- **Security Pool (Max 30):** Penalized by `OMCP-SEC-*` violations.
- **Data Validation Pool (Max 70):** Penalized by Format (`FMT`), Data Quality (`DAT`), and Documentation (`DOC`) violations.

**Using the Python API for Auditing:**
```python
from mcpcrunch import MCPcrunch

crunch = MCPcrunch("schema.json") # The base OpenMCP Meta-schema
with open("spec.json") as f:
    spec = json.load(f)

report = crunch.audit(spec)
print(f"Overall Score: {report.overall_score}/100")
for issue in report.deterministic.issues:
    print(f"[{issue.severity.value}] {issue.rule_id}: {issue.message}")
```

### 4.2 Runtime Conformance Testing

Conformance testing involves dynamically calling the live MCP server using test cases derived via mutation testing on the OpenMCP schemas.

```python
from mcpcrunch import ConformanceRunner, AuthConfig

runner = ConformanceRunner(
    spec_path="spec.json",
    server_url="https://api.myapp.com/mcp",
    schema_path="schema.json",
    auth=AuthConfig(bearer_token="eyJhb...")
)

report = runner.run_all() # Runs static integrity + runtime tests
print(f"Pass Rate: {report.summary.pass_rate}")
```

---

## 5. Mitigating MCPcrunch Score Deductions

To achieve a perfect "Grade A" 100/100 score, your ProdMCP schemas and configuration must be airtight. Below are the primary deductions and how to fix them in ProdMCP.

### A. Format & Documentation Issues (Data Validation Pool)
- **`OMCP-FMT-006` (Name Collisions):** Ensure no two tools, prompts, or resources share the exact same `name`.
- **`OMCP-DOC-001` (Missing Descriptions):** Every tool, prompt, and resource MUST have a comprehensive `description`.
  *Fix:* `@app.tool(name="...", description="Detailed usage instructions...", ...)`
- **`OMCP-DOC-002` (Missing Response Descriptions):** Output properties must be described.
  *Fix:* Use Pydantic `Field(..., description="...")` inside your Output schemas.

### B. Data Quality Constraints (Data Validation Pool - Critical)
If inputs are unbounded, LLMs can perform resource exhaustion or injection attacks.
- **`OMCP-DAT-001` (Strict Objects):** Input schemas must reject unknown properties.
  *Fix:* Pydantic V2 handles this by default, but ensure no `Extra.allow` configs exist. MCPcrunch expects `additionalProperties: false`.
- **`OMCP-DAT-003` (String Boundaries):** Every string field MUST have a `maxLength` to prevent buffer/payload exhaustion.
  *Fix:* `name: str = Field(..., max_length=100)`
- **`OMCP-DAT-004` (Regex Patterns):** Sensitive identifiers (emails, UUIDs, IPs) MUST have strict regex patterns.
  *Fix:* `email: str = Field(..., pattern="^[\w\.-]+@[\w\.-]+\.\w+$")`
- **`OMCP-DAT-005` & `OMCP-DAT-006` (Array/Numeric Bounds):** Arrays need `maxItems`; integers need `minimum` and `maximum`.
  *Fix:* `tags: list[str] = Field(..., max_items=10)`, `age: int = Field(..., ge=0, le=120)`

### C. Security Posture (Security Pool)
- **`OMCP-SEC-001` (Dangling Security bindings):** If you apply `security=[{"bearerAuth": []}]`, you MUST have called `app.add_security_scheme("bearerAuth", ...)` globally.
- **`OMCP-SEC-003` (Auth Enforcement):** Tools executing sensitive actions must not have empty security arrays.
  *Fix:* ALWAYS apply `security=[...]` to modifying endpoints.
- **`OMCP-SEC-005` (Transport Safety):** The base URL declared in `servers` must be `https://` or `wss://`. Do not hardcode `http://` for production specs.
- **`OMCP-ADV-005` (Localhost bindings):** The `servers.url` must not point to `localhost` or `127.0.0.1` in production to prevent SSRF bypasses.

By adhering to strict Pydantic `Field` boundaries and enforcing global security schemes, you ensure the LLM interacts with deterministic, secure, and compliant MCP instances.
