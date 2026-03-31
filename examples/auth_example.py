"""ProdMCP Authentication example.

Demonstrates API Key and Bearer Token authentication using shorthand
and registered security schemes.

Also shows how @app.common() can centralise security config when the same
handler is exposed as both an MCP tool and a REST endpoint (v0.3.0).
"""

from pydantic import BaseModel
from prodmcp import ProdMCP, BearerAuth, ApiKeyAuth


# ── Schemas ────────────────────────────────────────────────────────────

class SecureData(BaseModel):
    id: str
    secret_value: str


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("AuthExample")

# Register named security schemes (OpenAPI style)
app.add_security_scheme("bearerAuth", BearerAuth(scopes=["admin", "user"]))
app.add_security_scheme("apiKeyAuth", ApiKeyAuth(key_name="X-API-Key", location="header"))


# ── Shorthand bearer security ─────────────────────────────────────────

@app.tool(
    name="get_secure_data_shorthand",
    description="Fetch secure data using shorthand bearer config.",
    security=[{"type": "bearer", "scopes": ["read"]}]
)
def get_secure_data_shorthand() -> dict:
    """Fetch data with shorthand bearer auth."""
    return {"id": "123", "secret_value": "shorthand-secret"}


# ── Named scheme: bearer ───────────────────────────────────────────────

@app.tool(
    name="get_admin_data",
    description="Fetch admin-only data using registered bearerAuth.",
    security=[{"bearerAuth": ["admin"]}]
)
def get_admin_data() -> dict:
    """Fetch admin data."""
    return {"id": "admin-1", "secret_value": "admin-secret"}


# ── Named scheme: API Key ──────────────────────────────────────────────

@app.tool(
    name="get_api_data",
    description="Fetch data using API key authentication.",
    security=[{"apiKeyAuth": []}]
)
def get_api_data() -> dict:
    """Fetch data with API key."""
    return {"id": "api-1", "secret_value": "api-key-protected"}


# ── OR semantics: bearer OR API Key ──────────────────────────────────

@app.tool(
    name="get_public_secure_data",
    description="Accessible via either Bearer or API Key.",
    security=[
        {"bearerAuth": ["user"]},
        {"apiKeyAuth": []}
    ]
)
def get_public_secure_data() -> dict:
    """Fetch data with either auth method."""
    return {"id": "public-1", "secret_value": "flexible-secret"}


# ── v0.3.0: @app.common() shares security across MCP + REST ──────────
# The same handler exposed as both an MCP tool AND a REST API endpoint,
# with the security config declared only once in @app.common().

@app.common(
    output_schema=SecureData,
    security=[{"bearerAuth": ["user"]}],
)
@app.tool(name="get_profile", description="Get the current user's profile.")
@app.get("/profile", tags=["auth"])
def get_profile() -> dict:
    """Fetch the authenticated user's profile."""
    return {"id": "me", "secret_value": "my-profile-data"}


if __name__ == "__main__":
    # Export the spec to see security definitions
    print(app.export_openmcp_json())

    # Run options (v0.3.0):
    # app.run()                    # Unified: REST + MCP at /mcp (default)
    # app.run(transport="stdio")   # Pure MCP over stdin/stdout
