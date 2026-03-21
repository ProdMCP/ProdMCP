"""ProdMCP Authentication example.

Demonstrates API Key and Bearer Token authentication using shorthand 
and registered security schemes.
"""

from pydantic import BaseModel
from prodmcp import ProdMCP, BearerAuth, ApiKeyAuth

# 1. Define schemas
class SecureData(BaseModel):
    id: str
    secret_value: str

# 2. Initialize ProdMCP app
app = ProdMCP("AuthExample")

# 3. Register a named security scheme (OpenAPI style)
app.add_security_scheme("bearerAuth", BearerAuth(scopes=["admin", "user"]))
app.add_security_scheme("apiKeyAuth", ApiKeyAuth(key_name="X-API-Key", location="header"))

# 4. Tool using shorthand bearer authentication
@app.tool(
    name="get_secure_data_shorthand",
    description="Fetch secure data using shorthand bearer config.",
    security=[{"type": "bearer", "scopes": ["read"]}]
)
def get_secure_data_shorthand() -> dict:
    """Fetch data with shorthand bearer auth."""
    return {"id": "123", "secret_value": "shorthand-secret"}

# 5. Tool using registered security schemes
@app.tool(
    name="get_admin_data",
    description="Fetch admin-only data using registered bearerAuth.",
    security=[{"bearerAuth": ["admin"]}]
)
def get_admin_data() -> dict:
    """Fetch admin data."""
    return {"id": "admin-1", "secret_value": "admin-secret"}

# 6. Tool using API Key authentication
@app.tool(
    name="get_api_data",
    description="Fetch data using API key authentication.",
    security=[{"apiKeyAuth": []}]
)
def get_api_data() -> dict:
    """Fetch data with API key."""
    return {"id": "api-1", "secret_value": "api-key-protected"}

# 7. Tool with multiple authentication options (logical OR)
@app.tool(
    name="get_public_secure_data",
    description="Fetch data that can be accessed via either Bearer or API Key.",
    security=[
        {"bearerAuth": ["user"]},
        {"apiKeyAuth": []}
    ]
)
def get_public_secure_data() -> dict:
    """Fetch data with either auth method."""
    return {"id": "public-1", "secret_value": "flexible-secret"}

if __name__ == "__main__":
    # Export the spec to see security definitions
    print(app.export_openmcp_json())
    # To run the server:
    # app.run()
