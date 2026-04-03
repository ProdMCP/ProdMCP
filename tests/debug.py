from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from prodmcp.app import ProdMCP
from prodmcp.security import BearerAuth
from pydantic import BaseModel

app = ProdMCP("SecurityTestServer")
app._mcp = MagicMock()
app.add_security_scheme("bearerAuth", BearerAuth(scopes=[]))

class SecureInput(BaseModel):
    secret: str

@app.tool(
    name="secure_tool",
    input_schema=SecureInput,
    security=[{"bearerAuth": []}]
)
def my_secure_tool(secret: str, __security_context__=None) -> str:
    return f"Access granted to {secret}"

client = TestClient(app.as_fastapi())

resp = client.post(
    "/tools/secure_tool",
    json={"secret": "abc"},
    headers={"Authorization": "Bearer secret_token"}
)
print(resp.status_code)
print(resp.text)
