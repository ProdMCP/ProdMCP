#!/usr/bin/env bash
# reorganize_tests.sh
# Reorganizes ProdMCP tests into thematic subfolders, writes tests.md,
# then verifies the full suite still passes.
# Run from the repo root: bash reorganize_tests.sh

set -e
REPO="/Users/muruga/Projects/ProdMCP-org/ProdMCP"
T="$REPO/tests"

echo "==> Creating subfolders..."
for g in core validation security middleware bridge spec transport compat regression integration; do
  mkdir -p "$T/$g"
  touch "$T/$g/__init__.py"
done

echo "==> Moving files (skips already-moved files)..."

move_if_exists() {
  local src="$T/$1"
  local dst="$T/$2"
  if [ -f "$src" ]; then
    mv "$src" "$dst"
    echo "  MOVED  $1 -> $2"
  elif [ -f "$dst" ]; then
    echo "  SKIP   $2 (already in place)"
  else
    echo "  MISS   $1 (not found)"
  fi
}

# Core
move_if_exists test_constructor.py           core/test_constructor.py
move_if_exists test_decorators.py            core/test_decorators.py
move_if_exists test_common_decorator.py      core/test_common_decorator.py
move_if_exists test_stacking.py              core/test_stacking.py
move_if_exists test_deferred_registration.py core/test_deferred_registration.py
move_if_exists test_edge_cases.py            core/test_edge_cases.py
move_if_exists test_dependencies.py          core/test_dependencies.py
move_if_exists test_imports.py               core/test_imports.py

# Validation
move_if_exists test_schemas.py               validation/test_schemas.py
move_if_exists test_validation.py            validation/test_validation.py

# Security
move_if_exists test_security.py              security/test_security.py

# Middleware
move_if_exists test_middleware.py            middleware/test_middleware.py

# Bridge
move_if_exists test_fastapi.py               bridge/test_fastapi_bridge.py
move_if_exists test_mcp_bridge.py            bridge/test_mcp_test_bridge.py
move_if_exists test_http_methods.py          bridge/test_http_methods.py
move_if_exists test_unified_router.py        bridge/test_unified_router.py

# Spec
move_if_exists test_openmcp.py               spec/test_openmcp_spec.py

# Transport
move_if_exists test_run_method.py            transport/test_run_method.py

# Compat
move_if_exists test_migration_compat.py      compat/test_migration_compat.py

# Regression (renamed)
move_if_exists test_missing_coverage.py      regression/test_regression_pass1.py
move_if_exists test_missing_coverage_pass2.py regression/test_regression_pass2.py

# Integration
move_if_exists test_integration.py           integration/test_integration.py

echo ""
echo "==> Writing tests/tests.md..."
cat > "$T/tests.md" << 'MD'
# ProdMCP — Test Suite Reference

> **383 tests** across 10 thematic groups.
> All groups are discovered automatically by pytest via `testpaths = ["tests"]`.

---

## Folder Structure

```
tests/
├── core/          Core decorator, registration, and stacking behaviour
├── validation/    Schema resolution and input/output validation engine
├── security/      Security schemes, managers, and extraction logic
├── middleware/    Middleware manager and chain execution
├── bridge/        FastAPI REST bridge, MCP bridge, HTTP methods, unified router
├── spec/          OpenMCP specification generation
├── transport/     run() method and transport-mode selection
├── compat/        FastMCP and FastAPI migration compatibility
├── regression/    Targeted blind-spot regression suites (2 audit passes)
└── integration/   End-to-end multi-component integration tests
```

---

## core/ — Core Framework

| File | What it tests |
|------|---------------|
| `test_constructor.py` | `ProdMCP(name,...)`: positional name, `title=`, version, description, `mcp_path`, `strict_output`, registry init |
| `test_decorators.py` | `@app.tool`, `@app.prompt`, `@app.resource` — registration, name defaults, schema/security/middleware attachment, handler preservation |
| `test_common_decorator.py` | `@app.common(...)` propagation to all entity types; inline override; optional usage |
| `test_stacking.py` | Decorator stacking: `@app.tool + @app.get`, triple stacks, function identity (name, docstring, async) |
| `test_deferred_registration.py` | Pending queue → registry finalization; `@app.common` feeds deferred tools; API routes bypass queue |
| `test_edge_cases.py` | Empty/unicode/long names, many tools, lambda handlers, no-return annotation, multiline docstrings, async stacking |
| `test_dependencies.py` | FastAPI `Depends()` stripping from tool signatures; standard DI injection |
| `test_imports.py` | Public API imports from `prodmcp`, `prodmcp.security`, `prodmcp.exceptions` |

---

## validation/ — Validation Engine

| File | What it tests |
|------|---------------|
| `test_schemas.py` | `resolve_schema()` (Pydantic + dict deepcopy + None + TypeError); `validate_data()` (Pydantic, JSON Schema objects/arrays/scalars/enums); `extract_schema_ref()` $defs hoisting |
| `test_validation.py` | `create_validated_handler()`: no-schema pass-through, input pass/fail, output strict/non-strict, async wrapping |

---

## security/ — Security

| File | What it tests |
|------|---------------|
| `test_security.py` | BearerAuth, APIKeyHeader/Query, CustomAuth, SecurityManager (OR semantics, spec gen, shorthand), HTTPBasic, APIKeyCookie, OAuth2, OpenIdConnect |

---

## middleware/ — Middleware

| File | What it tests |
|------|---------------|
| `test_middleware.py` | Registration, `execute_before`/`after` order, `build_middleware_chain` (sync/async, kwargs mutation, error propagation), global hooks for prompts+resources, ASGI middleware accumulation |

---

## bridge/ — FastAPI & REST Bridges

| File | What it tests |
|------|---------------|
| `test_fastapi_bridge.py` | `app.test_mcp_as_fastapi()`: route creation, execution, security (403/422/200), ASGI middleware on bridge, ValueError → 400 via custom handler |
| `test_mcp_test_bridge.py` | `test_mcp_as_fastapi()`: route creation, exact HTTP responses, `test_mcp_as_fastapi()` isinstance check |
| `test_http_methods.py` | `@app.get/post/put/delete/patch`: registration, path params, response models, tags, status codes, function identity |
| `test_unified_router.py` | `create_unified_app()`: FastAPI app, CRUD, CORS, MCP sub-app CORS, falsy kwargs, finalization, exception handlers |

---

## spec/ — OpenMCP Specification

| File | What it tests |
|------|---------------|
| `test_openmcp_spec.py` | `export_openmcp()`: structure, tools/prompts/resources, `components.schemas`, security schemes, tool-level security; empty app |

---

## transport/ — Transport & Server

| File | What it tests |
|------|---------------|
| `test_run_method.py` | `app.run(transport=...)`: stdio → FastMCP; SSE/http/streamable-http → `run_http_async`; default host/port; ASGI middlewares forwarded |

---

## compat/ — Migration Compatibility

| File | What it tests |
|------|---------------|
| `test_migration_compat.py` | FastMCP drop-in (`FastMCP(name)`, `@mcp.tool`, async, `mcp.run()`); FastAPI drop-in; ProdMCP backward compat |

---

## regression/ — Blind-Spot Regression Suites

### `test_regression_pass1.py` (59 tests — Audit Pass 1)

| Class | Blind spot covered |
|-------|--------------------|
| `TestScopeValidatorEnforcement` | `scope_validator` overrides scopes; warning fires at construction |
| `TestSecuritySpecContent` | Bearer spec has correct `type`/`scheme`; apiKey has `name`+`in` |
| `TestAndSemanticsInSecurityRequirements` | AND-logic (both required); OR-logic (either sufficient) |
| `TestCustomAuthErrorMessage` | Custom auth error content; no double-wrapping |
| `TestEmptyKwargsValidation` | Empty kwargs + required schema → `ProdMCPValidationError` |
| `TestBeforeHookFailurePairing` | `before[1]` fails → `after[0]` still runs |
| `TestJsonSchemaArrayAndScalarValidation` | array/string/integer/number/boolean/enum/recursive schemas |
| `TestResolveSchemaIsolation` | Mutating returned schema dict doesn't corrupt Pydantic cache |
| `TestApiKeyHeaderCaseInsensitive` | RFC 7230 case-insensitive header lookup (5 variants) |
| `TestMultilineDocstringExactSummary` | Route summary = first line only; tool description = full docstring |
| `TestCommonSecurityShorthandFormat` | `{"type":"bearer"}` shorthand; scheme auto-registered at finalization |
| `TestSpecGenerationReadOnly` | `generate_security_spec()` is idempotent and non-mutating |

### `test_regression_pass2.py` (38 tests — Audit Pass 2)

| Class | Blind spot covered |
|-------|--------------------|
| `TestInputCoercion` | P2-1: Pydantic coerces `"3"`→int; handler receives coerced value |
| `TestOutputPydanticToDict` | P2-2: Handler returning `BaseModel` instance → serialized to dict |
| `TestSecurityContextInjection` | P2-3: `__security_context__` only injected when `security` is configured |
| `TestDictSchemaWithoutProperties` | P2-4: Dict schema without `properties` → dict_route_handler, no 404/405 |
| `TestParameterizedResourceRoute` | P2-5: `@app.resource(uri="items/{id}")` → URI vars forwarded to handler |
| `TestMatchUriTemplate` | P2-6: Multi-var, slash-in-value, special chars in URI templates |
| `TestResolveSchemaRawDictIsolation` | P2-11: `resolve_schema(dict)` returns deep copy; spec export safe |
| `TestDuplicateToolName` | P2-12: Duplicate tool name → last-writer-wins |
| `TestEmptyAppSpec` | P2-13: Empty app has no `components`, no schemas for bare tools |
| `TestNonStrictOutputValidation` | P2-14: Non-strict swallows invalid output; strict raises error |
| `TestExceptionPropagationToFastAPIHandlers` | P2-10: ValueError→400, SecurityError→403, ValidationError→422, HTTPException preserved |

---

## integration/ — Integration

| File | What it tests |
|------|---------------|
| `test_integration.py` | Full pipeline: spec gen, JSON roundtrip, registry integrity, schema deduplication, OR security, middleware + validation together |

---

## Running the Suite

```bash
# Full suite
python3 -m pytest tests/ -v

# Single group
python3 -m pytest tests/security/ -v
python3 -m pytest tests/regression/ -v

# With coverage
python3 -m pytest tests/ --cov=prodmcp --cov-report=term-missing

# Install dev dependencies first (required for async tests)
pip install -e ".[dev,rest]"
```

---

## Test Count by Group

| Group | Tests |
|-------|-------|
| core | ~130 |
| validation | ~25 |
| security | ~25 |
| middleware | ~20 |
| bridge | ~40 |
| spec | ~8 |
| transport | ~10 |
| compat | ~15 |
| regression | ~97 |
| integration | ~13 |
| **Total** | **383** |
MD

echo "  WROTE tests/tests.md"

echo ""
echo "==> Current test tree:"
find "$T" -name "*.py" | grep -v __pycache__ | sort

echo ""
echo "==> Running pytest to verify 383 tests pass..."
cd "$REPO"
python3 -m pytest tests/ -q --tb=short

echo ""
echo "==> Done. You can delete this script: rm reorganize_tests.sh"
