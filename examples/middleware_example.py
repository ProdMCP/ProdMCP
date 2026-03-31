"""ProdMCP Middleware example.

Demonstrates how to create and use custom middleware for logging and rate limiting.

Middleware works identically in all modes:
  - Pure MCP tools (@app.tool)
  - Pure REST routes (@app.get / @app.post)
  - Stacked handlers (both at once)
"""

import time
from typing import Dict
from prodmcp import ProdMCP, Middleware, MiddlewareContext, LoggingMiddleware


# ── Custom Middleware Definitions ──────────────────────────────────────

class RateLimiter(Middleware):
    """Limits calls per entity per minute."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.calls: Dict[str, list] = {}

    async def before(self, context: MiddlewareContext) -> None:
        now = time.time()
        entity = f"{context.entity_type}:{context.entity_name}"

        if entity not in self.calls:
            self.calls[entity] = []

        # Filter calls in the last minute
        self.calls[entity] = [t for t in self.calls[entity] if now - t < 60]

        if len(self.calls[entity]) >= self.requests_per_minute:
            raise Exception(
                f"Rate limit exceeded for {entity}. "
                f"Max {self.requests_per_minute} requests per minute."
            )

        self.calls[entity].append(now)
        print(f"[RateLimiter] Call {len(self.calls[entity])}/{self.requests_per_minute} for {entity}")

    async def after(self, context: MiddlewareContext) -> None:
        pass


class ContextLogger(Middleware):
    """Assigns a request_id and logs completion."""

    async def before(self, context: MiddlewareContext) -> None:
        context.metadata["request_id"] = "req_" + str(int(time.time()))
        print(f"[ContextLogger] Assigned request_id: {context.metadata['request_id']}")

    async def after(self, context: MiddlewareContext) -> None:
        print(f"[ContextLogger] Completed request_id: {context.metadata.get('request_id')}")


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("MiddlewareExample")

# Global middleware (applies to all tools/routes)
app.add_middleware(LoggingMiddleware())
app.add_middleware(RateLimiter(requests_per_minute=5), name="rate_limit")


# ── Pure MCP Tools ─────────────────────────────────────────────────────

@app.tool(
    name="fast_tool",
    description="A tool with global middleware only."
)
def fast_tool() -> str:
    """A fast tool."""
    return "Fast result"


@app.tool(
    name="limited_tool",
    description="A tool with an additional named rate limiter.",
    middleware=["rate_limit"]
)
def limited_tool() -> str:
    """A rate-limited tool."""
    return "Limited result"


@app.tool(
    name="context_tool",
    description="A tool that uses a custom context logger.",
    middleware=[ContextLogger()]
)
def context_tool() -> str:
    """A tool with context logging."""
    return "Context result"


# ── v0.3.0: REST + MCP stacked with shared middleware via @app.common() ─

@app.common(middleware=["rate_limit"])
@app.tool(name="rate_limited_weather", description="Get weather (rate-limited MCP + REST).")
@app.get("/weather/{city}", tags=["weather"])
def get_weather(city: str) -> dict:
    """Fetch weather for a city."""
    return {"city": city, "temp": 22.0, "condition": "Sunny"}


# ── v0.3.0: Pure REST route with middleware ────────────────────────────

@app.get("/health", tags=["system"])
def health() -> dict:
    """Health check — no extra middleware."""
    return {"status": "ok"}


if __name__ == "__main__":
    print(app.export_openmcp_json())

    print("\n" + "="*50 + "\n")
    print("Registered tools and their middleware:")
    for tool_name in app.list_tools():
        meta = app.get_tool_meta(tool_name)
        mw = meta.get("middleware", [])
        print(f"  - {tool_name}: {mw}")

    print("\nRegistered API routes:")
    for route in app.list_api_routes():
        print(f"  - {route}")

    # Run unified (REST + MCP) — v0.3.0 default:
    # app.run()
