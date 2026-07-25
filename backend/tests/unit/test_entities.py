"""Entity invariants: Message, Conversation, KnowledgeBase."""

from __future__ import annotations

import pytest

from app.domain.entities.conversation import MAX_MESSAGES, Conversation
from app.domain.entities.knowledge_base import (
    ContactDetails,
    KnowledgeBase,
    KnowledgeSection,
    extract_numbers,
    extract_terms,
    normalise_number,
)
from app.domain.entities.message import MAX_MESSAGE_LENGTH, Message, Role
from app.domain.errors import ConversationLimitError, InvalidMessageError, KnowledgeBaseError


class TestMessage:
    def test_factories_set_the_right_role(self) -> None:
        assert Message.user("hello").role is Role.USER
        assert Message.assistant("hi").role is Role.ASSISTANT

    @pytest.mark.parametrize("content", ["", "   ", "\n\t "])
    def test_blank_content_is_rejected(self, content: str) -> None:
        with pytest.raises(InvalidMessageError, match="empty"):
            Message.user(content)

    def test_overlong_content_is_rejected(self) -> None:
        """Caps injection payload size and bounds input-token spend."""
        with pytest.raises(InvalidMessageError, match="exceeds"):
            Message.user("a" * (MAX_MESSAGE_LENGTH + 1))

    def test_content_at_the_limit_is_accepted(self) -> None:
        assert len(Message.user("a" * MAX_MESSAGE_LENGTH).content) == MAX_MESSAGE_LENGTH

    def test_messages_are_immutable(self) -> None:
        """Nothing downstream may rewrite what the visitor actually said."""
        message = Message.user("original")

        with pytest.raises(AttributeError):
            message.content = "tampered"  # type: ignore[misc]

    def test_there_is_no_system_role(self) -> None:
        """A constructible system message would be an injection vector.

        If `Role.SYSTEM` existed, anything that appends to a conversation could
        smuggle in instructions. The system prompt travels separately, in
        `LLMRequest.system_prompt`.
        """
        assert {role.value for role in Role} == {"user", "assistant"}


class TestConversation:
    def test_append_returns_a_new_conversation(self) -> None:
        original = Conversation(id="c1")
        updated = original.append(Message.user("hello"))

        assert original.is_empty
        assert len(updated.messages) == 1
        assert original is not updated

    def test_blank_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="conversation id"):
            Conversation(id="  ")

    def test_appending_beyond_the_ceiling_is_rejected(self) -> None:
        conversation = Conversation(
            id="c1", messages=tuple(Message.user(f"m{i}") for i in range(MAX_MESSAGES))
        )

        with pytest.raises(ConversationLimitError):
            conversation.append(Message.user("one too many"))

    def test_constructing_beyond_the_ceiling_is_rejected(self) -> None:
        with pytest.raises(ConversationLimitError):
            Conversation(
                id="c1", messages=tuple(Message.user(f"m{i}") for i in range(MAX_MESSAGES + 1))
            )

    def test_recent_returns_the_tail_oldest_first(self) -> None:
        conversation = Conversation(
            id="c1", messages=tuple(Message.user(f"m{i}") for i in range(10))
        )

        recent = conversation.recent(3)

        assert [m.content for m in recent] == ["m7", "m8", "m9"]

    @pytest.mark.parametrize("turns", [0, -1])
    def test_recent_with_non_positive_turns_is_empty(self, turns: int) -> None:
        conversation = Conversation(id="c1").append(Message.user("hello"))

        assert conversation.recent(turns) == ()

    def test_has_prior_exchange_requires_an_assistant_reply(self) -> None:
        """Layer 1's follow-up exemption hangs on this being strict."""
        conversation = Conversation(id="c1").append(Message.user("hello"))
        assert not conversation.has_prior_exchange

        replied = conversation.append(Message.assistant("hi there"))
        assert replied.has_prior_exchange

    def test_last_message_accessors(self) -> None:
        conversation = (
            Conversation(id="c1")
            .append(Message.user("first"))
            .append(Message.assistant("reply"))
            .append(Message.user("second"))
        )

        assert conversation.last_user_message is not None
        assert conversation.last_user_message.content == "second"
        assert conversation.last_assistant_message is not None
        assert conversation.last_assistant_message.content == "reply"

    def test_last_message_accessors_on_empty_conversation(self) -> None:
        conversation = Conversation(id="c1")

        assert conversation.last_user_message is None
        assert conversation.last_assistant_message is None


class TestKnowledgeBase:
    def test_build_derives_the_guardrail_indexes(self) -> None:
        kb = KnowledgeBase.build(
            document="<kb/>",
            sections=(KnowledgeSection(name="projects", text="Burj Qadri has 22 storeys"),),
        )

        assert kb.section_names == {"projects"}
        assert "qadri" in kb.vocabulary
        assert "22" in kb.numbers

    def test_empty_document_is_rejected(self) -> None:
        with pytest.raises(KnowledgeBaseError, match="empty"):
            KnowledgeBase(document="  ", sections=(KnowledgeSection("a", "b"),))

    def test_no_sections_is_rejected(self) -> None:
        with pytest.raises(KnowledgeBaseError, match="no sections"):
            KnowledgeBase(document="<kb/>", sections=())

    def test_has_section(self, knowledge_base: KnowledgeBase) -> None:
        assert knowledge_base.has_section("contact_info")
        assert not knowledge_base.has_section("nonexistent_section")

    def test_real_knowledge_base_indexes_are_populated(self, knowledge_base: KnowledgeBase) -> None:
        """Guards against a fixture that silently loads nothing."""
        assert knowledge_base.word_count > 1_000
        assert "burj" in knowledge_base.vocabulary
        assert "ashrafi" in knowledge_base.vocabulary
        assert len(knowledge_base.numbers) > 20

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1,00,000", "100000"),
            ("1.75", "1.75"),
            ("1.750", "1.75"),
            ("400,010", "400010"),
            ("32", "32"),
            ("1.00", "1"),
        ],
    )
    def test_number_normalisation(self, raw: str, expected: str) -> None:
        """Formatting differences must not make Layer 4 reject correct answers."""
        assert normalise_number(raw) == expected

    def test_extract_numbers_finds_figures_in_prose(self) -> None:
        assert extract_numbers("G+32 storeys over 1.75 lakh sq.ft") == {"32", "1.75"}

    def test_extract_terms_drops_stopwords_and_short_tokens(self) -> None:
        terms = extract_terms("What about the Burj Qadri amenities")

        assert "burj" in terms
        assert "qadri" in terms
        assert "amenities" in terms
        assert "what" not in terms
        assert "the" not in terms


class TestContactDetails:
    def test_is_complete_requires_both_fields(self) -> None:
        assert ContactDetails(phone="1", email="a@b.c").is_complete
        assert not ContactDetails(phone="1").is_complete
        assert not ContactDetails(email="a@b.c").is_complete
        assert not ContactDetails().is_complete


class TestMessageRoleGuard:
    def test_a_non_role_value_is_rejected(self) -> None:
        """StrEnum compares equal to its string value, so a bare "user" would
        otherwise slip through and break `is Role.USER` identity checks."""
        with pytest.raises(InvalidMessageError, match="role must be a Role"):
            Message(role="user", content="hello")  # type: ignore[arg-type]

    def test_is_user_property(self) -> None:
        assert Message.user("hi").is_user
        assert not Message.assistant("hi").is_user
