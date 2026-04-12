# ProdMCP

[![PyPI version](https://img.shields.io/badge/pypi-v0.3.12-blue)](https://pypi.org/project/prodmcp/)
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

app = ProdMCP("MyServer", version="1.0.0")

@app.tool(name="get_user", description="Fetch user by ID")
@app.get("/users/{user_id}")
def get_user(user_id: str) -> dict:
    return {"name": "Alice", "email": "alice@example.com"}

if __name__ == "__main__":
    app.run()  # REST at / (Swagger at /docs) + MCP at /mcp/mcp
```

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
    # Forward the user's Azure AD token to the MCP server
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

The `headers={"Authorization": f"Bearer {ctx.token}"}` line is the **only auth-specific addition** — everything else is standard ADK boilerplate. ProdMCP's `_mcp_secured_wrapper` handles server-side token extraction transparently.

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

**Sidebar — List Tools:** Confirms the MCP server is reachable and tools are registered.

**Chat box:** Type a message — the ADK agent uses `gemini-2.5-flash` and invokes `get_data` via MCP when relevant.

---

## Features

- **Unified Framework** — One `ProdMCP` instance replaces both FastAPI and FastMCP
- **Decorator Stacking** — `@app.tool()` + `@app.get()` on the same handler with `@app.common()` for shared config
- **HTTP Methods** — `@app.get()`, `@app.post()`, `@app.put()`, `@app.delete()`, `@app.patch()`
- **MCP Primitives** — `@app.tool()`, `@app.prompt()`, `@app.resource()`
- **Schema-First Validation** — Pydantic models or raw JSON Schema for input/output
- **Security Layer** — Bearer, API key, OAuth2, OpenID Connect; `prodmcp.integrations.azure` for Azure AD
- **Middleware System** — Global and per-handler before/after hooks
- **Dependency Injection** — `Depends()` compatible with FastAPI and ProdMCP dependencies
- **ADK-Ready** — Works out of the box with Google Agent Development Kit via `MCPToolset`
- **OpenMCP Spec** — Auto-generated machine-readable specification

## License

MIT

---

## Release Notes

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

### v0.3.12 — Pydantic schema fix for secured MCP tools with ADK

Fixes a startup crash when ADK's `MCPToolset` is used with tools that have user-defined dependency types (e.g. `AzureADTokenContext`) — `@functools.wraps` was leaking `__annotations__` from the original handler into `_mcp_secured_wrapper`, causing `PydanticSchemaGenerationError`.

### v0.3.11 — Azure AD / Entra ID integration (`prodmcp.integrations.azure`)

`AzureADAuth`, `AzureADTokenContext`, `AzureADBearerScheme` — complete Azure AD JWT validation, JWKS caching, multi-format issuer/audience support, role checking, and OBO token exchange in two lines of setup.

### v0.3.10 — MCP tool security fix (Bug 10)

ProdMCP-secured MCP tools were raising `ProdMCPSecurityError` on every ADK/MCP call because `__security_context__` was never injected for MCP protocol calls. Fixed via `_mcp_secured_wrapper` which extracts HTTP headers from FastMCP's `Context` object.

### v0.3.9 — FastMCP lifespan fix (Bug 9)

Fixed `RuntimeError: Task group is not initialized` caused by `FastAPI()` being constructed before `mcp_instance.http_app()`, leaving the FastMCP session manager task group uninitialised.

### v0.3.0 — Unified Framework Release

One framework for both REST and MCP. `@app.common()` for shared config. `app.run()` for the unified server.
