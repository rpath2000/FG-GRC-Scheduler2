"""Five defects a user found by looking at the pages, all one root cause: ten private headers.

Reported from the running app:

  1. the brand title was huge on Reservations
  2. "Show Filters" and Export did nothing when clicked
  3. the signed-in user block was different on every page
  4. choosing Day changed the view but the toggle still showed Week selected
  5. the logo changed from page to page

Nothing was broken in the usual sense — every page returned 200 and rendered — so no gate objected.
Ten templates had each built their own header, and they disagreed on everything visible:

    logo glyph     GRC (x3), G (x5), ◉, ⟲
    brand element  <span> (x8), <h1> (x2)
    brand size     18px, 1.1rem, 1.125rem, 1.25rem, 20px
    right side     "AH Hamelin, Alex ⎋" / "↓" / "▼" / "↗" / "👤 … ⚙" / "Hamelin, Alex HA ⏏"

The oversized title (1) is worth spelling out: `.app-title` asked for 18px, but two templates wrapped
the brand in an `<h1>` and no stylesheet defines `h1`, so the BROWSER DEFAULT of 2em won. Eight pages
used a span and looked correct, which made it read as a one-page bug rather than a missing shell.

(4) was a hardcoded `class="view-btn active"` on Week: the handler read `view=day` correctly and the
timeline changed, while the control kept claiming Week. A page contradicting itself is worse than one
that does nothing.

(2) is NOT a bug — Show Filters and Export are deliberately out of scope and rendered disabled so the
header matches the approved screen. But they carried no disabled STYLE, so they looked like ordinary
blue links and invited the click. Being unavailable and looking unavailable are different requirements.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

PAGES = (
    "/", "/scheduler", "/instruments", "/instruments/form", "/instruments/favorites",
    "/reservations/new", "/audit",
    "/admin/locations", "/admin/vendors", "/admin/types", "/admin/purposes",
)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


@pytest.fixture(scope="module")
def client():
    """A client over a real schema.

    These assertions are about MARKUP, but every page queries the database to render, so a missing
    schema fails them with `no such table: instruments` and says nothing about the header. Creating the
    tables keeps the test honest about what it is measuring.
    """
    from app.models import Base
    from app.models.database import engine

    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


def _header(markup: str) -> str:
    found = re.search(r"<header[^>]*>.*?</header>", markup, re.S)
    assert found, "the page has no <header>"
    return found.group(0)


# --- one shell, not ten ---------------------------------------------------------------------------

def test_every_page_renders_the_same_header(client) -> None:
    """The defect behind (3) and (5), stated as one assertion.

    Every marker of WHERE YOU ARE is excluded, because that is the one thing which should differ per
    page: the active link, and the Admin group's own active/expanded state on the four admin routes.
    Comparing raw headers reports "different" shells when only the highlight has moved.
    """
    def shell(markup: str) -> str:
        text = _header(markup)
        text = re.sub(r'\s*aria-current="page"', "", text)
        text = re.sub(r'\s*aria-expanded="(?:true|false)"', "", text)
        text = re.sub(r'class="([^"]*?)\s*\bactive\b\s*([^"]*?)"', r'class="\1\2"', text)
        # Stripping the only class leaves `class=""`, which is itself a difference.
        text = re.sub(r'\s*class=""', "", text)
        return re.sub(r"\s+", " ", text).strip()

    headers = {p: shell(client.get(p).text) for p in PAGES}
    distinct = set(headers.values())

    assert len(distinct) == 1, (
        f"{len(distinct)} different header shells across {len(PAGES)} pages: "
        + ", ".join(sorted(headers))
    )


def test_one_logo_glyph_everywhere(client) -> None:
    glyphs = set()
    for p in PAGES:
        found = re.search(r'class="site-logo"[^>]*>([^<]*)<', _header(client.get(p).text))
        assert found, f"{p} has no .site-logo"
        glyphs.add(found.group(1).strip())

    assert len(glyphs) == 1, f"logo differs between pages: {glyphs}"


def test_one_user_block_everywhere(client) -> None:
    blocks = set()
    for p in PAGES:
        found = re.search(r'<div class="site-header-right">.*?</div>\s*</header>',
                          _header(client.get(p).text), re.S)
        blocks.add(re.sub(r"\s+", " ", found.group(0)) if found else f"MISSING on {p}")

    assert len(blocks) == 1, f"the user block differs between pages: {len(blocks)} variants"


def test_the_brand_is_never_a_heading(client) -> None:
    """(1). A heading inherits the browser's 2em and overrides whatever the page asked for."""
    for p in PAGES:
        assert "<h1" not in _header(client.get(p).text), (
            f"{p} puts a heading in the header — it will inherit the browser's default size"
        )


def test_the_brand_size_is_stated_once(client) -> None:
    sizes = set(re.findall(r"\.site-brand\s*\{[^}]*font-size:\s*([^;]+);", client.get("/").text))

    assert sizes == {"24px"}, f"expected one stated brand size, got {sizes}"


# --- the toggle tells the truth -------------------------------------------------------------------

@pytest.mark.parametrize("view", ["day", "week"])
def test_the_selected_view_is_the_highlighted_view(client, view: str) -> None:
    """(4). The handler always read `view` correctly; the control lied about it."""
    controls = re.search(r'<div class="view-controls">.*?</div>',
                         client.get(f"/?view={view}").text, re.S).group(0)
    active = re.findall(r'value="(\w+)"[^>]*class="view-btn active"', controls)

    assert active == [view], f"?view={view} highlights {active or 'nothing'}"


def test_month_and_year_stay_disabled(client) -> None:
    """Rendered so the control matches the approved screen; both views are out of scope."""
    controls = re.search(r'<div class="view-controls">.*?</div>',
                         client.get("/").text, re.S).group(0)

    assert re.findall(r'class="view-btn" disabled>(\w+)<', controls) == ["month", "year"]


# --- unavailable, and visibly so ------------------------------------------------------------------

def test_the_out_of_scope_actions_look_unavailable(client) -> None:
    """(2). They were correctly inert and looked entirely clickable."""
    page = client.get("/").text

    assert ".btn-link[disabled]" in page, "no disabled style, so a dead control looks like a live link"
    assert "cursor: not-allowed" in page
    for label in ("Show Filters", "Export"):
        control = re.search(rf'<button[^>]*>\s*{label}', page, re.S)
        assert control, f"{label} is missing"
        tag = page[control.start():control.start() + 240]
        assert "disabled" in tag, f"{label} is not disabled"
        assert "aria-disabled" in tag, f"{label} is not disabled to a screen reader"


# --- the guards: each of these would fail correct code ---

def test_the_shared_partials_exist() -> None:
    """A missing include renders as nothing, and every assertion above would then pass vacuously."""
    for name in ("_header.html", "_nav.html"):
        assert (TEMPLATES / name).is_file(), f"{name} is missing"


def test_every_page_includes_the_partial_rather_than_its_own_header() -> None:
    """Asserting on rendered output alone would not notice a template that copied the markup back in."""
    for path in TEMPLATES.glob("*.html"):
        if path.name.startswith("_"):
            continue
        body = path.read_text(encoding="utf-8")
        assert '{% include "_header.html" %}' in body, f"{path.name} does not include the shared header"
        assert "<header" not in body, f"{path.name} defines its own <header> again"


def test_the_user_block_does_not_imply_a_session(client) -> None:
    """There is no authentication here. The name is display only and must not offer a sign-out."""
    header = _header(client.get("/").text)

    assert "site-signout" in header, "the approved screen shows the glyph"
    assert "<a" not in re.search(r'<div class="site-header-right">.*?</div>\s*</header>',
                                header, re.S).group(0), "the user block must not link anywhere"
    assert "/logout" not in header and "/signout" not in header
