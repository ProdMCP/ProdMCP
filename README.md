# ProdMCP

[![PyPI version](https://img.shields.io/badge/pypi-v0.5.0-blue)](https://pypi.org/project/prodmcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/prodmcp.svg)](https://pypi.org/project/prodmcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![FOSSA](https://img.shields.io/badge/FOSSA-license%20compliant-brightgreen)](https://app.fossa.com/projects/custom%2B61520%2Fprodmcp)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=prodmcp_ProdMCP&metric=coverage)](https://sonarcloud.io/summary/new_code?id=prodmcp_ProdMCP)

> **Unified production framework for both REST APIs and MCP servers.** Drop-in replacement for FastAPI and FastMCP with schema validation, security, middleware, dependency injection, and OpenMCP spec generation.

## 🛡️ Enterprise Compliance & Security
ProdMCP is engineered for highly-regulated enterprise environments.
- **FOSSA**: 100% License Compliant, 0 Security/Dependency Vulnerabilities.
- **SonarCloud SAST**: Grade A (0 Bugs, 0 Vulnerabilities, 0 Security Hotspots, >80% Test Coverage).
- **GitHub Advanced Security**: Active CodeQL tracking.

---

## Installation

```bash
pip install prodmcp              # Core (MCP tools, prompts, resources, security)
pip install prodmcp[rest]        # + FastAPI + Uvicorn for the unified server
```

---

## Quick Start

```python
from prodmcp import ProdMCP
from pydantic import BaseModel

app = ProdMCP("MyServer", version="1.0.0")

class UserResponse(BaseModel):
    """A user's public profile information."""
    name: str
    email: str

@app.tool(name="get_user", description="Fetch user by ID")
@app.get("/users/{user_id}")
def get_user(user_id: str) -> UserResponse:
    return UserResponse(name="Alice", email="alice@example.com")

if __name__ == "__main__":
    app.run()  # REST at / (Swagger at /docs) + MCP at /mcp/mcp
```

The `UserResponse` docstring automatically appears in the OpenAPI `responses.200.description` and the OpenMCP `output_description` field — no extra code required.

---

## ✨ What's New in v0.5.0

### Response Descriptions from Pydantic Docstrings

ProdMCP now auto-derives the `responses.200.description` (OpenAPI) and `output_description` (OpenMCP) from your output Pydantic model's class docstring. No decorator parameter needed.

```python
class TicketResponse(BaseModel):
    """A successfully created or retrieved support ticket."""
    id: str
    status: str

@app.tool(name="create_ticket", description="Open a new support ticket")
def create_ticket(payload: TicketCreate) -> TicketResponse:
    ...
```

Generated OpenAPI:
```json
"responses": {
  "200": {
    "description": "A successfully created or retrieved support ticket."
  }
}
```

Generated OpenMCP:
```json
"output_description": "A successfully created or retrieved support ticket."
```

**Union / Optional support:**

```python
class InvoiceResponse(BaseModel):
    """A finalized invoice record."""
    ...

class DraftResponse(BaseModel):
    """A draft invoice pending approval."""
    ...

def get_invoice(...) -> Union[InvoiceResponse, DraftResponse]:
    ...
# output_description → "InvoiceResponse: A finalized invoice record. | DraftResponse: A draft invoice pending approval."
```

### Return-Annotation `output_schema` Fallback

`_register_tool`, `_register_prompt`, and `_register_resource` now read the function's return annotation (`-> MyModel`) as the `output_schema` automatically when `output_schema=` is not specified explicitly.

```python
# Before (explicit — still works):
@app.tool(name="get_weather", output_schema=WeatherResponse)
def get_weather(city: str) -> WeatherResponse: ...

# After (idiomatic — docstring propagates automatically):
@app.tool(name="get_weather")
def get_weather(city: str) -> WeatherResponse: ...
```

### Security Specification Hardening (42Crunch / MCPcrunch Compliance)

- **Full OAuth2 `authorizationCode` flow** emitted in `components.securitySchemes` — satisfies `OMCP-SEC-012`.
- **Global `security` field** injected into generated OpenAPI and OpenMCP specs.
- **Per-operation `security`** now injected for prompts and resources, not just tools.
- **401 / 403 error responses** auto-added to all secured operations.

---

## Azure AD / Entra ID Integration

ProdMCP ships a zero-boilerplate Azure Active Directory integration at `prodmcp.integrations.azure`.  
It handles JWT validation, JWKS caching, multi-format issuer/audience support, and On-Behalf-Of (OBO) token exchange — in two lines of setup.

### Setup

```python
from prodmcp import ProdMCP, Depends
from prodmcp.integrations.azure import AzureADAuth, AzureADTokenContext

auth = AzureADAuth.from_env()          # reads TENANT_ID, BACKEND_CLIENT_ID,
                                       # BACKEND_CLIENT_SECRET, API_AUDIENCE from env
app = ProdMCP("MyServer")
app.add_security_scheme("bearer", auth.bearer_scheme)
```

### Required environment variables

| Variable | Description |
|---|---|
| `TENANT_ID` | Azure AD tenant GUID |
| `BACKEND_CLIENT_ID` | Backend app registration client ID |
| `BACKEND_CLIENT_SECRET` | Backend app registration client secret |
| `API_AUDIENCE` | Expected `aud` claim (e.g. `api://your-client-id`) |
| `OBO_SCOPE` | On-Behalf-Of target scope (default: `https://graph.microsoft.com/.default`) |

### Protecting routes and MCP tools

```python
@app.tool(name="get_data", description="Authenticated data fetch")
@app.get("/data")
@app.common(security=[{"bearer": []}])
def get_data(ctx: AzureADTokenContext = Depends(auth.require_context)) -> dict:
    ctx.require_role("admin")       # 403 if the user doesn't have the 'admin' role
    obo = ctx.get_obo_token()       # On-Behalf-Of token exchange (downstream API access)
    return {
        "user": ctx.user_info,      # { oid, tid, name, preferred_username, roles, scp }
        "obo_scope": obo.get("scope"),
    }
```

`AzureADTokenContext` provides:

| Attribute / Method | Description |
|---|---|
| `ctx.token` | Raw JWT string |
| `ctx.claims` | Full decoded JWT payload |
| `ctx.user_info` | Common identity fields (oid, tid, name, roles…) |
| `ctx.roles` | List of roles from the JWT |
| `ctx.has_role("admin")` | Boolean role check |
| `ctx.require_role("admin")` | Raises 403 if role absent |
| `ctx.get_obo_token(scope=...)` | On-Behalf-Of exchange |

---

## Using with Google ADK (Agent Development Kit)

ProdMCP tools secured with Azure AD work seamlessly with ADK agents.  
The Bearer token flows from the REST request → ADK's `MCPToolset` transport headers → ProdMCP's server-side security check — **no extra auth code needed in the agent**.

```python
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StreamableHTTPConnectionParams

session_service = InMemorySessionService()

@app.post("/api/chat")
@app.common(security=[{"bearer": []}])
async def chat(request: ChatRequest, ctx: AzureADTokenContext = Depends(auth.require_context)) -> dict:
    toolset = MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=request.mcp_url,
            headers={"Authorization": f"Bearer {ctx.token}"},
        )
    )
    agent = LlmAgent(model="gemini-2.5-flash", tools=[toolset])
    runner = Runner(agent=agent, app_name="myapp", session_service=session_service)
    session = await session_service.create_session(app_name="myapp", user_id=ctx.claims["oid"])

    from google.genai import types
    result_text = ""
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=request.message)]),
    ):
        if event.is_final_response() and event.content:
            result_text = "".join(p.text for p in event.content.parts if hasattr(p, "text"))

    await toolset.close()
    return {"reply": result_text}
```

The `headers={"Authorization": f"Bearer {ctx.token}"}` line is the **only auth-specific addition** — everything else is standard ADK boilerplate.

---

## Running the Example App (`prodmcp-masl`)

The `prodmcp-masl` directory contains a full reference implementation: Azure AD authentication + ADK agent + React frontend.

### Prerequisites

- Python 3.11+, Node.js 18+
- An Azure AD tenant with:
  - A **frontend** SPA app registration (public client, no secret)
  - A **backend** API app registration (with a client secret and exposed API scope)

### 1. Configure environment

```bash
# prodmcp-masl/.env
TENANT_ID=your-tenant-guid
BACKEND_CLIENT_ID=your-backend-app-client-id
BACKEND_CLIENT_SECRET=your-backend-secret
API_AUDIENCE=api://your-backend-client-id
OBO_SCOPE=https://graph.microsoft.com/.default
GEMINI_API_KEY=your-gemini-api-key
ALLOWED_ORIGINS=http://localhost:5173
```

```bash
# prodmcp-masl/frontend/.env.local
VITE_TENANT_ID=your-tenant-guid
VITE_FRONTEND_CLIENT_ID=your-frontend-app-client-id
VITE_BACKEND_SCOPE=api://your-backend-client-id/your-scope-name
VITE_GEMINI_API_KEY=your-gemini-api-key   # optional, can be entered in UI
```

### 2. Start the backend

```bash
cd prodmcp-masl
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh
# → http://localhost:8000
# → Swagger UI: http://localhost:8000/docs
# → MCP endpoint: http://localhost:8000/mcp/mcp
```

### 3. Start the frontend

```bash
cd prodmcp-masl/frontend
npm install
npm run dev
# → http://localhost:5173
```

### 4. Test

Open `http://localhost:5173` and sign in with your Azure AD account.

**Sidebar — Test API Endpoints:**

| Endpoint | What to verify |
|---|---|
| `GET /health` → **Run** | Should return `{"status": "ok"}` with no auth |
| `GET /data` → **Run** | Returns your identity claims + OBO token (200) |
| `GET /data` → **Run without auth** | Returns 401 Unauthorized |
| `GET /api/tools` → **Run** | Lists live MCP tools registered on the server |

---

## Features

- **Unified Framework** — One `ProdMCP` instance replaces both FastAPI and FastMCP
- **Decorator Stacking** — `@app.tool()` + `@app.get()` on the same handler with `@app.common()` for shared config
- **HTTP Methods** — `@app.get()`, `@app.post()`, `@app.put()`, `@app.delete()`, `@app.patch()`
- **MCP Primitives** — `@app.tool()`, `@app.prompt()`, `@app.resource()`
- **Auto Response Descriptions** — Pydantic model docstrings propagate to OpenAPI and OpenMCP specs automatically
- **Return-Annotation Fallback** — `output_schema` inferred from `-> ReturnType` annotation automatically
- **Schema-First Validation** — Pydantic models or raw JSON Schema for input/output
- **Security Layer** — Bearer, API key, OAuth2, OpenID Connect; `prodmcp.integrations.azure` for Azure AD
- **Middleware System** — Global and per-handler before/after hooks
- **Dependency Injection** — `Depends()` compatible with FastAPI and ProdMCP dependencies
- **ADK-Ready** — Works out of the box with Google Agent Development Kit via `MCPToolset`
- **OpenMCP Spec** — Auto-generated machine-readable specification with `output_description` per capability

## License

MIT

---

## Release Notes

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

### v0.5.0 — Response descriptions from Pydantic docstrings + security hardening

- Pydantic model docstrings now automatically populate `responses.200.description` (OpenAPI) and `output_description` (OpenMCP) — no decorator changes needed.
- `Union[A, B]` responses compose a combined description: `"ModelA: desc | ModelB: desc"`.
- Return-annotation `output_schema` fallback: `-> MyModel` is sufficient, `output_schema=MyModel` in the decorator is no longer required.
- Full OAuth2 `authorizationCode` flow emitted in security schemes (42Crunch / `OMCP-SEC-012` compliant).
- Global and per-operation `security` fields injected for all prompts, resources, and tools.

### v0.4.0 — REST Bridge API cleanup

Renamed `app.as_fastapi()` → `app.test_mcp_as_fastapi()`. Old name removed.

### v0.3.12 — Pydantic schema fix for secured MCP tools with ADK

Fixes a startup crash when ADK's `MCPToolset` is used with tools that have user-defined dependency types.

### v0.3.11 — Azure AD / Entra ID integration (`prodmcp.integrations.azure`)

`AzureADAuth`, `AzureADTokenContext`, `AzureADBearerScheme` — complete Azure AD JWT validation, JWKS caching, multi-format issuer/audience support, role checking, and OBO token exchange in two lines of setup.

### v0.3.10 — MCP tool security fix (Bug 10)

ProdMCP-secured MCP tools were raising `ProdMCPSecurityError` on every ADK/MCP call because `__security_context__` was never injected for MCP protocol calls.

### v0.3.9 — FastMCP lifespan fix (Bug 9)

Fixed `RuntimeError: Task group is not initialized` on startup.

### v0.3.0 — Unified Framework Release

One framework for both REST and MCP. `@app.common()` for shared config. `app.run()` for the unified server.
