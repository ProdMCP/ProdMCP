"""ProdMCP OpenMCP Spec Generation example.

Demonstrates how to export the OpenMCP specification from a ProdMCP application,
including tools, prompts, resources, schemas, and security schemes.

New in v0.3.0: REST API routes (@app.get, @app.post etc.) are also included
when generating specs via export_openmcp().
"""

from typing import List
from pydantic import BaseModel
from prodmcp import ProdMCP

# ── Schemas ────────────────────────────────────────────────────────────

class User(BaseModel):
    id: int
    name: str

class Article(BaseModel):
    id: int
    title: str

class ArticleCreate(BaseModel):
    title: str
    content: str


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP(
    "OpenMCPExample",
    version="1.0.0",
    description="A demo for OpenMCP spec generation."
)


# ── MCP Tool with security ─────────────────────────────────────────────

@app.tool(
    name="get_users",
    description="Fetch all users.",
    output_schema=List[User],
    security=[{"type": "bearer", "scopes": ["read"]}]
)
def get_users() -> List[dict]:
    """Fetch all users."""
    return [{"id": 1, "name": "Alice"}]


# ── v0.3.0: Stacked tool + REST route ─────────────────────────────────
# Exposed as both an MCP tool AND GET /articles

@app.tool(name="list_articles", description="List all articles.")
@app.get("/articles", response_model=List[Article], tags=["articles"])
def list_articles() -> List[dict]:
    """Fetch articles."""
    return [{"id": 1, "title": "ProdMCP Guide"}]


# ── v0.3.0: POST route (REST only) ────────────────────────────────────

@app.post("/articles", response_model=Article, status_code=201, tags=["articles"])
def create_article(payload: ArticleCreate) -> dict:
    """Create an article."""
    return {"id": 2, "title": payload.title}


# ── Prompt ────────────────────────────────────────────────────────────

@app.prompt(
    name="summarize_article",
    description="Summarize an article by ID."
)
def summarize_article(article_id: int) -> str:
    """Summarize an article."""
    return f"Please summarize article with ID: {article_id}."


# ── Resource ──────────────────────────────────────────────────────────

@app.resource(
    uri="data://articles",
    name="article_list",
    description="List of all articles.",
    output_schema=List[Article]
)
def get_articles() -> List[dict]:
    """Fetch articles."""
    return [{"id": 1, "title": "ProdMCP Guide"}]


if __name__ == "__main__":
    # Export the OpenMCP specification as a dict
    spec = app.export_openmcp()
    print("OpenMCP Specification (Dict):")
    print(spec)

    print("\n" + "="*50 + "\n")

    # Export as a formatted JSON string
    spec_json = app.export_openmcp_json(indent=2)
    print("OpenMCP Specification (JSON):")
    print(spec_json)

    # You can save this to a file:
    # with open("openmcp_spec.json", "w") as f:
    #     f.write(spec_json)

    # Run in unified mode (v0.3.0 default):
    # app.run()   # REST at / and MCP at /mcp
