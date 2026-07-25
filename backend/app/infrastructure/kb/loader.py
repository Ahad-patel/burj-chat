"""Load `knowledge_base.xml` into the domain's `KnowledgeBase` entity.

This lives in infrastructure, not in the domain, for one concrete reason:
parsing XML safely needs `defusedxml`, and the domain layer takes no
third-party dependencies. The loader turns a file into plain sections; the
entity turns sections into the indexes the guardrails run against.

Loaded **once at startup**. The knowledge base is ~21KB and changes when the
client's website changes — re-reading it per request would buy nothing and add
a disk hit plus a reparse to every visitor question.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Final

from defusedxml.ElementTree import ParseError
from defusedxml.ElementTree import parse as parse_xml

from app.core.logging import get_logger
from app.domain.entities.knowledge_base import (
    ContactDetails,
    KnowledgeBase,
    KnowledgeSection,
)
from app.domain.errors import KnowledgeBaseError

logger = get_logger(__name__)

#: Where the fallback message's contact details come from. These are read out
#: of the knowledge base rather than hardcoded, so changing the sales number is
#: an edit to overrides.yaml — not a code change and a redeploy.
_CONTACT_SECTION: Final = "contact_info"
_PHONE_FIELDS: Final = ("phone", "whatsapp")
_EMAIL_FIELDS: Final = ("email",)


def load_knowledge_base(path: Path) -> KnowledgeBase:
    """Parse the knowledge base file into a domain entity.

    Raises `KnowledgeBaseError` on anything unusable. Failing at startup is the
    point: a service that boots with an empty knowledge base answers every
    question with the fallback while every health check stays green.
    """
    if not path.exists():
        raise KnowledgeBaseError(f"knowledge base not found at {path}; run `make kb`")

    try:
        # defusedxml, not stdlib ElementTree: this file is committed and trusted
        # today, but a parser hardened against entity-expansion attacks costs
        # nothing and removes the whole class of problem from a server process.
        root = parse_xml(path).getroot()
    except ParseError as error:
        raise KnowledgeBaseError(f"knowledge base at {path} is not valid XML: {error}") from error

    if root is None:
        raise KnowledgeBaseError(f"knowledge base at {path} has no root element")

    sections = tuple(
        KnowledgeSection(name=child.tag, text=_flatten(child))
        for child in root
        if _flatten(child).strip()
    )

    if not sections:
        raise KnowledgeBaseError(f"knowledge base at {path} contains no readable sections")

    knowledge_base = KnowledgeBase.build(
        document=path.read_text(encoding="utf-8"),
        sections=sections,
        contact=_extract_contact(root),
    )

    logger.info(
        "knowledge_base_loaded",
        path=str(path),
        sections=len(sections),
        words=knowledge_base.word_count,
        distinct_numbers=len(knowledge_base.numbers),
        has_contact=knowledge_base.contact.is_complete,
    )

    return knowledge_base


def _flatten(element: ET.Element) -> str:
    """Collapse an element's text and attribute values into one string.

    Attributes carry real facts in this document — `<project name="Burj Qadri"
    status="Completed">` — so dropping them would leave project names out of
    the vocabulary Layer 1 matches against and out of Layer 4's number index.
    """
    parts: list[str] = []

    for node in element.iter():
        parts.extend(str(value) for value in node.attrib.values())
        if node.text and node.text.strip():
            parts.append(node.text.strip())

    return " ".join(parts)


def _extract_contact(root: ET.Element) -> ContactDetails:
    """Pull the sales phone and email out of `<contact_info>`."""
    section = root.find(_CONTACT_SECTION)
    if section is None:
        logger.warning("knowledge_base_missing_contact_section", section=_CONTACT_SECTION)
        return ContactDetails()

    found = {
        node.tag: node.text.strip() for node in section.iter() if node.text and node.text.strip()
    }

    return ContactDetails(
        phone=_first(found, _PHONE_FIELDS),
        email=_first(found, _EMAIL_FIELDS),
    )


def _first(values: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        if value := values.get(key):
            return value
    return ""
