"""Tests for the knowledge-base builder.

A scraper fails *silently* by nature: when the source markup changes, extraction
quietly returns nothing, the knowledge base empties out, and the assistant
starts answering "I don't have information about that" to every question. The
system looks healthy the whole time.

So these tests do two jobs — check the parsing logic, and pin the specific
site quirks that already broke the build once.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import build_kb
import pytest
from build_kb import (
    ContentBlock,
    PageKind,
    PageSpec,
    _clean_soup,
    _dedupe,
    _drop_filler,
    _extract_configurations,
    _extract_listing,
    _extract_specs,
    build_xml,
    parse_page,
    validate,
)
from defusedxml.ElementTree import parse as parse_xml

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_XML = REPO_ROOT / "knowledge-base" / "knowledge_base.xml"
RAW_DIR = REPO_ROOT / "knowledge-base" / "raw"


def _kb_root() -> ET.Element:
    """Parse the committed KB, narrowing away the Optional from getroot()."""
    root = parse_xml(KB_XML).getroot()
    assert root is not None
    return root


def _page(body: str) -> str:
    """Wrap a body fragment the way the real site does — inside a WebForms form."""
    return f"""
    <html><body>
      <header><a href="index.aspx">Home</a></header>
      <nav id="navbar"><a href="about-us.aspx">About</a></nav>
      <form name="form1" method="post" action="x.aspx" id="form1">
        {body}
      </form>
      <footer id="footer">Copyright 2024</footer>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Regression: the ASP.NET WebForms <form> wrapper
# ---------------------------------------------------------------------------


def test_form_wrapper_is_not_stripped_as_boilerplate() -> None:
    """The single highest-impact bug this builder can have.

    This is an ASP.NET WebForms site, so the *entire* page body sits inside one
    <form runat="server">. Treating forms as boilerplate — which is correct on
    almost any other site — deleted every word of content and produced a valid
    but empty knowledge base. Guard it permanently.
    """
    soup = _clean_soup(_page("<h2>Burj Ashrafi</h2><p>Status : Completed</p>"))
    text = soup.get_text(" ", strip=True)

    assert "Burj Ashrafi" in text
    assert "Completed" in text


def test_navigation_and_footer_are_stripped() -> None:
    soup = _clean_soup(_page("<h2>Real Content</h2>"))
    text = soup.get_text(" ", strip=True)

    assert "Real Content" in text
    assert "Copyright" not in text
    assert "About" not in text


# ---------------------------------------------------------------------------
# Regression: listing pages link to slugs that do not match the displayed name
# ---------------------------------------------------------------------------


def test_listing_pairs_project_with_link_despite_spelling_mismatch() -> None:
    """The site spells one project two different ways.

    upcoming.aspx displays "Burj Chisti" (one 's') while the URL is
    "burj-chishti.aspx". Matching names against slugs looked reasonable and
    silently dropped the project's entire 1,200-word detail page from the
    knowledge base. Pairing must be structural — via the link inside the card.
    """
    soup = _clean_soup(
        _page("""
        <div class="card">
          <h4>Burj Chisti</h4>
          <a href="burj-chishti.aspx">Read More</a>
        </div>
        """)
    )

    listed = _extract_listing(soup)

    assert len(listed) == 1
    assert listed[0].name == "Burj Chisti"
    assert listed[0].slug == "burj-chishti"


def test_listing_project_without_a_link_has_no_slug() -> None:
    """ongoing.aspx names Burj Ashrafi (Phase 2) but links nowhere.

    Inventing a slug here would attach Phase 1's "Completed" content to a
    project that is actually ongoing — a factual error told to customers.
    """
    soup = _clean_soup(_page('<div class="card"><h4>Burj Ashrafi (Phase 2)</h4></div>'))

    listed = _extract_listing(soup)

    assert listed[0].name == "Burj Ashrafi (Phase 2)"
    assert listed[0].slug is None


def test_listing_does_not_borrow_a_sibling_cards_link() -> None:
    soup = _clean_soup(
        _page("""
        <div class="row">
          <div class="card"><h4>Burj Classic</h4><a href="burj-classic.aspx">Read More</a></div>
          <div class="card"><h4>Unlinked Project</h4></div>
        </div>
        """)
    )

    listed = {item.name: item.slug for item in _extract_listing(soup)}

    assert listed["Burj Classic"] == "burj-classic"
    # Bounded ancestor walk must not reach across to the neighbouring card.
    assert listed["Unlinked Project"] is None


# ---------------------------------------------------------------------------
# Spec extraction
# ---------------------------------------------------------------------------


def test_specs_are_parsed_from_key_colon_value_paragraphs() -> None:
    soup = _clean_soup(
        _page("""
        <p>Status : Completed</p>
        <p>Area : 1.75 lakh sq.ft</p>
        <p>Storey : G+32</p>
        """)
    )

    assert _extract_specs(soup) == {
        "Status": "Completed",
        "Area": "1.75 lakh sq.ft",
        "Storey": "G+32",
    }


@pytest.mark.parametrize("value", ["-", "Download certificate", "N/A"])
def test_placeholder_rera_values_are_discarded(value: str) -> None:
    """ "Rera : Download certificate" is a PDF link, not a registration number.

    Recording it would let the assistant imply a RERA registration exists and
    that it knows the number — a claim with legal weight in Indian real estate.
    """
    soup = _clean_soup(_page(f"<p>Rera : {value}</p>"))

    assert "Rera" not in _extract_specs(soup)


def test_prose_containing_a_colon_is_not_mistaken_for_a_spec() -> None:
    long_sentence = "Note : " + "a very long marketing sentence about our values " * 3
    soup = _clean_soup(_page(f"<p>{long_sentence}</p>"))

    assert _extract_specs(soup) == {}


# ---------------------------------------------------------------------------
# Configurations recovered from image filenames
# ---------------------------------------------------------------------------


def test_configurations_are_recovered_from_floor_plan_filenames() -> None:
    """Unit configurations exist ONLY in image filenames on this site.

    "1 BHK" is never written in text — the sole record is
    images/burj-chishti/1.5bhk.jpg. It is real published data, and it answers
    one of the most common buyer questions.
    """
    soup = _clean_soup(
        _page("""
        <img src="images/burj-chishti/2bhk.jpg">
        <img src="images/burj-chishti/1.5bhk.jpg">
        <img src="images/burj-chishti/1bhk.jpg">
        <img src="images/gallery.jpg">
        """)
    )

    assert _extract_configurations(soup) == ["1 BHK", "1.5 BHK", "2 BHK"]


# ---------------------------------------------------------------------------
# Deduplication and filler removal
# ---------------------------------------------------------------------------


def test_dedupe_is_case_insensitive_and_order_preserving() -> None:
    assert list(_dedupe(["Gazebo", "Bike parking", "gazebo", "Gym"])) == [
        "Gazebo",
        "Bike parking",
        "Gym",
    ]


def test_repeated_template_filler_is_dropped() -> None:
    """The same marketing paragraph opens all four project pages.

    Four copies would teach the model to quote boilerplate that says nothing
    about any individual project.
    """
    filler = "A large part of our business is in the commercial real estate sector."
    blocks = [
        ContentBlock(heading="Overview", paragraphs=(f"{filler} And more text.", "Real detail.")),
        ContentBlock(heading="Only Filler", paragraphs=(f"{filler} Nothing else.",)),
    ]

    cleaned = _drop_filler(blocks, [filler])

    assert len(cleaned) == 1
    assert cleaned[0].paragraphs == ("Real detail.",)


def test_testimonial_authors_are_not_emitted_as_company_sections() -> None:
    """Reviews must be attributed, not restated as company facts.

    Left alone, the extractor turned a customer review into
    `<section title="Nadim Khan">` inside the company profile.
    """
    parsed = parse_page(
        PageSpec("index", PageKind.COMPANY),
        _page("""
        <h2>Our Customer Says</h2>
        <h3>Nadim Khan</h3><p>Well developed construction company.</p>
        <h3>Moosa Mistri</h3><p>Deserved to be in this field.</p>
        """),
    )

    assert parsed.testimonials == [
        ("Nadim Khan", "Well developed construction company."),
        ("Moosa Mistri", "Deserved to be in this field."),
    ]
    assert "Nadim Khan" not in {block.heading for block in parsed.blocks}


# ---------------------------------------------------------------------------
# Build validation — the loud-failure net
# ---------------------------------------------------------------------------


def test_validate_rejects_an_empty_knowledge_base() -> None:
    problems = validate(ET.Element("knowledge_base"))

    assert problems, "validation must reject an empty tree rather than pass it through"
    assert any("company_history" in problem for problem in problems)


def test_validate_accepts_the_committed_knowledge_base() -> None:
    root = _kb_root()

    assert validate(root) == []


# ---------------------------------------------------------------------------
# The committed artifact
# ---------------------------------------------------------------------------


def test_committed_kb_is_wellformed_and_has_every_expected_section() -> None:
    root = _kb_root()
    tags = {child.tag for child in root}

    assert {
        "company_profile",
        "company_history",
        "contact_info",
        "ongoing_projects",
        "completed_projects",
        "upcoming_projects",
        "faq",
    } <= tags


def test_committed_kb_contains_all_five_projects() -> None:
    root = _kb_root()
    names = {project.get("name", "") for project in root.findall(".//project")}

    assert "Burj Ashrafi (Phase 1)" in names
    assert "Burj Ashrafi (Phase 2)" in names
    assert any("Classic" in name for name in names)
    assert any("Qadri" in name for name in names)
    assert any("Chisti" in name for name in names)


def test_committed_kb_has_no_duplicate_project_slugs() -> None:
    """A slug appearing twice means listing/detail pairing has regressed."""
    root = _kb_root()
    slugs = [p.get("slug") for p in root.findall(".//project") if p.get("slug")]

    assert len(slugs) == len(set(slugs)), f"duplicate project entries: {slugs}"


def test_committed_kb_reports_ashrafi_phases_distinctly() -> None:
    """Phase 1 is complete; Phase 2 is ongoing. Conflating them misinforms buyers."""
    root = _kb_root()

    ongoing = {p.get("name") for p in root.findall("ongoing_projects/project")}
    completed = {p.get("name") for p in root.findall("completed_projects/project")}

    assert "Burj Ashrafi (Phase 2)" in ongoing
    assert "Burj Ashrafi (Phase 1)" in completed


def test_committed_kb_carries_real_content_not_just_structure() -> None:
    root = _kb_root()
    words = sum(len((node.text or "").split()) for node in root.iter())

    assert words > 1_500, f"knowledge base holds only {words} words — extraction likely broke"


def test_committed_kb_never_states_a_rera_number() -> None:
    """No RERA number has been verified, so none may appear.

    An invented registration number is the single most damaging thing this
    assistant could tell a buyer.
    """
    text = KB_XML.read_text(encoding="utf-8")

    assert "Download certificate" not in text
    assert "P51900XXXXXX" not in text


def test_kb_is_small_enough_to_inject_whole() -> None:
    """The design has no retrieval step, which is only valid while the KB is small.

    If this fails, the no-RAG decision needs revisiting — do not just raise the
    number. ~4 chars per token is the usual English approximation.
    """
    approx_tokens = len(KB_XML.read_text(encoding="utf-8")) / 4

    assert approx_tokens < 15_000, f"KB is ~{approx_tokens:,.0f} tokens; too large to inject whole"


def test_offline_rebuild_is_deterministic() -> None:
    """Two builds from the same cached HTML must agree.

    Non-determinism here (set iteration order, dict shuffling) would make the
    --check gate flap and every regeneration produce a noisy diff.
    """
    pages = {
        page.slug: parse_page(page, page.raw_path.read_text(encoding="utf-8"))
        for page in build_kb.PAGES
    }
    overrides = build_kb.load_overrides()

    first = ET.tostring(build_xml(pages, overrides), encoding="unicode")
    second = ET.tostring(build_xml(pages, overrides), encoding="unicode")

    assert first == second


def test_every_source_page_is_cached_for_offline_builds() -> None:
    missing = [page.slug for page in build_kb.PAGES if not page.raw_path.exists()]

    assert not missing, f"raw HTML missing for {missing}; run `make kb`"
    assert len(build_kb.PAGES) == 10, "expected 10 source pages (6 nav + 4 project detail)"
