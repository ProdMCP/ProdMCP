"""FastAPI Migration Example — Drop-in replacement.

This file demonstrates that a FastAPI project can be migrated to ProdMCP
by changing ONLY the import line. Every decorator, parameter name, and
pattern remains identical.

Before (FastAPI):
    from fastapi import FastAPI, Depends, HTTPException

After (ProdMCP):
    from prodmcp import ProdMCP as FastAPI, Depends, HTTPException
"""

# ── The ONLY line that changes ─────────────────────────────────────────
from prodmcp import ProdMCP as FastAPI, Depends, HTTPException
# ── Everything below is IDENTICAL to a standard FastAPI app ────────────

from pydantic import BaseModel

app = FastAPI(title="UserService", version="2.0.0")


class UserCreate(BaseModel):
    username: str
    email: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str


# Simulated database
USERS_DB: dict[int, dict] = {
    1: {"id": 1, "username": "alice", "email": "alice@example.com"},
    2: {"id": 2, "username": "bob", "email": "bob@example.com"},
}
_next_id = 3


@app.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
def get_user(user_id: int) -> dict:
    """Fetch a user by ID."""
    if user_id not in USERS_DB:
        raise HTTPException(status_code=404, detail="User not found")
    return USERS_DB[user_id]


@app.get("/users", response_model=list[UserResponse], tags=["users"])
def list_users() -> list:
    """List all users."""
    return list(USERS_DB.values())


@app.post("/users", response_model=UserResponse, status_code=201, tags=["users"])
def create_user(payload: UserCreate) -> dict:
    """Create a new user."""
    global _next_id
    user = {"id": _next_id, "username": payload.username, "email": payload.email}
    USERS_DB[_next_id] = user
    _next_id += 1
    return user


@app.delete("/users/{user_id}", status_code=204, tags=["users"])
def delete_user(user_id: int) -> None:
    """Delete a user."""
    if user_id not in USERS_DB:
        raise HTTPException(status_code=404, detail="User not found")
    del USERS_DB[user_id]


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(port=8000)
