"""ProdMCP OpenMCP Generation example.

Demonstrates how to export the OpenMCP specification from a ProdMCP application.
"""

from typing import List
from pydantic import BaseModel
from prodmcp import ProdMCP

# 1. Define schemas
class User(BaseModel):
    id: int
    name: str

class Article(BaseModel):
    id: int
    title: str

# 2. Initialize ProdMCP app
app = ProdMCP("OpenMCPExample", version="1.0.0", description="A demo for OpenMCP spec generation.")

# 3. Add tools with security and middleware
@app.tool(
    name="get_users",
    description="Fetch all users.",
    output_schema=List[User],
    security=[{"type": "bearer", "scopes": ["read"]}]
)
def get_users() -> List[dict]:
    """Fetch all users."""
    return [{"id": 1, "name": "Alice"}]

# 4. Add prompts
@app.prompt(
    name="summarize_article",
    description="Summarize an article by ID."
)
def summarize_article(article_id: int) -> str:
    """Summarize an article."""
    return f"Please summarize article with ID: {article_id}."

# 5. Add resources
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
