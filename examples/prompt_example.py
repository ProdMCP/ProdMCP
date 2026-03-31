"""ProdMCP Prompt example.

Demonstrates how to define and use prompts with input schemas.

Prompts are MCP-specific (no REST equivalent). They work the same
in both pure MCP and unified (REST + MCP) mode.
"""

from typing import List
from pydantic import BaseModel, Field
from prodmcp import ProdMCP


# ── Schemas ────────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    name: str
    age: int
    interests: List[str]


class ArticleSummaryInput(BaseModel):
    title: str
    content: str
    max_length: int = Field(default=50, description="Maximum length of the summary.")


# ── App Setup ──────────────────────────────────────────────────────────

app = ProdMCP("PromptExample")


# ── Simple prompt ─────────────────────────────────────────────────────

@app.prompt(
    name="greet_user",
    description="Generate a personalized greeting for the user."
)
def greet_user(name: str) -> str:
    """Generate a greeting."""
    return f"Hello, {name}! How can I help you today?"


# ── Prompt with structured input schema ───────────────────────────────

@app.prompt(
    name="explain_profile",
    description="Explain a user's profile based on their name, age, and interests.",
    input_schema=UserProfile
)
def explain_profile(name: str, age: int, interests: List[str]) -> str:
    """Explain a person's interests."""
    interest_str = ", ".join(interests)
    return (
        f"You should explain why {name}, who is {age} years old, "
        f"might be interested in {interest_str}."
    )


# ── Prompt with defaults ───────────────────────────────────────────────

@app.prompt(
    name="summarize_article",
    description="Summarize an article with a specified maximum length.",
    input_schema=ArticleSummaryInput
)
def summarize_article(title: str, content: str, max_length: int = 50) -> str:
    """Generate a summary prompt."""
    return (
        f"Summarize the following article titled '{title}' "
        f"to a maximum of {max_length} words: {content}"
    )


# ── Multi-step prompt ──────────────────────────────────────────────────

@app.prompt(
    name="analyze_theme",
    description="Analyze a theme across multiple texts.",
)
def analyze_theme(theme: str, texts: List[str]) -> str:
    """Analyze a common theme in multiple texts."""
    text_listing = "\n".join([f"- {text}" for text in texts])
    return (
        f"Analyze the theme of '{theme}' across the following texts:\n"
        f"{text_listing}"
    )


if __name__ == "__main__":
    # Export the spec
    print(app.export_openmcp_json())

    # Run options (v0.3.0):
    # app.run()                   # Unified: REST at / and MCP at /mcp (default)
    # app.run(transport="stdio")  # Pure MCP over stdin/stdout (Claude Desktop etc.)
