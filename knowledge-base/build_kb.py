#!/usr/bin/env python3
"""Build the Burj Constructions knowledge base from the live website.

    make kb                # fetch the site and regenerate
    make kb ARGS=--offline # rebuild from cached raw/ HTML, no network
    make kb ARGS=--check   # verify the committed XML is up to date (CI)

Why this shape:

* **Ten pages, not six.** The three project *listing* pages (ongoing, completed,
  upcoming) are navigation shells holding under 50 words each. Roughly 85% of
  the real content lives on the four project detail pages behind their
  "Read More" links. Scraping only the nav pages produces a knowledge base that
  cannot answer "how many floors does Burj Chishti have?".

* **No chunking, no embeddings, no vector store.** The finished file is ~10k
  tokens, so it fits whole into every request's context. Retrieval would add
  moving parts and a failure mode to solve a problem this project does not have.

* **Scraped data is merged with a hand-curated `overrides.yaml`.** The site
  omits facts a customer will certainly ask for (RERA numbers, unit
  configurations, pricing) and repeats a block of template filler on every
  project page. Overrides let the client correct and extend the knowledge base
  without touching this script or waiting on their webmaster.

Python notes for this file:
* ``from __future__ import annotations`` makes every annotation a string at
  runtime, so ``list[str]`` works without importing ``List``.
* ``@dataclass(frozen=True)`` builds an immutable value object — Python's
  closest equivalent to a Dart ``const`` class with ``final`` fields.
* ``xml.etree.ElementTree`` is stdlib and escapes text automatically. We never
  build XML with string concatenation; that is how injection bugs get in.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import httpx
import yaml
from bs4 import BeautifulSoup, Tag

BASE_URL: Final = "https://burjconstructions.com"
HERE: Final = Path(__file__).resolve().parent
RAW_DIR: Final = HERE / "raw"
OVERRIDES_PATH: Final = HERE / "overrides.yaml"
OUTPUT_PATH: Final = HERE / "knowledge_base.xml"

REQUEST_TIMEOUT: Final = 30.0
USER_AGENT: Final = "BurjKnowledgeBaseBuilder/1.0 (+https://burjconstructions.com)"

# Structural chrome repeated on every page. Removing these before extraction is
# what "strip nav/footer boilerplate" means in practice.
#
# Note the absence of "form": this is an ASP.NET WebForms site, which wraps the
# ENTIRE page body in a single <form runat="server">. Stripping forms the way
# you would on a normal site deletes every word of content.
BOILERPLATE_TAGS: Final = ("script", "style", "noscript", "header", "nav", "footer")
BOILERPLATE_IDS: Final = ("section-loading", "navbar", "footer")

# Headings whose content is purely images (floor plans, photo galleries), or is
# already captured as structured data. "address" is extracted into its own
# element, so keeping the heading too would duplicate it.
IMAGE_ONLY_HEADINGS: Final = frozenset({"floor plans", "gallery", "location", "address"})

# The homepage renders its "124 Years experience" stat as a bare <h1>124</h1>
# animated counter, which would otherwise become a section literally titled
# "124". Rewrite it into something that reads as a fact.
HEADING_ALIASES: Final = {"124": "124 Years of Experience — Since 1901"}

# Headings that introduce structured lists parsed separately from prose.
MANAGEMENT_HEADING: Final = "our management"
TESTIMONIALS_HEADING: Final = "our customer says"

# Detail pages express structured facts as "<p>Status : Completed</p>".
SPEC_PATTERN: Final = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,24}?)\s*:\s*(.+?)\s*$")

# Unit configurations appear ONLY in floor-plan image filenames
# (images/burj-ashrafi/2bhk.jpg). This is real on-page data, just badly marked up.
BHK_PATTERN: Final = re.compile(r"(\d+(?:\.\d+)?)\s*bhk", re.IGNORECASE)


class PageKind(StrEnum):
    """How a page should be parsed. Drives dispatch in `parse_page`."""

    COMPANY = "company"
    LISTING = "listing"
    PROJECT = "project"
    CONTACT = "contact"


@dataclass(frozen=True, slots=True)
class PageSpec:
    slug: str
    kind: PageKind

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.slug}.aspx"

    @property
    def raw_path(self) -> Path:
        return RAW_DIR / f"{self.slug}.html"


PAGES: Final[tuple[PageSpec, ...]] = (
    PageSpec("index", PageKind.COMPANY),
    PageSpec("about-us", PageKind.COMPANY),
    PageSpec("ongoing", PageKind.LISTING),
    PageSpec("completed", PageKind.LISTING),
    PageSpec("upcoming", PageKind.LISTING),
    PageSpec("contact-us", PageKind.CONTACT),
    # The four detail pages carrying ~85% of the content.
    PageSpec("burj-ashrafi", PageKind.PROJECT),
    PageSpec("burj-classic", PageKind.PROJECT),
    PageSpec("burj-qadri", PageKind.PROJECT),
    PageSpec("burj-chishti", PageKind.PROJECT),
)

# Which listing page a project detail page is reached from — this is the only
# place the site records whether a project is ongoing, completed, or upcoming.
LISTING_OF: Final = {
    "ongoing": "Ongoing",
    "completed": "Completed",
    "upcoming": "Upcoming",
}


@dataclass(frozen=True, slots=True)
class ListedProject:
    """A project named on a listing page, with its detail page if one exists.

    `slug` is None when the listing page names a project but links nowhere —
    Burj Ashrafi (Phase 2) is announced on ongoing.aspx with no page of its own.
    """

    name: str
    slug: str | None


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """A heading and the prose/bullets beneath it."""

    heading: str
    paragraphs: tuple[str, ...] = ()
    items: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.paragraphs and not self.items


@dataclass(slots=True)
class ParsedPage:
    slug: str
    kind: PageKind
    title: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    blocks: list[ContentBlock] = field(default_factory=list)
    address: str = ""
    configurations: list[str] = field(default_factory=list)
    listed_projects: list[ListedProject] = field(default_factory=list)
    management: list[str] = field(default_factory=list)
    testimonials: list[tuple[str, str]] = field(default_factory=list)


class BuildError(RuntimeError):
    """Raised when the source site has changed enough to invalidate the build."""


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def fetch_pages(*, offline: bool) -> None:
    """Download every page into `raw/`, or verify the cache when offline.

    `raw/` is committed to the repo so builds are reproducible without network
    access, and so a diff shows exactly what changed when the site is edited.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if offline:
        missing = [page.slug for page in PAGES if not page.raw_path.exists()]
        if missing:
            raise BuildError(f"--offline requested but raw HTML is missing for: {missing}")
        print(f"offline: using {len(PAGES)} cached pages from {RAW_DIR}")
        return

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=headers, follow_redirects=True) as client:
        for page in PAGES:
            response = client.get(page.url)
            response.raise_for_status()
            page.raw_path.write_text(response.text, encoding="utf-8")
            print(f"fetched {page.url} ({len(response.text):,} bytes)")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Collapse whitespace and normalise Unicode.

    The source HTML is full of newlines inside tags and non-breaking spaces;
    both would otherwise leak into the knowledge base and waste context tokens.
    """
    text = unicodedata.normalize("NFKC", text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_soup(html: str) -> BeautifulSoup:
    """Parse HTML and remove navigation, footer, and script chrome."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(list(BOILERPLATE_TAGS)):
        tag.decompose()
    for element_id in BOILERPLATE_IDS:
        node = soup.find(id=element_id)
        if isinstance(node, Tag):
            node.decompose()

    return soup


def _text_of(node: Tag) -> str:
    return _normalise(node.get_text(" ", strip=True))


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Pull the "Key : Value" spec block off a project detail page."""
    specs: dict[str, str] = {}

    for paragraph in soup.find_all("p"):
        if not isinstance(paragraph, Tag):
            continue
        text = _text_of(paragraph)
        # Guard on length: prose sentences contain colons too.
        if len(text) > 80:
            continue
        if (match := SPEC_PATTERN.match(text)) is None:
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        # "Rera : Download certificate" is a PDF link, not a number. Recording
        # it as a value would let the model claim a RERA registration exists.
        if value.lower() in {"-", "download certificate", "na", "n/a"}:
            continue
        specs[key.title()] = value

    return specs


def _extract_blocks(
    soup: BeautifulSoup, exclude: frozenset[str] = frozenset()
) -> list[ContentBlock]:
    """Group page content under its nearest preceding heading.

    The site nests content inconsistently, so rather than trusting the DOM tree
    we walk headings in document order and collect what follows each one.

    `exclude` holds headings already captured as structured data elsewhere —
    testimonial author names and management names. Without it, a customer review
    would be emitted as `<section title="Nadim Khan">` inside the company
    profile, and the model would reasonably conclude that Nadim Khan is a fact
    about the company rather than someone who left a review.
    """
    grouped: dict[str, tuple[list[str], list[str]]] = {}
    order: list[str] = []
    excluded = {name.casefold() for name in exclude}

    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        if not isinstance(heading, Tag):
            continue
        title = _text_of(heading)
        if not title or title.lower().rstrip(":") in IMAGE_ONLY_HEADINGS:
            continue
        if title.casefold() in excluded:
            continue
        title = HEADING_ALIASES.get(title.casefold(), title)

        paragraphs: list[str] = []
        items: list[str] = []

        for sibling in heading.find_all_next(["p", "li", "h1", "h2", "h3", "h4", "h5"]):
            if not isinstance(sibling, Tag):
                continue
            if sibling.name.startswith("h"):
                break  # reached the next heading; this block is done
            text = _text_of(sibling)
            if not text or (SPEC_PATTERN.match(text) and len(text) < 80):
                continue  # spec lines are captured separately as structured data
            (items if sibling.name == "li" else paragraphs).append(text)

        if title not in grouped:
            grouped[title] = ([], [])
            order.append(title)
        existing_paragraphs, existing_items = grouped[title]
        existing_paragraphs.extend(paragraphs)
        existing_items.extend(items)

    blocks: list[ContentBlock] = []
    for title in order:
        paragraphs, items = grouped[title]
        block = ContentBlock(
            heading=title,
            paragraphs=tuple(_dedupe(paragraphs)),
            items=tuple(_dedupe(items)),
        )
        if not block.is_empty:
            blocks.append(block)

    return blocks


def _dedupe(values: Iterable[str]) -> Iterator[str]:
    """Yield values once each, preserving order.

    Pages repeat content — "Amenities" appears twice on every project page, once
    as described bullets and once as bare labels. Duplicates in the knowledge
    base waste context and make the model over-weight whatever is repeated.
    """
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            yield value


def _nodes_after_heading(
    soup: BeautifulSoup, heading_text: str, want: tuple[str, ...]
) -> Iterator[Tag]:
    """Yield `want` tags following a named heading, stopping at the next h2."""
    for heading in soup.find_all(["h2", "h3"]):
        if not isinstance(heading, Tag) or _text_of(heading).casefold() != heading_text:
            continue
        for node in heading.find_all_next([*want, "h2"]):
            if not isinstance(node, Tag):
                continue
            if node.name == "h2":
                return
            yield node
        return


def _extract_management(soup: BeautifulSoup) -> list[str]:
    """Read the management team names from the homepage."""
    names = (_text_of(node) for node in _nodes_after_heading(soup, MANAGEMENT_HEADING, ("h4",)))
    return list(_dedupe(name for name in names if name))


def _extract_testimonials(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Read customer reviews as (author, quote) pairs.

    Kept separate from company facts and tagged as testimonials so the model can
    attribute them rather than restating opinion as fact.
    """
    testimonials: list[tuple[str, str]] = []

    for node in _nodes_after_heading(soup, TESTIMONIALS_HEADING, ("h3",)):
        author = _text_of(node)
        quote_node = node.find_next("p")
        quote = _text_of(quote_node) if isinstance(quote_node, Tag) else ""
        if author and quote:
            testimonials.append((author, quote))

    return testimonials


def _extract_address(soup: BeautifulSoup) -> str:
    """Find the paragraph following an 'Address:' heading."""
    for heading in soup.find_all(["h3", "h4", "h5"]):
        if not isinstance(heading, Tag):
            continue
        if _text_of(heading).lower().rstrip(":") != "address":
            continue
        sibling = heading.find_next("p")
        if isinstance(sibling, Tag):
            return _text_of(sibling)
    return ""


def _extract_configurations(soup: BeautifulSoup) -> list[str]:
    """Recover unit configurations from floor-plan image filenames.

    The site never states "1 BHK" in text — the only record is
    `images/burj-ashrafi/2bhk.jpg`. That is real published data, just marked up
    badly, and it answers one of the most common questions a buyer asks.
    """
    found: set[str] = set()
    for image in soup.find_all("img"):
        if not isinstance(image, Tag):
            continue
        src = str(image.get("src") or "")
        found.update(match.group(1) for match in BHK_PATTERN.finditer(src))

    return [f"{size} BHK" for size in sorted(found, key=float)]


def _extract_listing(soup: BeautifulSoup) -> list[ListedProject]:
    """Read project names and their detail-page links off a listing page.

    Names are paired with links **structurally** — by walking up from each
    heading to its enclosing card and finding the link inside — rather than by
    matching the name against the slug. Name matching looks tempting and fails
    immediately here: the site spells the same project "Burj Chisti" on the
    listing page and "burj-chishti" in the URL. Guessing at that similarity
    would silently drop the project's entire detail page from the knowledge
    base, which is exactly the kind of quiet data loss a scraper must not have.
    """
    projects: list[ListedProject] = []

    for heading in soup.find_all("h4"):
        if not isinstance(heading, Tag):
            continue
        name = _text_of(heading)
        if not name:
            continue

        projects.append(ListedProject(name=name, slug=_nearest_project_link(heading)))

    return projects


def _nearest_project_link(heading: Tag) -> str | None:
    """Find the project detail page linked from the same card as `heading`.

    Scans forward in document order and stops at the next heading, so a card
    with no link of its own cannot borrow the next card's link — which would
    silently file one project's content under another project's name.
    """
    for node in heading.find_all_next(["a", "h2", "h3", "h4", "h5"]):
        if not isinstance(node, Tag):
            continue
        if node.name != "a":
            break  # the next card began before any link appeared
        if (slug := _project_slug(str(node.get("href") or ""))) is not None:
            return slug

    # Some cards place the link before the heading; check the heading's own
    # container, which is the card itself, but go no wider than that.
    parent = heading.parent
    if isinstance(parent, Tag):
        for anchor in parent.find_all("a", href=True):
            if isinstance(anchor, Tag) and (slug := _project_slug(str(anchor.get("href") or ""))):
                return slug

    return None


def _project_slug(href: str) -> str | None:
    """Return the detail-page slug for a project link, or None if not one."""
    if href.startswith("burj-") and href.endswith(".aspx"):
        return href.removesuffix(".aspx")
    return None


def parse_page(page: PageSpec, html: str) -> ParsedPage:
    """Dispatch to the right extraction strategy for this page kind."""
    soup = _clean_soup(html)
    parsed = ParsedPage(slug=page.slug, kind=page.kind)

    heading = soup.find(["h1", "h2"])
    parsed.title = _text_of(heading) if isinstance(heading, Tag) else page.slug

    match page.kind:
        case PageKind.PROJECT:
            parsed.specs = _extract_specs(soup)
            parsed.blocks = _extract_blocks(soup)
            parsed.address = _extract_address(soup)
            parsed.configurations = _extract_configurations(soup)
        case PageKind.LISTING:
            parsed.listed_projects = _extract_listing(soup)
        case PageKind.COMPANY:
            parsed.management = _extract_management(soup)
            parsed.testimonials = _extract_testimonials(soup)
            already_captured = frozenset(parsed.management) | {
                author for author, _ in parsed.testimonials
            }
            parsed.blocks = _extract_blocks(soup, already_captured)
        case PageKind.CONTACT:
            parsed.blocks = _extract_blocks(soup)

    return parsed


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def load_overrides() -> dict[str, Any]:
    """Read the hand-curated corrections layer.

    `yaml.safe_load` — never `yaml.load` — because the unsafe loader can
    instantiate arbitrary Python objects from a YAML file.
    """
    if not OVERRIDES_PATH.exists():
        return {}
    data = yaml.safe_load(OVERRIDES_PATH.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise BuildError(f"{OVERRIDES_PATH.name} must contain a mapping at the top level")
    return data


def _drop_filler(blocks: list[ContentBlock], filler: list[str]) -> list[ContentBlock]:
    """Remove template paragraphs repeated verbatim across project pages.

    Every detail page opens with the same "A large part of our business is in
    the commercial real estate sector..." marketing block. Keeping four copies
    would teach the model that this text is important, when it says nothing
    about any specific project.
    """
    if not filler:
        return blocks

    prefixes = tuple(text.casefold()[:60] for text in filler)
    cleaned: list[ContentBlock] = []

    for block in blocks:
        kept = tuple(p for p in block.paragraphs if not p.casefold().startswith(prefixes))
        candidate = ContentBlock(heading=block.heading, paragraphs=kept, items=block.items)
        if not candidate.is_empty:
            cleaned.append(candidate)

    return cleaned


# ---------------------------------------------------------------------------
# XML rendering
# ---------------------------------------------------------------------------


def _add_text_element(parent: ET.Element, tag: str, text: str) -> None:
    if text:
        ET.SubElement(parent, tag).text = text


def _render_blocks(parent: ET.Element, blocks: Iterable[ContentBlock]) -> None:
    for block in blocks:
        section = ET.SubElement(parent, "section", {"title": block.heading})
        for paragraph in block.paragraphs:
            _add_text_element(section, "p", paragraph)
        if block.items:
            listing = ET.SubElement(section, "list")
            for item in block.items:
                _add_text_element(listing, "item", item)


def build_xml(pages: dict[str, ParsedPage], overrides: dict[str, Any]) -> ET.Element:
    """Assemble the XML-tagged knowledge base.

    Section tags are deliberately explicit (`<company_history>`,
    `<ongoing_projects>`, `<contact_info>`) rather than a flat text dump. That
    structure is Layer 2 of the grounding guardrail: it lets the system prompt
    reference sections by name, and lets the Layer 4 validator check that the
    model cited a section that actually exists.
    """
    filler: list[str] = list(overrides.get("drop_paragraphs", []))
    project_overrides: dict[str, Any] = overrides.get("projects", {}) or {}
    company_overrides: dict[str, Any] = overrides.get("company", {}) or {}

    root = ET.Element(
        "knowledge_base",
        {
            "company": "Burj Constructions",
            "source": BASE_URL,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        },
    )

    # --- Company profile -----------------------------------------------------
    profile = ET.SubElement(root, "company_profile")
    for key, value in company_overrides.items():
        if isinstance(value, list | dict):
            continue
        _add_text_element(profile, str(key), str(value))

    # --- History and about ---------------------------------------------------
    history = ET.SubElement(root, "company_history")
    _render_blocks(history, _drop_filler(pages["about-us"].blocks, filler))

    overview = ET.SubElement(root, "company_overview")
    _render_blocks(overview, _drop_filler(pages["index"].blocks, filler))

    if management := pages["index"].management:
        team = ET.SubElement(root, "management_team")
        for name in management:
            _add_text_element(team, "member", name)

    if testimonials := pages["index"].testimonials:
        reviews = ET.SubElement(root, "testimonials")
        for author, quote in testimonials:
            _add_text_element(
                ET.SubElement(reviews, "testimonial", {"author": author}), "quote", quote
            )

    # --- Projects, grouped by the listing page that references them ----------
    status_by_slug = _resolve_project_status(pages)

    for listing_slug, status_label in LISTING_OF.items():
        container = ET.SubElement(root, f"{listing_slug}_projects", {"status": status_label})
        listing = pages[listing_slug]

        for listed in listing.listed_projects:
            detail = pages.get(listed.slug) if listed.slug else None

            if detail is None:
                # Named on a listing page with no detail page of its own —
                # Burj Ashrafi (Phase 2). Emit the name plus any curated data
                # so the model can at least confirm the project exists.
                project = ET.SubElement(
                    container, "project", {"name": listed.name, "status": status_label}
                )
                _apply_project_overrides(project, project_overrides.get(_slugify(listed.name), {}))
                continue

            project = ET.SubElement(
                container,
                "project",
                {"name": detail.title or listed.name, "slug": detail.slug, "status": status_label},
            )
            _render_project(project, detail, filler, project_overrides.get(detail.slug, {}))

    # Any detail page not referenced by a listing page still gets included —
    # otherwise a nav change would silently drop content from the KB.
    orphans = [
        page
        for page in pages.values()
        if page.kind is PageKind.PROJECT and page.slug not in status_by_slug
    ]
    if orphans:
        container = ET.SubElement(root, "other_projects")
        for detail in orphans:
            project = ET.SubElement(
                container, "project", {"name": detail.title, "slug": detail.slug}
            )
            _render_project(project, detail, filler, project_overrides.get(detail.slug, {}))

    # --- Contact -------------------------------------------------------------
    contact = ET.SubElement(root, "contact_info")
    _render_blocks(contact, pages["contact-us"].blocks)
    for key, value in (overrides.get("contact", {}) or {}).items():
        _add_text_element(contact, str(key), str(value))

    # --- Curated FAQ ---------------------------------------------------------
    faq_entries: list[dict[str, str]] = overrides.get("faq", []) or []
    if faq_entries:
        faq = ET.SubElement(root, "faq")
        for entry in faq_entries:
            item = ET.SubElement(faq, "entry")
            _add_text_element(item, "question", str(entry.get("question", "")))
            _add_text_element(item, "answer", str(entry.get("answer", "")))

    return root


def _render_project(
    element: ET.Element,
    detail: ParsedPage,
    filler: list[str],
    project_override: dict[str, Any],
) -> None:
    specs = dict(detail.specs)
    specs.update(project_override.get("specs", {}) or {})

    if specs:
        spec_element = ET.SubElement(element, "specifications")
        for key, value in specs.items():
            ET.SubElement(spec_element, "spec", {"name": str(key)}).text = str(value)

    configurations = project_override.get("configurations") or detail.configurations
    if configurations:
        configs = ET.SubElement(element, "configurations")
        for configuration in configurations:
            _add_text_element(configs, "configuration", str(configuration))

    _add_text_element(element, "address", project_override.get("address") or detail.address)
    _render_blocks(element, _drop_filler(detail.blocks, filler))
    _apply_project_overrides(element, project_override)


def _apply_project_overrides(element: ET.Element, project_override: dict[str, Any]) -> None:
    """Attach curated notes the website does not publish."""
    for note in project_override.get("notes", []) or []:
        _add_text_element(element, "note", str(note))


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _resolve_project_status(pages: dict[str, ParsedPage]) -> dict[str, str]:
    """Map each project slug to the listing page that references it."""
    status: dict[str, str] = {}
    for listing_slug, label in LISTING_OF.items():
        for listed in pages[listing_slug].listed_projects:
            if listed.slug:
                status[listed.slug] = label
    return status


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(root: ET.Element) -> list[str]:
    """Sanity-check the generated KB. Empty list means the build is trustworthy.

    This exists because a scraper failure is silent by nature: if the site's
    markup changes, extraction quietly returns nothing and the assistant starts
    answering "I don't have information about that" to every question. These
    checks turn that into a loud build failure.
    """
    problems: list[str] = []

    required = ("company_history", "contact_info", "completed_projects")
    for section in required:
        if root.find(section) is None:
            problems.append(f"missing required section <{section}>")

    projects = root.findall(".//project")
    if len(projects) < 4:
        problems.append(f"expected at least 4 projects, found {len(projects)}")

    for project in projects:
        name = project.get("name", "?")
        if project.get("slug") and project.find("specifications") is None:
            problems.append(f"project {name!r} has no specifications")

    word_count = sum(len((node.text or "").split()) for node in root.iter())
    if word_count < 1_000:
        problems.append(f"knowledge base has only {word_count} words; extraction likely broke")

    contact = root.find("contact_info")
    if contact is not None:
        contact_text = " ".join((node.text or "") for node in contact.iter())
        if "@" not in contact_text:
            problems.append("contact_info contains no email address")

    return problems


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build(*, offline: bool) -> str:
    fetch_pages(offline=offline)

    pages = {
        page.slug: parse_page(page, page.raw_path.read_text(encoding="utf-8")) for page in PAGES
    }
    root = build_xml(pages, load_overrides())

    if problems := validate(root):
        raise BuildError(
            "generated knowledge base failed validation:\n  - " + "\n  - ".join(problems)
        )

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--offline", action="store_true", help="rebuild from cached raw/ HTML")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed knowledge_base.xml is stale (for CI)",
    )
    args = parser.parse_args(argv)

    try:
        xml = build(offline=args.offline or args.check)
    except (BuildError, httpx.HTTPError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        # The timestamp changes every run, so compare everything else.
        if _without_timestamp(current) != _without_timestamp(xml):
            print("error: knowledge_base.xml is stale — run `make kb`", file=sys.stderr)
            return 1
        print("knowledge_base.xml is up to date")
        return 0

    OUTPUT_PATH.write_text(xml, encoding="utf-8")
    words = len(re.sub(r"<[^>]+>", " ", xml).split())
    print(f"\nwrote {OUTPUT_PATH.relative_to(HERE.parent)} — {words:,} words, {len(xml):,} bytes")
    return 0


def _without_timestamp(xml: str) -> str:
    return re.sub(r'generated_at="[^"]*"', "", xml)


if __name__ == "__main__":
    raise SystemExit(main())
