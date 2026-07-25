# Burj Constructions AI Assistant

A strictly grounded AI assistant for [burjconstructions.com](https://burjconstructions.com),
embeddable into their existing ASP.NET WebForms site via a single script tag.

The assistant answers **only** from a curated knowledge base built from the company's own
website. Questions outside that scope receive a fallback pointing to the sales team — never a
general-knowledge answer.

> **Not fine-tuning.** The knowledge base is injected into the model's context at request time
> (grounding). No model is trained or fine-tuned; there is no ML pipeline and no GPU.

---

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Architecture plan | ✅ Done |
| 1 | Scaffold, tooling, CI | ✅ Done |
| 2 | Knowledge base builder | ✅ Done |
| 3 | Domain layer + `LLMClient` port | ✅ Done |
| 4 | LLM adapters + conversation service | ⬜ Next |
| 5 | API layer | ⬜ |
| 6 | Embeddable widget | ⬜ |
| 7 | Voice (optional) | ⬜ |

---

## Quick start

```bash
make setup          # install Python 3.12 + dependencies, create .env
# add GEMINI_API_KEY to .env — free tier: https://aistudio.google.com/apikey
make ci             # lint, types, tests — exactly what CI runs
```

| Command | Does |
|---|---|
| `make setup` | Install the pinned interpreter and all dependencies |
| `make lint` | ruff lint + security rules + format check |
| `make types` | mypy, strict mode |
| `make test` | pytest |
| `make cov` | pytest with coverage |
| `make ci` | All of the above — mirrors the pipeline |
| `make kb` | Regenerate the knowledge base from the live site |
| `make run` | Start the API on :8000 with auto-reload |

---

## Architecture

Clean Architecture with strictly inward-only dependencies.

```
        api  ─────┐
     services ────┼──▶  domain  (stdlib only — no framework, no SDK)
 infrastructure ──┘         ▲
                            │ declares
                        ports/LLMClient
                            ▲ implements
              GeminiClient ─┴─ AnthropicClient
```

The domain layer imports nothing but the standard library. That constraint is what makes the
guardrails testable without a network call, and the LLM provider swappable by changing one
environment variable.

**It is enforced, not documented.**
[backend/tests/architecture/test_layer_boundaries.py](backend/tests/architecture/test_layer_boundaries.py)
parses every domain module's syntax tree and fails the build on a forbidden import. A second test
asserts no module outside the two adapters imports a vendor SDK — which is what makes
"swapping providers costs one env var" a verifiable claim rather than an aspiration.

### Swapping the LLM provider

```bash
LLM_PROVIDER=gemini      # Google AI Studio free tier (development default)
LLM_PROVIDER=anthropic   # Claude (production option)
```

Nothing else changes. No code, no config, no redeploy of the widget.

### The grounding guardrail

Four independent layers, so no single bypass defeats the system:

| Layer | Where | Guarantees |
|---|---|---|
| 1. Relevance pre-filter | [relevance.py](backend/app/domain/guardrails/relevance.py) | Blocks injection, creative requests, competitors, and blatant general-knowledge questions **before any model call** — nothing to persuade |
| 2. Structured context | [system_prompt.py](backend/app/domain/prompts/system_prompt.py) | Knowledge base injected as named XML sections, so Layer 4 can verify citations |
| 3. Strict system prompt | [system_prompt.py](backend/app/domain/prompts/system_prompt.py) | Refusal rules with the exact fallback wording, plus the JSON output contract |
| 4. Response validation | [validator.py](backend/app/domain/guardrails/validator.py) | Rejects invented figures, fake section citations, and competitor mentions. Fails closed |

**Each layer is deliberately partial, and the docs say which part.** Layer 1
cannot be airtight without rejecting real customers. Layer 4 checks *factual
grounding*, not topicality — a general vocabulary-overlap test was implemented,
measured, and removed because it scored ordinary replies like *"I'd be happy to
help"* below any threshold that also caught off-topic prose. Overlapping
partial guarantees beat one layer pretending to be complete.

The sharpest check is numeric: **every multi-digit figure in an answer must
appear in the knowledge base.** Invented prices, possession dates, and RERA
registration numbers are exactly the fabrications that would harm the client,
and every one of them is a multi-digit number absent from the corpus.

Layer 1 is tuned for **high precision, not high recall**: it rejects only what it is certain
about, and lets ambiguous questions through to layers 3 and 4. A filter aggressive enough to
catch everything would also reject *"how much does a 2BHK cost?"* — a real customer question with
no company keyword in it. Cost control and defence in depth are Layer 1's job; the semantic
decision belongs downstream.

---

## Layout

```
├── backend/
│   ├── app/
│   │   ├── api/v1/           # FastAPI routers — thin, no business logic
│   │   ├── core/             # config, composition root, rate limiting, logging
│   │   ├── domain/           # PURE business logic — zero framework/SDK imports
│   │   │   ├── entities/     ├── guardrails/
│   │   │   ├── ports/        └── prompts/
│   │   ├── services/         # use-cases orchestrating domain + infrastructure
│   │   ├── infrastructure/   # llm/ adapters, kb/ loader
│   │   └── schemas/          # Pydantic request/response models (the only Pydantic)
│   └── tests/
│       ├── unit/             # domain layer, LLM mocked, fast
│       ├── integration/      # real provider, marked and skippable
│       ├── security/         # prompt-injection and guardrail-bypass attempts
│       └── architecture/     # dependency-rule enforcement
├── knowledge-base/
│   ├── raw/                  # scraped page content
│   ├── overrides.yaml        # hand-curated corrections; wins over scraped data
│   ├── build_kb.py           # scraper → structured KB builder
│   └── knowledge_base.xml    # generated, committed, XML-tagged
├── widget/                   # TypeScript + Vite → single self-contained JS file
└── .github/workflows/ci.yml
```

`pyproject.toml` sits at the repo root rather than in `backend/` so that one lockfile, one ruff
config, and one mypy config cover both the backend and the knowledge-base builder. The package
still lives at `backend/app` and imports as `app`.

---

## Quality gates

CI fails the build on any violation.

| Gate | Tool |
|---|---|
| Lint, formatting, security rules | `ruff` (the `S` ruleset **is** bandit, ported — running both would duplicate findings) |
| Static types | `mypy --strict` |
| Tests + coverage | `pytest` — ≥80% overall, ≥95% on `domain/guardrails/` |
| Architecture | AST-based dependency-rule tests |
| Secret scanning | `gitleaks` over full history |
| Dependency CVEs | `pip-audit` against the exported lockfile |
| SAST | `semgrep` — advisory, non-blocking until its signal rate is proven on this repo |

---

## Security

- All secrets in environment variables; `.env` is gitignored and gitleaks scans history for it
- The LLM API key is **server-side only** — the widget never receives it
- Rate limiting per IP and per session, sized to cap LLM spend rather than merely deter abuse
- CORS locked to `burjconstructions.com` origins; no wildcards in production
- Pydantic validation at every endpoint boundary
- Security headers (CSP, HSTS, X-Content-Type-Options) on all responses
- Errors never leak stack traces to clients
- **No database and no PII at rest.** Conversations live in memory with a TTL. There is no lead
  capture and no admin dashboard, so there is no stored-PII encryption layer — a key-management
  surface that would protect nothing is a liability, not a control. If lead capture is added,
  encryption ships in the same change.

---

## Knowledge base

```bash
make kb                  # fetch the live site and regenerate
make kb ARGS=--offline   # rebuild from committed raw/ HTML, no network
make kb-check            # fail if the committed XML is stale (runs in CI)
```

Built from **ten** pages, not the six in the site's navigation. The three project *listing* pages
(`ongoing`, `completed`, `upcoming`) are navigation shells holding under 50 words each; roughly
85% of the real content lives on the four project detail pages reached via their "Read More"
links (`burj-ashrafi`, `burj-classic`, `burj-qadri`, `burj-chishti`).

Output: **1,903 words / 21 KB ≈ 5k tokens.** The entire knowledge base fits in every request's
context, which is why this project has no embeddings, no chunking, and no vector store.
Retrieval would add moving parts and a failure mode to solve a problem that does not exist at
this size. `test_kb_is_small_enough_to_inject_whole` fails if that stops being true.

`raw/` holds the scraped HTML and is committed, so builds are reproducible offline and a diff
shows exactly what changed when the client edits their site.

### Three site quirks the builder has to handle

These are pinned by regression tests, because a scraper fails *silently* — when markup changes,
extraction quietly returns nothing and the assistant starts refusing every question while looking
perfectly healthy.

1. **The site is ASP.NET WebForms, so the entire page body sits inside one `<form>`.** Stripping
   forms as boilerplate — correct on almost any other site — deletes every word of content.
2. **A project is spelled two ways.** `upcoming.aspx` displays "Burj Chisti"; the URL is
   `burj-chishti.aspx`. Matching names to slugs silently dropped a 1,200-word detail page, so
   pairing is structural — via the link inside each card, bounded so a card cannot borrow its
   neighbour's link.
3. **Unit configurations exist only in image filenames.** "1 BHK" is never written in text; the
   sole record is `images/burj-chishti/1.5bhk.jpg`.

### The overrides layer

`build_kb.py` merges scraped output with a hand-maintained `overrides.yaml`, overrides winning.
It supplies what the site omits (pricing and availability answers that route to the sales team),
strips the marketing paragraph repeated verbatim on all four project pages, and disambiguates
**Burj Ashrafi Phase 1 vs Phase 2** — Phase 1 is complete and has a detail page, Phase 2 is
ongoing and is named on `ongoing.aspx` with no page and no published specs.

Only verified facts belong in that file: it is fed to the model as ground truth and stated to real
customers as fact. **No RERA number appears anywhere in the knowledge base** — the site publishes
certificates as PDFs without transcribing the numbers, and an invented registration number is the
most damaging thing this assistant could say. Placeholders sit commented out awaiting the
client's confirmation, and a test asserts none has leaked in.

---

## License

Proprietary — © Burj Constructions.
