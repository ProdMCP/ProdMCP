"""FastMCP Migration Example — Drop-in replacement.

This file demonstrates that a FastMCP project can be migrated to ProdMCP
by changing ONLY the import line. Every decorator, parameter name, and
pattern remains identical.

Before (FastMCP):
    from fastmcp import FastMCP

After (ProdMCP):
    from prodmcp import ProdMCP as FastMCP
"""

# ── The ONLY line that changes ─────────────────────────────────────────
from prodmcp import ProdMCP as FastMCP
# ── Everything below is IDENTICAL to a standard FastMCP app ────────────

mcp = FastMCP("WeatherServer")


@mcp.tool()
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Weather in {city}: 22°C, Partly Cloudy"


@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.resource("data://config")
def get_config() -> str:
    """Return application configuration."""
    return '{"debug": false, "log_level": "INFO"}'


@mcp.resource("data://users")
def get_users() -> str:
    """Return a list of users."""
    return '[{"name": "Alice"}, {"name": "Bob"}]'


@mcp.prompt()
def greeting(name: str) -> str:
    """Generate a personalized greeting."""
    return f"Hello {name}! How can I assist you today?"


@mcp.prompt()
def code_review(code: str) -> str:
    """Generate a code review prompt."""
    return f"Please review the following code:\n\n{code}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
