"""ProdMCP Validation example.

Demonstrates input and output validation using Pydantic models.

New in v0.3.0: validation works identically for both MCP tools
and REST API routes — you can stack them on the same handler.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr
from prodmcp import ProdMCP


# ── Schemas ────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    email: EmailStr
    age: Optional[int] = Field(None, ge=18, le=100)
    hobbies: List[str] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    status: str = "active"


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("ValidationExample")


# ── MCP tool with validation ───────────────────────────────────────────

@app.tool(
    name="add_numbers",
    description="Add two numbers."
)
def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


# ── v0.3.0: Stacked tool + REST with shared schemas via @app.common() ─
# Input/output schemas defined once, shared across both MCP and REST.

@app.common(
    input_schema=UserCreate,
    output_schema=UserResponse,
)
@app.tool(
    name="create_user",
    description="Create a new user with validation.",
)
@app.post("/users", status_code=201, tags=["users"])
def create_user(
    username: str,
    email: str,
    age: Optional[int] = None,
    hobbies: List[str] = [],
) -> dict:
    """Create a user."""
    return {
        "id": 123,
        "username": username,
        "email": email,
        "status": "active"
    }


# ── REST-only route with response_model ───────────────────────────────

@app.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
def get_user_by_id(user_id: int) -> dict:
    """Fetch a user by ID."""
    return {
        "id": user_id,
        "username": f"user_{user_id}",
        "email": f"user_{user_id}@example.com",
        "status": "verified"
    }


# ── MCP-only tool with output schema ──────────────────────────────────

@app.tool(
    name="get_user_mcp",
    description="Fetch a user by ID (MCP only).",
    output_schema=UserResponse
)
def get_user_mcp(user_id: int) -> dict:
    """Fetch a user (MCP tool)."""
    return {
        "id": user_id,
        "username": f"user_{user_id}",
        "email": f"user_{user_id}@example.com",
        "status": "verified"
    }


if __name__ == "__main__":
    # Export the spec
    print(app.export_openmcp_json())

    print("\nAPI routes registered:")
    for route in app.list_api_routes():
        print(f"  {route}")

    # Run unified (v0.3.0 default — REST + MCP):
    # app.run()
    # Or MCP only via stdio:
    # app.run(transport="stdio")
