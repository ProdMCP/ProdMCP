"""ProdMCP basic example server.

Demonstrates tools, prompts, resources with schemas, security, middleware,
and OpenMCP spec export.
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


# ── Tools ──────────────────────────────────────────────────────────────


@app.tool(
    name="get_user_data",
    description="Fetch user profile data by user ID.",
    input_schema=UserInput,
    output_schema=UserOutput,
    security=[{"type": "bearer", "scopes": ["user"]}],
    middleware=["logging"],
)
def get_user_data(user_id: str) -> dict:
    """Retrieve user data from the database."""
    return {"name": "Alice", "email": "alice@example.com"}


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


# ── Export Spec ────────────────────────────────────────────────────────

if __name__ == "__main__":
    spec = app.export_openmcp()
    print(json.dumps(spec, indent=2))
    # Uncomment to run the MCP server:
    # app.run()
