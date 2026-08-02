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
| 4 | LLM adapters + conversation service | ✅ Done |
| 5 | API layer | ✅ Done |
| 6 | Embeddable widget | ✅ Done |
| 6.5 | Deployment (Oracle Always Free + GitHub Pages) | ✅ Done |
| 7 | Voice (optional) | ⬜ Optional |

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

The app is served via a factory (`uvicorn app.main:create_app --factory`) — there
is deliberately no module-level `app`, so importing `app.main` does not require
a live API key.

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
     GeminiClient ─ AnthropicClient ─ OpenAICompatibleClient
```

The domain layer imports nothing but the standard library. That constraint is what makes the
guardrails testable without a network call, and the LLM provider swappable by changing one
environment variable.

**It is enforced, not documented.**
[backend/tests/architecture/test_layer_boundaries.py](backend/tests/architecture/test_layer_boundaries.py)
parses every domain module's syntax tree and fails the build on a forbidden import. A second test
asserts no module outside the LLM adapters imports a vendor SDK — which is what makes
"swapping providers costs one env var" a verifiable claim rather than an aspiration.

### Swapping the LLM provider

```bash
LLM_PROVIDER=gemini             # Google AI Studio free tier (development default)
LLM_PROVIDER=anthropic          # Claude (production option)
LLM_PROVIDER=openai_compatible  # any open-weight model (Groq, OpenRouter, Ollama, vLLM…)
```

The third option is one adapter covering every service that speaks the OpenAI
chat-completions API, so those are a **URL change, not a code change**:

| Provider | Free tier | `OPENAI_COMPAT_BASE_URL` |
|---|---|---|
| Groq | generous | `https://api.groq.com/openai/v1` |
| OpenRouter | some free models | `https://openrouter.ai/api/v1` |
| Together | credits | `https://api.together.xyz/v1` |
| Ollama | local, free, **no key** | `http://localhost:11434/v1` |
| vLLM | self-hosted | `http://localhost:8000/v1` |

Adding it took one new file and three lines in the composition root — nothing in
the domain, the guardrails, the service, or the API layer changed. It needs no
new SDK either: the wire format is a JSON POST, so it uses the `httpx` already
in the tree.

Open-weight models follow instructions less reliably than the frontier models,
so Layer 4 rejects more of their answers and visitors see the fallback more
often. That is the guardrail working, not failing.

Nothing else changes. No code, no config, no redeploy of the widget.
`test_only_the_provider_field_differs_across_all_three` asserts that literally:
it diffs every settings field across all three configurations and requires the
difference to be exactly `{"llm_provider"}`.

**The adapters are not symmetric, and that is the point.** Current Claude models
(Opus 5, Sonnet 5, Opus 4.8/4.7) **reject** `temperature` with a 400. Gemini
requires it. A service that set `temperature` on an SDK call directly would fail
on the first visitor question the moment you flipped the env var — breaking the
exact promise this architecture makes.

Instead the domain expresses *intent* (`temperature=0.2` — "be faithful, not
creative") as a port field, and
[anthropic_client.py](backend/app/infrastructure/llm/anthropic_client.py) decides
how to honour it per model: sent where accepted, omitted where not, logged once
at startup either way. Absorbing that asymmetry is what an adapter is *for*.

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

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/chat` | Ask a question. Returns `{conversation_id, answer, is_fallback}` |
| `GET /health` | Liveness — restart me if this fails |
| `GET /ready` | Readiness — route traffic to me if this passes |

Health and readiness are separate on purpose: a knowledge-base failure should
pull an instance out of rotation, not trigger a restart loop. `/ready` inspects
actual content, because a loaded-but-empty knowledge base is a process that
looks perfectly healthy while answering every question with the fallback.

The response deliberately omits the internal outcome and rejection reason.
Returning *which* guardrail refused would turn the endpoint into an oracle for
probing the filter. `is_fallback` is safe because the fallback sentence is fixed
and self-identifying — it tells a caller nothing the answer text doesn't.

`conversation_id` is a server-minted UUID4. There is no authentication on this
endpoint, so unguessable identifiers are the only thing stopping someone walking
`1`, `2`, `3` and appending to other visitors' conversations — which is why the
schema rejects anything that isn't UUID4 shaped.

## Widget

One self-contained file, **34 KB gzipped**, embedded with a single tag:

```html
<script src="https://your-cdn/burj-chat.js"
        data-api-url="https://api.burjconstructions.com" defer></script>
```

```sh
cd widget && npm run check   # typecheck + 73 unit tests + browser isolation run
```

### The palette is the site's, not a guess

`#deb339` is the most-used colour in the client's own `css/burj.css`; the dark
surfaces `#1e2126`/`#23262d` and the Poppins typeface come from the same place.
**The brief specified "navy/gold" — the site has no navy anywhere.** Building
navy would have produced exactly the bolted-on look the palette exists to avoid.

Contrast is asserted rather than claimed: `tests/contrast.test.ts` computes WCAG
ratios for all 11 pairings the widget actually renders and fails the build below
4.5:1. It also pins the constraint that shapes the design — gold on white is
**1.98:1** and fails badly, which is why gold only ever appears as a background
with dark ink on it, or as text on charcoal.

### Isolation is verified in a browser, not asserted

`npm run verify` loads the built bundle into headless Chromium on a page
carrying the client's real Bootstrap, Animate.css, `burj.css`, and jQuery 3.5.1,
plus hostile overrides (`* { font-family: Comic Sans !important }`,
`button { background: magenta !important; padding: 40px !important }`,
`div { border: 2px solid lime !important }`), then reads **computed** styles
inside the shadow root. 20/20 checks pass.

The harness includes a control assertion that the hostile CSS genuinely wrecks
an unprotected element — without it, every isolation check could pass by the
overrides silently failing to apply.

That run found a real bug jsdom could not: the host wrapper lives in the *light*
DOM, so `div { border: … !important }` reached it and drew a lime box around the
whole widget. Fixed by a `:host` block using `!important`, which under CSS
Cascading 4 beats an outer `!important` because importance reverses the usual
shadow ordering.

## Deployment

**$0/month, permanently.** Full walkthrough in [deploy/README.md](deploy/README.md).

| Piece | Where | Cost |
|---|---|---|
| API | Oracle Always Free ARM VM (4 cores, 24 GB, no expiry) | $0 |
| TLS | Let's Encrypt via Caddy, auto-renewed | $0 |
| Widget | GitHub Pages, built by Actions on every push | $0 |

```sh
docker compose -f deploy/docker-compose.yml up -d --build
```

The container is built for **linux/arm64** because that is what Oracle's free
tier runs, and CI builds that architecture on every push — an image that
compiles on x86 can still fail on aarch64 when a dependency has no wheel.
CI also boots the image and asserts `/health`, `/ready`, a guardrail refusal,
and that `/docs` is 404 in production.

TLS is not optional: the widget is embedded on an HTTPS page, so an HTTP API
would be blocked as mixed content and the request would never leave the
browser. Caddy handles the certificate with no cron job and no certbot.

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
