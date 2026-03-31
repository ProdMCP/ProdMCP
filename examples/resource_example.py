"""ProdMCP Resource example.

Demonstrates how to define and use resources with schemas and custom URIs.

Resources are MCP-specific. In v0.3.0 you can stack a @app.resource with
a @app.get to also expose the same data via a REST endpoint.
"""

from typing import List
from pydantic import BaseModel
from prodmcp import ProdMCP


# ── Schemas ────────────────────────────────────────────────────────────

class User(BaseModel):
    id: int
    name: str
    avatar_url: str


class Article(BaseModel):
    id: int
    title: str
    content: str


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("ResourceExample")


# ── Static resource (MCP only) ─────────────────────────────────────────

@app.resource(
    uri="data://static/users",
    name="static_users",
    description="A static list of users.",
    output_schema=List[User]
)
def get_static_users() -> List[dict]:
    """Fetch a static list of users."""
    return [
        {"id": 1, "name": "Alice", "avatar_url": "https://example.com/alice.png"},
        {"id": 2, "name": "Bob",   "avatar_url": "https://example.com/bob.png"},
    ]


# ── Dynamic resource with URI template ────────────────────────────────

@app.resource(
    uri="data://articles/{article_id}",
    name="article_by_id",
    description="Fetch a specific article by its ID.",
    output_schema=Article
)
def get_article(article_id: int) -> dict:
    """Fetch an article by ID."""
    articles = {
        1: {"id": 1, "title": "Introduction to ProdMCP",  "content": "ProdMCP is a unified framework."},
        2: {"id": 2, "title": "Advanced Resources",        "content": "Learn dynamic URIs in resources."},
    }
    return articles.get(article_id, {"id": 0, "title": "Not Found", "content": ""})


# ── Resource with tags and custom MIME type ───────────────────────────

@app.resource(
    uri="config://web/settings",
    name="web_settings",
    description="Web application settings in JSON format.",
    tags={"config", "web"},
    mime_type="application/json"
)
def get_web_settings() -> dict:
    """Fetch web settings."""
    return {
        "theme": "dark",
        "notifications": True,
        "api_endpoint": "https://api.example.com/v1"
    }


# ── v0.3.0: Stacked resource + REST endpoint ──────────────────────────
# The same handler is exposed as both:
#   MCP resource:  data://users
#   REST endpoint: GET /users

@app.common(output_schema=List[User])
@app.resource(uri="data://users", name="users_resource", description="All users.")
@app.get("/users", response_model=List[User], tags=["users"])
def list_users() -> List[dict]:
    """List all users (available via MCP resource AND REST GET)."""
    return [
        {"id": 1, "name": "Alice", "avatar_url": "https://example.com/alice.png"},
        {"id": 2, "name": "Bob",   "avatar_url": "https://example.com/bob.png"},
    ]


if __name__ == "__main__":
    # Export OpenMCP spec
    print(app.export_openmcp_json())

    print("\nRegistered resources:", app.list_resources())
    print("Registered API routes:", app.list_api_routes())

    # Run options (v0.3.0):
    # app.run()                   # Unified: REST at / and MCP at /mcp (default)
    # app.run(transport="stdio")  # Pure MCP over stdin/stdout
