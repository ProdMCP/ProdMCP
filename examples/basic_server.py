"""ProdMCP basic example server.

Demonstrates tools, prompts, resources with schemas, security, and middleware.
Also shows how to expose MCP tools as REST API endpoints (unified mode).

Run modes:
    python basic_server.py               # Prints the OpenMCP spec
    app.run()                            # Unified: REST + MCP at /mcp/sse (default)
    app.run(transport="stdio")           # MCP over stdin/stdout (Claude Desktop etc.)
    app.run(transport="sse")             # Pure MCP SSE only
"""

import json

from pydantic import BaseModel

from prodmcp import LoggingMiddleware, ProdMCP


# ── Schemas ────────────────────────────────────────────────────────────


class UserInput(BaseModel):
    user_id: str


class UserOutput(BaseModel):
    name: str
    email: str


class TextInput(BaseModel):
    text: str
    max_length: int = 500


class SummaryOutput(BaseModel):
    summary: str
    word_count: int


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("MyServer", version="1.0.0")
app.add_middleware(LoggingMiddleware, name="logging")


# ── Tools (MCP only) ───────────────────────────────────────────────────


@app.tool(
    name="summarize_text",
    description="Summarize a block of text.",
    input_schema=TextInput,
    output_schema=SummaryOutput,
)
def summarize_text(text: str, max_length: int = 500) -> dict:
    """Summarize text content."""
    words = text.split()
    summary = " ".join(words[:max_length])
    return {"summary": summary, "word_count": len(words)}


# ── Stacked: tool + REST API route ────────────────────────────────────
# The same handler is exposed via both:
#   MCP:  tool name "get_user_data"
#   REST: GET /users/{user_id}  ← new in v0.3.0


@app.tool(
    name="get_user_data",
    description="Fetch user profile data by user ID.",
    input_schema=UserInput,
    output_schema=UserOutput,
    security=[{"type": "bearer", "scopes": ["user"]}],
    middleware=["logging"],
)
@app.get("/users/{user_id}", response_model=UserOutput, tags=["users"])
def get_user_data(user_id: str) -> dict:
    """Retrieve user data from the database."""
    return {"name": "Alice", "email": "alice@example.com"}


# ── Prompts ────────────────────────────────────────────────────────────


@app.prompt(
    name="explain_topic",
    description="Generate a prompt asking for a topic explanation.",
    input_schema=TextInput,
)
def explain_topic(text: str) -> str:
    """Generate an explanation prompt."""
    return f"Please explain the following topic in detail: {text}"


# ── Resources ──────────────────────────────────────────────────────────


@app.resource(
    uri="data://users",
    name="user_database",
    description="User database resource.",
    output_schema=UserOutput,
)
def user_database() -> list:
    """Fetch all users from the database."""
    return [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": "bob@example.com"},
    ]


# ── Health endpoint (REST only, v0.3.0) ───────────────────────────────


@app.get("/health", tags=["system"])
def health() -> dict:
    """Health check."""
    return {"status": "ok", "version": "1.0.0"}


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    spec = app.export_openmcp()
    print(json.dumps(spec, indent=2))

    # Run options:
    # app.run()                         # Unified: REST + MCP (default)
    # app.run(transport="stdio")        # Pure MCP over stdin/stdout
    # app.run(transport="sse")          # Pure MCP SSE only
    # app.run(host="0.0.0.0", port=9000)  # Custom host/port
