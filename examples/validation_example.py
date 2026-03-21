"""ProdMCP Validation example.

Demonstrates input and output validation using Pydantic models.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr
from prodmcp import ProdMCP

# 1. Define input and output schemas
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    email: EmailStr
    age: Optional[int] = Field(None, ge=18, le=100)
    hobbies: List[str] = Field(default_factory=list)

class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    status: str = "active"

# 2. Initialize ProdMCP app
app = ProdMCP("ValidationExample")

# 3. Tool with input and output validation
@app.tool(
    name="create_user",
    description="Create a new user with validation.",
    input_schema=UserCreate,
    output_schema=UserResponse
)
def create_user(username: str, email: str, age: Optional[int] = None, hobbies: List[str] = []) -> dict:
    """Create a user."""
    # Logic for user creation (mocked)
    return {
        "id": 123,
        "username": username,
        "email": email,
        "status": "active"
    }

# 4. Tool with strict output validation (strict=True by default in ProdMCP)
@app.tool(
    name="get_user_by_id",
    description="Fetch a user by ID with strict output validation.",
    output_schema=UserResponse
)
def get_user_by_id(user_id: int) -> dict:
    """Fetch a user."""
    # In a real app, this would be from a database
    return {
        "id": user_id,
        "username": f"user_{user_id}",
        "email": f"user_{user_id}@example.com",
        "status": "verified"
    }

# 5. Tool without explicit schemas (standard Python types)
@app.tool(
    name="add_numbers",
    description="Add two numbers."
)
def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    # Export the spec
    print(app.export_openmcp_json())
    # To run the server:
    # app.run()
