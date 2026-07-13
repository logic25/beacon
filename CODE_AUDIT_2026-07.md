# Beacon Code Audit — July 2026

Read-only audit of the Beacon repo (`/Users/mannyrussell/beacon`), three parallel passes:
content pipeline + data hygiene, core RAG/LLM/vector layer, and `bot_v2.py` monolith + security.
Nothing was modified. Findings are consolidated, deduped, and ranked below.

## Verdict

The architecture underneath is **decent and mostly aligned with intent** — real module boundaries
already exist (`core/`, `features/`, `analytics/`), the notice→parse→demand→grounded-generation
pipeline is a faithful implementation of the design, and the core retrieval mechanics (Voyage
query/document asymmetry, Pinecone filters, correction overlay) are correct.

But it is **functional-but-fragile**, with one live outage, a security model that is essentially
"nobody knows the Railway URL," and two data-integrity bugs. It doesn't need a rewrite — it needs a
focused hardening + de-duplication pass and one round of extraction to tame the 3k-line monolith.

---

## TIER 0 — Live outage, fix immediately

**0.1 The Google Chat bot is currently broken.** `bot_v2.py:860` calls `llm_client._should_use_tools(...)`
but `llm_client` is never defined (the singleton is `claude_client`). Every non-cached GChat knowledge
question hits this line, raises `NameError`, is swallowed by the outer `except`, and the user gets
"I apologize, but I encountered an error." Introduced by commit `fc44d84`. The Ordino widget is
unaffected (separate code path). **Fix:** `claude_client._should_use_tools(user_message)`. One line.

---

## TIER 1 — Critical security holes

**1.1 Unauthenticated write/ingest endpoints = RAG poisoning.** `/api/ingest` (`bot_v2.py:1579`),
`/api/ingest-email` (`:1847`), `/api/knowledge/rebuild-manifest` (`:2346`), `/api/knowledge/assign-folders`
(`:2685`) have **no auth**. Anyone who reaches the Railway URL can inject arbitrary documents into the
Pinecone KB — which is then fed to Claude as authoritative context for every user (stored prompt
injection). **Fix:** require `x-beacon-key` (or a dedicated ingest secret) on all ingest + manifest-mutating routes.

**1.2 Privilege escalation via client-supplied email.** `/api/chat` (`:1178`) passes
`data.get("user_email")` straight into the `/correct` admin check (`:477`, `user_email in ADMIN_EMAILS`).
A caller can POST `{"message":"/correct X | Y","user_email":"manny@greenlightexpediting.com"}` and inject
KB "corrections" as an admin. `/webhook` (`:1001`) has the same exposure — it does **no Google Chat JWT
verification**, so a spoofed payload can set an admin email. **Fix:** verify the GChat bearer JWT on
`/webhook`; require the analytics/admin secret for `/correct`, not a client-supplied email.

**1.3 Unauthenticated analytics leak PII.** `/analytics-data` (`:1516`) and `/api/analytics` (`:1533`)
are open and return verbatim user questions (which routinely contain client names, addresses, BINs),
top users, and cost. **Fix:** gate behind the shared secret or the OAuth dashboard.

**1.4 Wildcard CORS with credentials.** `CORS(app, supports_credentials=True)` (`:184`) allows any origin
with credentials — combined with the open endpoints, any site a GLE user visits can call them from the
browser. **Fix:** restrict `origins` to the Ordino/Lovable domains.

**1.5 Secret reuse + weak default.** `BEACON_ANALYTICS_KEY` doubles as the KB-admin secret (`:2432`) — one
leak grants KB delete/edit. And `app.secret_key` defaults to `'dev-secret-change-in-production'` (`:181`)
if `FLASK_SECRET_KEY` is unset. **Fix:** dedicated `KB_ADMIN_SECRET`; fail hard on a missing prod secret.

> Positive: no secrets are logged, keys load via pydantic `Settings`/env, `.gitignore` excludes `.env` and DBs.

---

## TIER 2 — Critical correctness / data integrity

**2.1 `_last_grounding` concurrency race.** Grounding is stashed on the shared engine singleton
(`engine.py:330/443`) and read back by the route (`content_routes.py:547`). Two overlapping
`POST /api/content/generate` calls race — Ordino gets the **wrong draft's** grounding object (wrong
`verify_flags`/`kb_sources`), silently mis-attributing which facts are unsourced. **Fix:** return grounding
as a value from `generate_*`, never persist per-request output on a shared singleton. *(Touches the grounding
work just shipped.)*

**2.2 Semantic response cache serves cross-format + stale answers.** The cache (`response_cache.py`) is keyed
only on question-embedding similarity and is shared between the GChat and web flows. Three failures:
(a) a question first asked in GChat returns GChat-formatted text to the web widget (and vice-versa), with
`sources: []`; (b) tool-backed operational answers ("3 projects overdue") are re-served for 24h even as the
data changes; (c) a `/correct` KB edit doesn't invalidate the cached pre-correction answer. **Fix:** key on
`(flow/format, question, retrieval-context-hash)`, exclude tool/operational + property-lookup flows from
caching, separate or format-normalize the GChat vs web caches.

**2.3 Contamination filter covers 1 of 4 question-entry paths; no PII scrub.** The filter exists only in
`engine._query_team_questions_supabase`. The **daily scheduler's main job** `run_auto_generate`
(`content_routes.py:642/657`) — plus `_query_team_questions_sqlite` — pull questions **raw**. And even where
the filter runs, it only drops tool-formatted text; a legitimate human question containing a client address
("...ALT2 at 123 Main St for [client]...") passes and is published verbatim in the blog FAQ. **Fix:**
centralize the contamination list + `is_contaminated()`, apply at all four entry points, and add a PII scrub
(addresses/BIN/BBL/names) before any question is stored or injected into a prompt.

---

## TIER 3 — Design alignment / structural

**3.1 Two divergent pipelines.** The good notice×demand×grounded path runs on the **hourly email poller**;
the **daily `ContentScheduler`** runs an older, cruder keyword-clustering path (`run_auto_generate`) that
skips the notice cross-reference, the semantic demand match, the LLM analysis, and the contamination filter.
The design's centerpiece and the code's daily job are different pipelines. **Fix:** point `ContentScheduler`
at the notice×demand path, or bring `run_auto_generate` up to parity.

**3.2 Ordino-driven generate drops demand context.** The candidate rebuilt from the Ordino request
(`content_routes.py:527-535`) omits `team_questions`/`most_common_angle`, so `generate_blog_post` emits
"Team has been asking about this **0** times" with an empty FAQ — on the path Ordino actually uses. **Fix:**
pass the demand fields through.

**3.3 Two conflicting Sonnet model IDs.** `llm_client.py:234` hardcodes `claude-sonnet-4-6`; `config.py:81`
maps `sonnet → claude-sonnet-4-5-20250929` (older). `route_model()` bypasses `validate_model`, so the model
used and the model config describes disagree — and setting `CLAUDE_MODEL=claude-sonnet-4-6` crashes startup
(not in the allow-list). **Fix:** one source of truth in `Settings`; standardize on `claude-sonnet-4-6`;
reconcile the allow-list.

**3.4 Retriever ordering bugs.** `retrieve()` truncates to `top_k` **before** applying `min_score`
(`retriever.py:230`) — can return fewer valid docs than exist. And `_format_context` re-sorts by
`(authority, score)`, dropping the recency boost the re-ranker exists to apply. **Fix:** filter-before-truncate;
carry one ranking through selection and display.

---

## TIER 4 — Cleanup / refactoring

- **Delete dead code:** `ANALYTICS_PUBLIC_HTML` (`bot_v2.py:2872-3067`, ~200 lines, never referenced);
  `delete_by_source` no-op (`vector_store.py:289`); empty `HEDGING_PATTERNS`.
- **Centralize the 3 embedding paths** onto `VectorStore` (public `embed_texts(texts, input_type)`); delete
  `SemanticCache`'s private Voyage client + hardcoded `"voyage-2"`; stop `content_engine` reaching into the
  private `_embed_voyage`.
- **De-duplicate:** the "skip RAG for operational queries" decision (two divergent copies, `bot_v2.py:860` vs
  `1287`); the `get_recent_conversations` fetch (hand-rolled in two places, `SupabaseAnalyticsDB` already has it);
  the two citation formatters; `generate_blog_post`/`generate_newsletter` are ~90% identical → one `_generate()`.
- **Extract the monolith** (deploy-safe, one PR each): (1) delete dead HTML; (2) knowledge routes 2051-2863 →
  `features/knowledge_routes.py` Blueprint; (3) ingest routes → Blueprint; (4) `handle_slash_command` → `commands.py`;
  (5) chat routes → Blueprint; (6) app-factory + a single `@require_secret` decorator.
- **Fix SQL string interpolation** (`engine.py:693/894`) → parameterized queries.
- **Grounding substring false-match** (`engine.py:353`): `"$100"` matches inside `"$1000"` → token-boundary match.
- **Promote magic numbers to config:** semantic threshold `0.55`, `min_score`, grounding cutoff `0.7`,
  `days=60`, cache `0.85`/`24h`, `CITATION_THRESHOLD 0.65`.
- **Cache re-embeds each question up to 3× per call** (`response_cache.py:251/294/317`) → embed once, thread through.

---

## Recommended fix sequence

1. **Ship the one-line GChat fix (0.1) now** — the bot is down for knowledge questions.
2. **Security lockdown (Tier 1)** — one `@require_secret` decorator on ingest/manifest/analytics routes,
   GChat JWT verification, stop trusting client `user_email`, restrict CORS, split the KB-admin secret. This is
   the highest-value cluster; do it as one focused PR.
3. **Data integrity (2.1 grounding race, 2.3 contamination coverage + PII scrub)** — these touch the content
   work just shipped and the contamination cleanup in flight.
4. **Cache fix (2.2)** — wrong/stale answers to users.
5. **Reconcile the two pipelines (3.1/3.2)** + the model-ID unification (3.3).
6. **Cleanup + monolith extraction (Tier 4)** — dead code first, then Blueprints, incrementally.
