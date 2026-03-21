"""ProdMCP Middleware example.

Demonstrates how to create and use custom middleware for logging and rate limiting.
"""

import time
from typing import Dict
from prodmcp import ProdMCP, Middleware, MiddlewareContext, LoggingMiddleware

# 1. Custom Rate Limiting Middleware
class RateLimiter(Middleware):
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
            raise Exception(f"Rate limit exceeded for {entity}. Max {self.requests_per_minute} requests per minute.")
        
        self.calls[entity].append(now)
        print(f"[RateLimiter] Call {len(self.calls[entity])}/{self.requests_per_minute} for {entity}")

    async def after(self, context: MiddlewareContext) -> None:
        # No action needed after the call
        pass

# 2. Custom Header Middleware (modifies metadata)
class ContextLogger(Middleware):
    async def before(self, context: MiddlewareContext) -> None:
        # Store some info in metadata for downstream middleware or logging
        context.metadata["request_id"] = "req_" + str(int(time.time()))
        print(f"[ContextLogger] Assigned request_id: {context.metadata['request_id']}")

    async def after(self, context: MiddlewareContext) -> None:
        print(f"[ContextLogger] Completed request_id: {context.metadata.get('request_id')}")

# 3. Initialize ProdMCP app
app = ProdMCP("MiddlewareExample")

# 4. Add global middleware
app.add_middleware(LoggingMiddleware())
app.add_middleware(RateLimiter(requests_per_minute=5), name="rate_limit")

# 5. Define tools with specific middleware
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

if __name__ == "__main__":
    # Export the spec to see how middleware is referenced (via tags or names)
    # Note: Middleware specifically is an internal implementation detail in ProdMCP,
    # but it affects how tools are wrapped and executed.
    print(app.export_openmcp_json())
    
    print("\n" + "="*50 + "\n")
    print("Example tools registered with middleware:")
    for tool_name in app.list_tools():
        meta = app.get_tool_meta(tool_name)
        mw = meta.get("middleware", [])
        print(f" - Tool: {tool_name}, Middleware: {mw}")
