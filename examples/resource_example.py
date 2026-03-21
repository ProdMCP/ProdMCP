"""ProdMCP Resource example.

Demonstrates how to define and use resources with schemas and custom URIs.
"""

from typing import List
from pydantic import BaseModel
from prodmcp import ProdMCP

# 1. Define schemas for resource data
class User(BaseModel):
    id: int
    name: str
    avatar_url: str

class Article(BaseModel):
    id: int
    title: str
    content: str

# 2. Initialize ProdMCP app
app = ProdMCP("ResourceExample")

# 3. Define a static resource
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
        {"id": 2, "name": "Bob", "avatar_url": "https://example.com/bob.png"},
    ]

# 4. Define a resource with a dynamic URI (FastMCP supports templates)
@app.resource(
    uri="data://articles/{article_id}",
    name="article_by_id",
    description="Fetch a specific article by its ID.",
    output_schema=Article
)
def get_article(article_id: int) -> dict:
    """Fetch an article by ID."""
    # In a real app, you'd fetch this from a database
    articles = {
        1: {"id": 1, "title": "Introduction to ProdMCP", "content": "ProdMCP is a production layer for FastMCP."},
        2: {"id": 2, "title": "Advanced Resources", "content": "Learn how to use dynamic URIs in resources."},
    }
    return articles.get(article_id, {"id": 0, "title": "Not Found", "content": ""})

# 5. Define a resource with tags and custom mime type
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

if __name__ == "__main__":
    # Export OpenMCP spec to see how resources are defined
    print(app.export_openmcp_json())
    # To run the server:
    # app.run()
