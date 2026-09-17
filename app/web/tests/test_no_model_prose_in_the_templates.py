"""A template served the model's own reasoning to the user.

`scheduler.html` shipped with 793 bytes of LLM narration in front of the document, and the whole page
wrapped in a markdown code fence:

    Looking at this template, I need to:

    1. Wire the date navigation form with proper method/action (it already has `method="get" action="/"`
       — but the route is `/scheduler`, so I'll point it there)
    2. Add success/error message handling (none currently visible in markup, but I must wrap something...
    ```html
    <!DOCTYPE html>
    ...
    ```

The binding step stored the model's ENTIRE response as the template instead of extracting the fenced
code block, so the reasoning rendered as the first thing on the Scheduler page — above the header, in
the browser, to the user. Every gate passed it: the file was valid HTML (a browser renders stray text as
text), the page answered 200, the probe parsed it, the suite never opened it, and the smoke check only
asserts a status code.

A user found it. This is the test that would have.
"""
from pathlib import Path

import pytest

TEMPLATES = sorted((Path(__file__).resolve().parents[1] / "templates").glob("*.html"))

# Phrases that belong to a model talking about the work, never to a page. Deliberately short and
# specific: `I need to:` and `Looking at this` are what actually leaked, and a broad pattern like "I "
# would match ordinary copy.
PROSE = (
    "Looking at this template",
    "Looking at the",
    "I need to:",
    "I'll point it there",
    "Here's the updated",
    "Here is the updated",
    "the instructions require",
    "As an AI",
)


def _visible(markup: str) -> str:
    """The template minus Jinja comments and CSS comments, which are ours and may discuss anything."""
    import re

    without_jinja = re.sub(r"\{#.*?#\}", "", markup, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", without_jinja, flags=re.S)


def test_there_is_at_least_one_template() -> None:
    """A glob that silently matches nothing would make every test below vacuously pass."""
    assert len(TEMPLATES) >= 10, [p.name for p in TEMPLATES]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_no_markdown_code_fence(path: Path) -> None:
    """The fence is the tell: a template is a file, not a chat reply."""
    assert "```" not in path.read_text(encoding="utf-8"), (
        f"{path.name} still contains a markdown code fence — the model's response was stored whole "
        "instead of the code block being extracted."
    )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_no_model_narration(path: Path) -> None:
    found = [p for p in PROSE if p in _visible(path.read_text(encoding="utf-8"))]

    assert not found, f"{path.name} contains model reasoning: {found}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_a_full_page_starts_with_its_doctype(path: Path) -> None:
    """Nothing may precede `<!DOCTYPE>` — that is exactly where the leaked prose sat.

    Partials are exempt by name (`_nav.html`, `_shared_styles.html`): they are included INTO a page and
    correctly have no doctype of their own.
    """
    if path.name.startswith("_"):
        pytest.skip("a partial has no doctype of its own")
    text = path.read_text(encoding="utf-8").lstrip()

    assert text.lower().startswith("<!doctype"), (
        f"{path.name} begins with {text[:70]!r} rather than its doctype"
    )
