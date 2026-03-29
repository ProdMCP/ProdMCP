"""ProdMCP SSE Streamable HTTP Example Server.

Demonstrates how to run a ProdMCP server as a streamable HTTP MCP 
using the standard Server-Sent Events (SSE) transport.
"""

import asyncio

from pydantic import BaseModel

from prodmcp import ProdMCP


class EchoInput(BaseModel):
    message: str


# Create the ProdMCP app
app = ProdMCP(
    "SSEStreamableServer", 
    version="1.0.0",
    description="Streamable HTTP MCP Example via SSE"
)


@app.tool(
    name="echo",
    description="Echoes the input message back.",
    input_schema=EchoInput,
)
async def echo(message: str) -> dict:
    """Return the sent message."""
    # Simulate a small delay for demonstration
    await asyncio.sleep(0.5)
    return {"response": f"Echo: {message}"}


if __name__ == "__main__":
    # FastMCP uses Starlette and Uvicorn under the hood to run an SSE server.
    # Note: Ensure you have `uvicorn` and `starlette` installed for SSE support.
    # Start the streamable HTTP MCP on port 8000
    print("Starting Streamable HTTP MCP (SSE transport)...")
    print("Client connection endpoint: http://localhost:8000/sse")
    
    app.run(
        transport="sse", 
        host="0.0.0.0", 
        port=8000
    )
