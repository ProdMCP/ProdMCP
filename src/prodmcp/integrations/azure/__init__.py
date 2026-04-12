"""Azure Active Directory / Entra ID integration for ProdMCP.

Usage::

    from prodmcp.integrations.azure import AzureADAuth, AzureADTokenContext

    auth = AzureADAuth.from_env()
    app.add_security_scheme("bearer", auth.bearer_scheme)

    @app.tool()
    @app.get("/data")
    @app.common(security=[{"bearer": []}])
    def get_data(ctx: AzureADTokenContext = Depends(auth.require_context)) -> dict:
        ctx.require_role("admin")          # raises 403 if not in roles claim
        obo = ctx.get_obo_token()          # On-Behalf-Of exchange (lazy / cached)
        return {"user": ctx.user_info, "obo_scope": obo.get("scope")}
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from prodmcp.exceptions import ProdMCPSecurityError
from prodmcp.security.http import HTTPBearer
from prodmcp.security.base import SecurityContext

logger = logging.getLogger(__name__)


# ── Module-level JWKS / OpenID config caches (shared across all AzureADAuth instances) ──

_OPENID_CACHE: dict[str, dict[str, Any]] = {}   # keyed by tenant_id
_JWKS_CACHE: dict[str, dict[str, Any]] = {}     # keyed by tenant_id


def _fetch_json(url: str) -> dict[str, Any]:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _get_openid_config(tenant_id: str, force: bool = False) -> dict[str, Any]:
    entry = _OPENID_CACHE.get(tenant_id, {})
    if force or not entry or time.time() >= entry.get("expires_at", 0):
        url = f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
        _OPENID_CACHE[tenant_id] = {"value": _fetch_json(url), "expires_at": time.time() + 3600}
    return _OPENID_CACHE[tenant_id]["value"]


def _get_jwks(tenant_id: str, force: bool = False) -> dict[str, Any]:
    entry = _JWKS_CACHE.get(tenant_id, {})
    if force or not entry or time.time() >= entry.get("expires_at", 0):
        oid = _get_openid_config(tenant_id, force=force)
        _JWKS_CACHE[tenant_id] = {"value": _fetch_json(oid["jwks_uri"]), "expires_at": time.time() + 3600}
    return _JWKS_CACHE[tenant_id]["value"]


# ── TokenContext ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AzureADTokenContext:
    """Verified Azure AD identity attached to every authenticated request.

    Attributes:
        token:  Raw JWT string (access token).
        claims: Decoded and verified JWT payload.
        _auth:  Back-reference to the AzureADAuth instance (for OBO calls).
    """

    token: str
    claims: dict[str, Any]
    _auth: "AzureADAuth" = field(repr=False, compare=False)

    # Convenient claim accessors ────────────────────────────────────────────────

    @property
    def user_info(self) -> dict[str, Any]:
        """Common user-identity fields from the JWT claims."""
        return {
            "oid": self.claims.get("oid"),
            "tid": self.claims.get("tid"),
            "preferred_username": self.claims.get("preferred_username"),
            "name": self.claims.get("name"),
            "aud": self.claims.get("aud"),
            "scp": self.claims.get("scp"),
            "roles": self.claims.get("roles", []),
        }

    @property
    def roles(self) -> list[str]:
        """Roles granted to the calling user (from the `roles` claim)."""
        raw = self.claims.get("roles", [])
        return [raw] if isinstance(raw, str) else list(raw)

    def has_role(self, role: str) -> bool:
        """Return True if the user has the given role."""
        return role in self.roles

    def require_role(self, role: str) -> None:
        """Raise HTTPException 403 if the user does not have *role*.

        Args:
            role: Role name to check (e.g. ``"admin"``).

        Raises:
            HTTPException: 403 Forbidden if the role is absent.
        """
        from prodmcp import HTTPException
        if not self.has_role(role):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' required. User has roles: {self.roles}",
            )

    def get_obo_token(self, scope: str | None = None) -> dict[str, Any]:
        """Exchange this token for a downstream service token via OBO flow.

        Args:
            scope: Target scope (e.g. ``"https://graph.microsoft.com/.default"``).
                   Defaults to ``AzureADAuth.obo_scope``.

        Returns:
            Microsoft token endpoint response dict with ``access_token``,
            ``token_type``, ``expires_in``, ``scope``.

        Raises:
            HTTPException: 503 if the Microsoft endpoint is unreachable.
            HTTPException: 400/502 if the OBO exchange fails.
        """
        return self._auth._obo_exchange(self.token, scope or self._auth.obo_scope)


# ── AzureADAuth ────────────────────────────────────────────────────────────────

class AzureADAuth:
    """Plug-and-play Azure Active Directory / Entra ID authentication for ProdMCP.

    Handles:
    - JWKS-based JWT validation (RS256, audience, issuer, expiry)
    - Multi-format issuer / audience acceptance (v1 + v2 endpoints)
    - On-Behalf-Of (OBO) token exchange
    - Admin role enforcement helper

    Example::

        from prodmcp.integrations.azure import AzureADAuth, AzureADTokenContext
        from prodmcp import ProdMCP, Depends

        auth = AzureADAuth.from_env()

        app = ProdMCP("MyServer")
        app.add_security_scheme("bearer", auth.bearer_scheme)

        @app.tool()
        @app.common(security=[{"bearer": []}])
        def protected(ctx: AzureADTokenContext = Depends(auth.require_context)) -> dict:
            ctx.require_role("admin")
            return ctx.user_info

    Args:
        tenant_id:       Azure AD tenant GUID or domain.
        client_id:       Backend app registration client ID (used as audience).
        client_secret:   Backend app registration client secret (for OBO).
        api_audience:    Expected ``aud`` claim (defaults to ``api://{client_id}``).
        obo_scope:       Default downstream scope for OBO exchange.
        extra_audiences: Additional valid audience values.
        extra_issuers:   Additional valid issuer values.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        api_audience: str | None = None,
        obo_scope: str = "https://graph.microsoft.com/.default",
        extra_audiences: list[str] | None = None,
        extra_issuers: list[str] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_audience = api_audience or f"api://{client_id}"
        self.obo_scope = obo_scope
        self._extra_audiences: set[str] = set(extra_audiences or [])
        self._extra_issuers: set[str] = set(extra_issuers or [])

    # ── Construction helpers ────────────────────────────────────────────────────

    @classmethod
    def from_env(
        cls,
        *,
        tenant_id_var: str = "TENANT_ID",
        client_id_var: str = "BACKEND_CLIENT_ID",
        client_secret_var: str = "BACKEND_CLIENT_SECRET",
        api_audience_var: str = "API_AUDIENCE",
        obo_scope_var: str = "OBO_SCOPE",
    ) -> "AzureADAuth":
        """Create an AzureADAuth instance from environment variables.

        Reads:
            - ``TENANT_ID`` (or *tenant_id_var*)
            - ``BACKEND_CLIENT_ID`` (or *client_id_var*)
            - ``BACKEND_CLIENT_SECRET`` (or *client_secret_var*)
            - ``API_AUDIENCE`` (or *api_audience_var*, optional)
            - ``OBO_SCOPE`` (or *obo_scope_var*, optional)

        Raises:
            RuntimeError: If any required variable is missing.
        """
        def _require(name: str) -> str:
            val = os.getenv(name, "").strip()
            if not val:
                raise RuntimeError(
                    f"AzureADAuth.from_env(): missing required env var '{name}'"
                )
            return val

        return cls(
            tenant_id=_require(tenant_id_var),
            client_id=_require(client_id_var),
            client_secret=_require(client_secret_var),
            api_audience=os.getenv(api_audience_var, "").strip() or None,
            obo_scope=os.getenv(obo_scope_var, "https://graph.microsoft.com/.default"),
        )

    # ── ProdMCP integration points ──────────────────────────────────────────────

    @property
    def bearer_scheme(self) -> "AzureADBearerScheme":
        """Return a ProdMCP-compatible SecurityScheme for this auth config.

        Use with ``app.add_security_scheme("bearer", auth.bearer_scheme)``.
        """
        return AzureADBearerScheme(self)

    def require_context(self, credentials: Any = None) -> AzureADTokenContext:
        """ProdMCP dependency — validate the Bearer token and return a context.

        Use with ``Depends(auth.require_context)``.

        Args:
            credentials: Auto-injected by ProdMCP from the Authorization header.

        Returns:
            Verified :class:`AzureADTokenContext`.

        Raises:
            HTTPException: 401 if the token is missing, malformed, or invalid.
        """
        from prodmcp import HTTPException

        if (
            credentials is None
            or getattr(credentials, "scheme", "").lower() != "bearer"
            or not getattr(credentials, "credentials", None)
        ):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        token = credentials.credentials
        claims = self._validate_token(token)
        return AzureADTokenContext(token=token, claims=claims, _auth=self)

    # ── Internal implementation ─────────────────────────────────────────────────

    def _valid_audiences(self) -> set[str]:
        return {self.api_audience, self.client_id} | self._extra_audiences

    def _valid_issuers(self, oid_config: dict[str, Any]) -> set[str]:
        tid = self.tenant_id
        return {
            oid_config.get("issuer", ""),
            f"https://sts.windows.net/{tid}/",
            f"https://login.microsoftonline.com/{tid}/",
            f"https://login.microsoftonline.com/{tid}/v2.0",
        } | self._extra_issuers

    def _find_signing_key(self, token: str) -> dict[str, Any]:
        try:
            from jose import jwt as _jwt, JWTError
            header = _jwt.get_unverified_header(token)
        except Exception as exc:
            raise _auth_error("Invalid token header") from exc

        kid = header.get("kid")
        if not kid:
            raise _auth_error("Missing token key identifier (kid)")

        for force in (False, True):
            jwks = _get_jwks(self.tenant_id, force=force)
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    return key

        raise _auth_error("Unable to find signing key for token")

    def _validate_token(self, token: str) -> dict[str, Any]:
        try:
            from jose import jwt as _jwt, JWTError
        except ImportError as exc:
            raise RuntimeError(
                "prodmcp.integrations.azure requires 'python-jose[cryptography]'. "
                "Install it with: pip install python-jose[cryptography]"
            ) from exc

        # Peek at unverified claims for audience/issuer selection
        try:
            raw = _jwt.get_unverified_claims(token)
        except Exception:
            raw = {}

        actual_aud = raw.get("aud", "<missing>")
        actual_iss = raw.get("iss", "<missing>")

        try:
            oid_config = _get_openid_config(self.tenant_id)
            signing_key = self._find_signing_key(token)

            matched_aud = next(
                (a for a in self._valid_audiences() if a == actual_aud), None
            )
            if not matched_aud:
                raise _auth_error(
                    f"Invalid audience. Token aud='{actual_aud}', "
                    f"expected one of {sorted(self._valid_audiences())}"
                )

            matched_iss = next(
                (i for i in self._valid_issuers(oid_config) if i == actual_iss), None
            )
            if not matched_iss:
                raise _auth_error(
                    f"Invalid issuer. Token iss='{actual_iss}', "
                    f"expected one of {sorted(self._valid_issuers(oid_config))}"
                )

            return _jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=matched_aud,
                issuer=matched_iss,
                options={"verify_at_hash": False},
            )

        except JWTError as exc:
            raise _auth_error(f"Token validation failed: {exc}") from exc
        except requests.RequestException as exc:
            from prodmcp import HTTPException
            raise HTTPException(
                status_code=503,
                detail="Unable to reach Microsoft identity metadata endpoints",
            ) from exc

    def _obo_exchange(self, user_token: str, scope: str) -> dict[str, Any]:
        """Perform an On-Behalf-Of token exchange."""
        from prodmcp import HTTPException

        token_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "requested_token_use": "on_behalf_of",
            "assertion": user_token,
            "scope": scope,
        }

        try:
            resp = requests.post(token_url, data=payload, timeout=15)
            body = resp.json()
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=503,
                detail="Unable to reach Microsoft token endpoint",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Microsoft token endpoint returned invalid JSON",
            ) from exc

        if resp.status_code >= 400:
            error_code = body.get("error", "token_exchange_failed")
            raise HTTPException(
                status_code=400 if resp.status_code < 500 else 502,
                detail={
                    "error": error_code,
                    "error_description": body.get("error_description", "Unknown OBO failure"),
                    "hint": _obo_hint(error_code),
                },
            )

        return body


# ── AzureADBearerScheme — ProdMCP SecurityScheme adapter ───────────────────────

class AzureADBearerScheme(HTTPBearer):
    """A ProdMCP HTTPBearer scheme that validates tokens via AzureADAuth.

    When registered via ``app.add_security_scheme("bearer", auth.bearer_scheme)``,
    ProdMCP's spec generator will advertise this as a Bearer/JWT scheme in the
    OpenMCP spec, and the security enforcement layer will call ``extract()``
    to validate tokens on secured routes/tools.
    """

    def __init__(self, auth: AzureADAuth) -> None:
        super().__init__()
        self._auth = auth

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        """Validate the Bearer token from request headers."""
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith("Bearer "):
            raise ProdMCPSecurityError(
                "Missing or invalid Bearer token", scheme="bearerAuth"
            )

        token = auth_header[len("Bearer "):]
        claims = self._auth._validate_token(token)
        return SecurityContext(token=token, scopes=list(claims.get("roles", [])))


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _auth_error(detail: str) -> "Any":
    from prodmcp import HTTPException
    return HTTPException(status_code=401, detail=detail)


def _obo_hint(error_code: str) -> str:
    hints = {
        "invalid_grant": "Incoming user token may be invalid, expired, or missing required consent for OBO.",
        "invalid_scope": "Requested OBO scope is invalid. Verify OBO_SCOPE and downstream API permissions.",
        "unauthorized_client": "Backend app registration is not allowed to request this token or secret is invalid.",
        "interaction_required": "User or admin consent is required for downstream API permissions.",
    }
    return hints.get(error_code, "Check Azure app registration, API permissions, and consent settings.")


__all__ = ["AzureADAuth", "AzureADTokenContext", "AzureADBearerScheme"]
