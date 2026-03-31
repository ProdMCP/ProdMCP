"""ProdMCP SSE / Streamable HTTP Example.

Demonstrates how to run a ProdMCP server as a pure MCP SSE transport.
This is useful for AI clients (Claude Desktop, Cursor, etc.) that connect
via the MCP protocol directly without needing a REST API.

For the more common unified mode (REST + MCP together), see unified_example.py.

Run:
    python sse_example.py
    # MCP SSE endpoint: http://localhost:8000/sse
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


@app.tool(
    name="add",
    description="Add two numbers.",
)
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    print("Starting ProdMCP in pure SSE mode...")
    print("MCP SSE endpoint: http://localhost:8000/sse")
    print()
    print("To run in unified mode (REST + MCP), use:")
    print("  app.run()  # serves REST at / and MCP at /mcp/sse")
    print()

    # Pure MCP SSE — no REST API routes
    app.run(
        transport="sse",
        host="0.0.0.0",
        port=8000
    )
