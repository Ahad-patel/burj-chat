"""Vocabulary and patterns Layer 1 matches against.

Kept apart from the filter logic so the rules are reviewable as data. A
non-programmer at the client can read this file and tell you whether the
competitor list is current; nobody can do that with regexes buried in control
flow.

Every pattern here is written for **precision over recall**. Layer 1 rejects
only what it is certain about — see `relevance.py` for why that bias is
deliberate.
"""

from __future__ import annotations

import re
from typing import Final

#: Core real-estate and company vocabulary. A question containing any of these
#: is plausibly in scope even when it names no project — "how much is a 2BHK?"
#: has no company keyword in it but is exactly what a customer asks.
DOMAIN_TERMS: Final = frozenset(
    {
        # Company and projects
        "burj",
        "ashrafi",
        "classic",
        "qadri",
        "chishti",
        "chisti",
        "latif",
        "constructions",
        "construction",
        "builder",
        "builders",
        "developer",
        # Property vocabulary
        "flat",
        "flats",
        "apartment",
        "apartments",
        "home",
        "homes",
        "house",
        "property",
        "properties",
        "unit",
        "units",
        "bhk",
        "bedroom",
        "bedrooms",
        "carpet",
        "builtup",
        "sqft",
        "storey",
        "storeys",
        "floor",
        "floors",
        "tower",
        "building",
        "residential",
        "commercial",
        "duplex",
        "jodi",
        # Buying process
        "price",
        "prices",
        "pricing",
        "cost",
        "costs",
        "rate",
        "rates",
        "booking",
        "book",
        "buy",
        "buying",
        "purchase",
        "sale",
        "sell",
        "available",
        "availability",
        "possession",
        "ready",
        "loan",
        "emi",
        "payment",
        "brochure",
        "visit",
        "site",
        "enquiry",
        "inquiry",
        "contact",
        "discount",
        "offer",
        "negotiable",
        "handover",
        "maintenance",
        "society",
        # Timeline. "What's coming up next?" is an ordinary question about
        # upcoming projects and contains none of the words above — a rejection
        # here is a lost customer, which is the failure mode Layer 1 must avoid.
        "coming",
        "next",
        "soon",
        "launch",
        "launching",
        "future",
        "planned",
        "timeline",
        "schedule",
        "when",
        # Interior and layout vocabulary
        "kitchen",
        "bathroom",
        "toilet",
        "balcony",
        "deck",
        "furnished",
        "flooring",
        "tiles",
        "layout",
        "plan",
        "plans",
        "view",
        "vastu",
        # Ways of reaching the company
        "email",
        "phone",
        "call",
        "whatsapp",
        "number",
        "timing",
        "timings",
        "hours",
        "open",
        "photos",
        "images",
        "video",
        "tour",
        # Compliance and specs
        "rera",
        "registration",
        "certificate",
        "approved",
        "legal",
        "documents",
        "amenity",
        "amenities",
        "parking",
        "lift",
        "lifts",
        "elevator",
        "security",
        "safety",
        "fire",
        "water",
        "power",
        "backup",
        "gym",
        "gazebo",
        "terrace",
        "refuge",
        "earthquake",
        "specification",
        "specifications",
        "facilities",
        "facility",
        # Company profile
        "company",
        "history",
        "founded",
        "experience",
        "management",
        "team",
        "director",
        "office",
        "address",
        "location",
        "located",
        "project",
        "projects",
        "ongoing",
        "completed",
        "upcoming",
        "delivered",
        # Locality
        "mumbai",
        "byculla",
        "dongri",
        "agripada",
        "kambekar",
        "mohammed",
        "ali",
        "road",
        "street",
        "sobo",
        "maharashtra",
    }
)

#: Attempts to override the assistant's instructions. Matching any of these is
#: sufficient grounds to refuse without ever calling the model — which is what
#: makes Layer 1 un-injectable for the cases it does catch.
INJECTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\bignore\s+(all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+)*(instruction|rule|prompt|direction|guideline)",
        re.I,
    ),
    re.compile(
        r"\b(disregard|forget|override|bypass|discard)\s+(all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+)*(instruction|rule|prompt|context|guideline|everything|training)",
        re.I,
    ),
    re.compile(r"\byou\s+are\s+(now|no\s+longer)\b", re.I),
    re.compile(r"\b(act|behave|pretend|roleplay|role-play)\s+(as|like|to\s+be)\b", re.I),
    re.compile(r"\b(system|developer|initial|original)\s+(prompt|message|instruction)", re.I),
    re.compile(
        r"\b(reveal|show|print|repeat|output|tell\s+me)\s+(me\s+)?(your|the)\s+(prompt|instruction|rule|system)",
        re.I,
    ),
    re.compile(r"\b(new|updated)\s+(instruction|rule|persona|role)s?\b", re.I),
    re.compile(r"\bdo\s+anything\s+now\b|\bDAN\s+mode\b", re.I),
    re.compile(r"\bjailbreak|\bdeveloper\s+mode\b", re.I),
    re.compile(r"\bwithout\s+(any\s+)?(restriction|filter|limitation|guardrail)", re.I),
    re.compile(r"</?(system|instruction)s?>", re.I),
)

#: Requests for generated content. The assistant answers questions about a
#: construction company; it is not a general writing tool, and letting it act
#: like one is both off-brand and a standing invitation to abuse the endpoint.
CREATIVE_REQUEST_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\bwrite\s+(me\s+)?(a|an|some)?\s*(poem|song|story|essay|joke|rap|haiku|script|letter|email|article|blog)",
        re.I,
    ),
    re.compile(
        r"\b(compose|generate|create)\s+(me\s+)?(a|an|some)?\s*(poem|song|story|essay|joke|script|code|program)",
        re.I,
    ),
    re.compile(r"\bwrite\s+(me\s+)?(some\s+)?(python|java|javascript|sql|html|c\+\+|code)\b", re.I),
    re.compile(r"\btranslate\s+.{0,40}\b(into|to)\s+\w+", re.I),
    re.compile(r"\b(summarize|summarise)\s+(this|the\s+following)\b", re.I),
)

#: Unambiguous general-knowledge questions. Deliberately narrow: "weather" alone
#: would wrongly reject "is the facade weather resistant?", so each pattern
#: requires the surrounding shape of a general-knowledge query.
OFF_DOMAIN_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bwhat(?:'s|\s+is)\s+the\s+weather\b", re.I),
    re.compile(r"\bweather\s+(in|at|for|today|tomorrow|forecast)\b", re.I),
    re.compile(r"\b(temperature|forecast)\s+(in|at|today|tomorrow)\b", re.I),
    re.compile(
        r"\bwho\s+is\s+the\s+(prime\s+minister|president|ceo\s+of|king|queen|chief\s+minister)\b",
        re.I,
    ),
    re.compile(r"\bwhat\s+is\s+the\s+capital\s+of\b", re.I),
    re.compile(r"\bwho\s+(won|is\s+winning)\b.*\b(match|cup|election|game|series)\b", re.I),
    re.compile(r"\b(cricket|football|ipl|world\s+cup)\s+(score|match|result)", re.I),
    re.compile(r"\b(recipe|how\s+to\s+cook|how\s+do\s+i\s+cook)\b", re.I),
    re.compile(r"\bstock\s+(price|market)\s+(of|for|today)\b", re.I),
    re.compile(r"\b(bitcoin|crypto|cryptocurrency)\s+(price|rate)\b", re.I),
    re.compile(r"\bwhat\s+is\s+\d+\s*[\+\-\*/x]\s*\d+", re.I),
    re.compile(r"\bmedical\s+advice\b|\bdiagnos(e|is)\b", re.I),
)

#: Competitors and unrelated developers. The assistant must not discuss
#: property it did not build — a comparison it invents is both a factual risk
#: and a commercial one for the client.
COMPETITOR_TERMS: Final = frozenset(
    {
        "dlf",
        "lodha",
        "godrej",
        "oberoi",
        "hiranandani",
        "raheja",
        "prestige",
        "brigade",
        "sobha",
        "puravankara",
        "kolte",
        "mahindra",
        "tata housing",
        "adani realty",
        "piramal",
        "rustomjee",
        "kalpataru",
        "runwal",
        "wadhwa",
        "shapoorji",
        "ajmera",
        "dosti",
        "sunteck",
        "nirmal",
        "sheth",
        "99acres",
        "magicbricks",
        "housing.com",
        "nobroker",
        "squareyards",
    }
)

#: Patterns applied to a generated *answer*, not to the visitor's question.
#: These catch the highest-damage categories of off-topic output if a jailbreak
#: ever gets past Layer 1.
#:
#: Deliberately narrow. A general "does this answer look on-topic?" check was
#: tried and rejected: measuring how much of an answer's vocabulary appears in
#: the knowledge base scored ordinary replies like "I'd be happy to help" and
#: "That project is finished" at 0.29-0.40 — below any threshold that also
#: caught off-topic prose. It would have left the assistant unable to greet a
#: visitor. These patterns match statements no legitimate answer ever makes.
OFF_DOMAIN_ANSWER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(the\s+)?(prime\s+minister|president|chief\s+minister)\s+of\b", re.I),
    re.compile(r"\bthe\s+capital\s+of\s+\w+\s+is\b", re.I),
    re.compile(
        r"\bweather\s+(in|at|today|tomorrow)\b.*\b(degrees?|sunny|rainy|cloudy|humid)\b", re.I
    ),
    re.compile(r"\b\d+\s*degrees?\s*(celsius|c\b|fahrenheit|f\b)", re.I),
    re.compile(r"\broses\s+are\s+red\b", re.I),
    re.compile(r"\b(here('s| is)\s+(a|your)\s+(poem|song|story|joke|recipe|essay))\b", re.I),
    re.compile(r"\b(ingredients|preheat\s+the\s+oven|tablespoons?|teaspoons?)\b", re.I),
    re.compile(r"\bmy\s+(system\s+)?(instructions?|system\s+prompt)\s+(are|is|was|were)\b", re.I),
    re.compile(r"\byou\s+are\s+the\s+official\s+website\s+assistant\b", re.I),
)

#: Short openers that should reach the model so it can greet naturally, even
#: though they carry no topic words at all.
GREETING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*(hi|hey|hello|yo|hiya|namaste|salaam|assalam[ou]?\s*alaikum)\b", re.I),
    re.compile(r"^\s*good\s+(morning|afternoon|evening|day)\b", re.I),
    re.compile(
        r"^\s*(thanks|thank\s+you|thankyou|ty|ok|okay|got\s+it|great|cool|bye|goodbye)\b", re.I
    ),
    re.compile(r"^\s*(who\s+are\s+you|what\s+can\s+you\s+do|help)\s*\??\s*$", re.I),
)

#: Words that make a short message a follow-up to the previous turn rather than
#: a new topic — "and the price?", "what about that one?".
CONTINUATION_MARKERS: Final = frozenset(
    {
        "it",
        "its",
        "it's",
        "that",
        "this",
        "those",
        "these",
        "they",
        "them",
        "there",
        "one",
        "ones",
        "same",
        "also",
        "and",
        "what",
        "about",
        "how",
        "why",
        "when",
        "where",
        "which",
        "more",
        "else",
        "other",
        "another",
        "yes",
        "no",
        "sure",
        "please",
        "the",
        "any",
    }
)

#: A message at or below this many words is treated as possibly anaphoric.
MAX_FOLLOWUP_WORDS: Final = 8
