"""ProdMCP Unified Example — API + MCP from one codebase.

Demonstrates:
1. Drop-in FastAPI migration: @app.get(), @app.post()
2. Drop-in FastMCP migration: @app.tool(), @app.resource(), @app.prompt()
3. Stacking: Same function serves both REST and MCP
4. @app.common() for shared cross-cutting concerns

Run:
    python examples/unified_example.py
    # REST:    http://localhost:8000/users/123
    # Swagger: http://localhost:8000/docs
    # MCP SSE: http://localhost:8000/mcp/sse
"""

from pydantic import BaseModel, Field

from prodmcp import ProdMCP, BearerAuth, LoggingMiddleware


# ── Schemas ────────────────────────────────────────────────────────────

class UserInput(BaseModel):
    username: str = Field(..., min_length=2)
    email: str

class UserOutput(BaseModel):
    id: int
    username: str
    email: str

class WeatherOutput(BaseModel):
    city: str
    temperature: float
    description: str


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("MyUnifiedServer", version="1.0.0")
app.add_middleware(LoggingMiddleware, name="logging")
app.add_security_scheme("bearer", BearerAuth(scopes=["read", "write"]))


# ── Pattern 1: Pure API (FastAPI drop-in) ──────────────────────────────

@app.get("/health", tags=["system"])
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


# ── Pattern 2: Pure MCP (FastMCP drop-in) ──────────────────────────────

@app.prompt()
def greeting(name: str) -> str:
    """Generate a greeting prompt."""
    return f"Hello {name}, how can I help you today?"


# ── Pattern 3: Stacked — same function for API + MCP ──────────────────

@app.tool(description="Fetch a user by their ID")
@app.get("/users/{user_id}", response_model=UserOutput, tags=["users"])
def get_user(user_id: int) -> dict:
    """Retrieve user data."""
    return {"id": user_id, "username": "alice", "email": "alice@example.com"}


@app.tool(description="Create a new user account")
@app.post("/users", response_model=UserOutput, tags=["users"])
def create_user(payload: UserInput) -> dict:
    """Create a user."""
    return {"id": 1, "username": payload.username, "email": payload.email}


# ── Pattern 4: @app.common() for shared concerns ──────────────────────

@app.common(
    output_schema=WeatherOutput,
    security=[{"bearer": ["read"]}],
    middleware=["logging"],
)
@app.tool(name="get_weather", description="Get weather for a city")
@app.get("/weather/{city}", tags=["weather"])
def get_weather(city: str) -> dict:
    """Fetch current weather."""
    return {
        "city": city,
        "temperature": 22.5,
        "description": "Partly cloudy",
    }


# ── Run ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Unified mode: REST at /, MCP at /mcp, Swagger at /docs
    app.run(host="0.0.0.0", port=8000)
