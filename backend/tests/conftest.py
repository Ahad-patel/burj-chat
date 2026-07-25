"""Shared fixtures.

The knowledge base fixture is built from the **real committed
knowledge_base.xml**, not a toy stub. That is deliberate: the guardrails are
tuned against this specific corpus, and a synthetic fixture would let the filter
pass tests while failing on the content it actually ships with.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from defusedxml.ElementTree import parse as parse_xml

from app.domain.entities.knowledge_base import ContactDetails, KnowledgeBase, KnowledgeSection
from app.domain.ports.llm_client import LLMRequest, LLMResponse, TokenUsage

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_XML = REPO_ROOT / "knowledge-base" / "knowledge_base.xml"


def _section_text(element: ET.Element) -> str:
    """Flatten a section's text, attributes included.

    Attributes carry real facts here — `<project name="Burj Qadri"
    status="Completed">` — so ignoring them would leave project names out of the
    vocabulary that Layer 1 matches against.
    """
    parts: list[str] = []
    for node in element.iter():
        parts.extend(str(value) for value in node.attrib.values())
        if node.text and node.text.strip():
            parts.append(node.text.strip())
    return " ".join(parts)


def load_real_knowledge_base() -> KnowledgeBase:
    """Build a domain KnowledgeBase from the committed XML.

    Mirrors what `infrastructure/kb/` will do in Phase 4. Kept here rather than
    imported from infrastructure so the domain suite has no outward dependency.
    """
    root = parse_xml(KB_XML).getroot()
    assert root is not None

    sections = tuple(KnowledgeSection(name=child.tag, text=_section_text(child)) for child in root)

    return KnowledgeBase.build(
        document=KB_XML.read_text(encoding="utf-8"),
        sections=sections,
        contact=ContactDetails(phone="+91 98199 62446", email="Latifcorp@aol.com"),
    )


@pytest.fixture(scope="session")
def knowledge_base() -> KnowledgeBase:
    return load_real_knowledge_base()


class FakeLLMClient:
    """An in-memory `LLMClient`, so no test ever touches the network.

    It has no base class and imports nothing from infrastructure — it satisfies
    the port purely by having a matching `generate` method, which is the whole
    point of using a `Protocol`. `test_fake_client_satisfies_the_port` asserts
    mypy agrees.
    """

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses) or ["{}"]
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        text = self._responses[min(len(self.requests) - 1, len(self._responses) - 1)]
        return LLMResponse(
            text=text,
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            stop_reason="stop",
            model="fake-model",
        )

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def was_called(self) -> bool:
        return bool(self.requests)


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()
