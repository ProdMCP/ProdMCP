# Release Notes

## Version 0.2.0
**Initial Public API Release**

This release brings the full production-ready capability of ProdMCP, featuring:

- **Decorator API**: Elegantly define tools, prompts, and resources using `@app.tool()`, `@app.prompt()`, and `@app.resource()`.
- **Schema-First Validation**: Native integration with Pydantic (`BaseModel`) allowing inputs/outputs validation to be rigorously enforced via `strict_output` toggle.
- **Advanced Security Manager**: Includes native `BearerAuth`, `ApiKeyAuth`, and `CustomAuth` schemes. Features shorthand inline security definitions (e.g. `{"type": "bearer", "scopes": ["admin"]}`).
- **Dependency Injection**: First-class `Depends()` support, mimicking FastAPI, enabling asynchronous resolution of context (Headers, Request parameters) into tool arguments automatically.
- **Middleware Hooks**: Global and entity-specific lifecycle hooks (`before`, `after`) using `MiddlewareContext` for request logging, metrics, and granular control.
- **Network Transports**: Support for basic `stdio` execution and streamable HTTP endpoints using Server-Sent Events (`sse`).
- **OpenMCP Specification Engine**: Auto-generates native OpenSpec definitions to define endpoints programmatically (`app.export_openmcp()`).
- **REST Bridge**: Instantly convert an MCP setup into a fully documented FastAPI router endpoint (`app.as_fastapi()`).

**Documentation Improvements:**
- Added robust examples covering SSE Server capabilities (`examples/sse_example.py`).
- Integrated end-to-end `SKILL.md` for AI agent consumption.
