# Beacon

**NYC Construction & Expediting AI Assistant — RAG-powered, multi-interface**

AI assistant for Greenlight Expediting (GLE). Provides instant answers on NYC zoning codes, building codes, MDL, HMC, DHCR regulations, DOB filing procedures, and team-specific knowledge. Available via Google Chat and the Ordino CRM widget.

---

## Architecture

| Layer | Technology |
|-------|-----------|
| **LLM** | Claude (Anthropic) — Haiku for speed, Sonnet for complex queries |
| **Vector Store** | Pinecone (1024-dim, cosine similarity) |
| **Embeddings** | Voyage AI (voyage-2) |
| **Hosting** | Railway (auto-deploy from GitHub) |
| **Interfaces** | Google Chat (webhook) + Ordino CRM widget (`/api/chat`) |
| **Analytics** | Supabase (primary) + SQLite (fallback) |
| **Frontend CRM** | Ordino — built on Lovable/Supabase at ordinocrm.com |

### How It Works

```
User Question (Google Chat or Ordino Widget)
    │
    ├─ Slash Command? → handle_slash_command() → response
    │
    ├─ Property Lookup? → NYC Open Data API → formatted response
    │
    └─ Regular Question
         ├─ Pinecone RAG retrieval (authority-sorted, with corrections)
         ├─ Objections KB lookup (if filing-type detected)
         ├─ Topic classification (LLM → keyword fallback)
         ├─ Model routing (Haiku for simple, Sonnet for complex)
         └─ Claude generates response with source citations
              │
              └─ Log to Supabase analytics (via edge function)
```

---

## Project Structure

```
beacon/
├── bot_v2.py                  # Main Flask app (entry point for Railway)
├── config.py                  # Pydantic settings — all env vars validated here
├── requirements.txt           # Python dependencies
├── Procfile                   # Railway/Heroku process definition
├── railway.json               # Railway deploy config
├── render.yaml                # Render.com backup deploy config
├── .env / env.example         # Environment variables
│
├── core/                      # Runtime modules (imported by bot_v2.py)
│   ├── llm_client.py          #   Claude API client, system prompts, model routing
│   ├── retriever.py           #   RAG retrieval — authority sort, corrections, scoring
│   ├── vector_store.py        #   Pinecone operations (search, upsert, filters)
│   ├── session_manager.py     #   Conversation history per user
│   ├── rate_limiter.py        #   Usage tracking and cost controls
│   ├── response_cache.py      #   Semantic response caching
│   └── google_chat.py         #   Google Chat API client
│
├── features/                  # Feature modules (imported by bot_v2.py)
│   ├── objections.py          #   Common DOB objections knowledge base
│   ├── plan_reader.py         #   Architectural plan reading capabilities
│   ├── nyc_open_data.py       #   Live NYC property lookups (BIS, DOB, HPD)
│   ├── knowledge_capture.py   #   Team corrections & tips (/correct, /tip)
│   └── dashboard.py           #   Railway admin dashboard (OAuth protected)
│
├── analytics/                 # Analytics & classification
│   ├── analytics.py           #   SQLite analytics backend (fallback)
│   ├── analytics_supabase.py  #   Supabase edge function proxy (primary)
│   ├── topic_classifier.py    #   LLM-based topic classification for dashboard
│   ├── intelligent_scorer.py  #   Content candidate scoring with Claude + RAG
│   └── content_routes.py      #   Content Intelligence API (Flask blueprint)
│
├── content_engine/            # Content Intelligence (newsletter parsing)
│   ├── engine.py              #   Main engine: parses DOB newsletters, scores content
│   └── parser.py              #   Email/newsletter parsing logic
│
├── zoning/                    # Zoning analysis module
│   ├── analyzer.py            #   ZoningAnalyzer for property zoning lookups
│   ├── rules/                 #   Zoning rules: bulk, parking, use groups
│   └── data_sources/          #   NYC data: PLUTO, flood zones, landmarks, tax maps
│
├── ingestion/                 # Offline tooling (not runtime)
│   ├── ingest.py              #   Document ingestion pipeline (file → Pinecone)
│   ├── zoning_ingest.py       #   Specialized Zoning Resolution ingestion
│   ├── chat_ingest.py         #   Google Chat history ingestion
│   └── document_processor.py  #   PDF/text chunking and processing
│
├── knowledge/                 # 89 markdown files — the RAG knowledge base
│   ├── processes/             #   44 filing guides, permits, inspections
│   ├── dob_notices/           #   17 Buildings Bulletins, service notices
│   ├── historical/            #   8 past project case files
│   ├── mdl/                   #   6 Multiple Dwelling Law sections
│   ├── building_code_2022/    #   3 NYC Building Code chapters
│   ├── zoning/                #   3 Zoning Resolution articles
│   ├── building_code/         #   2 general building code references
│   ├── building_code_1968/    #   1 1968 Building Code
│   ├── hmc/                   #   1 Housing Maintenance Code
│   ├── rcny/                  #   1 Rules of the City of New York
│   └── communication/         #   1 communication patterns
│
├── tests/                     # Unit tests
│   ├── test_llm_client.py
│   ├── test_session_manager.py
│   └── test_intelligent_scorer.py
│
└── docs/                      # Reference documentation
    ├── GLE_Ordino_Beacon_Handoff.docx
    ├── BeaconChatWidget.tsx
    ├── architecture.jsx
    ├── cross_reference_engine_spec.md
    ├── supabase_schema.sql
    └── generate_handoff_doc.js
```

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/webhook` | POST | Google Chat webhook handler |
| `/api/chat` | POST | Ordino widget chat (JSON API) |
| `/api/analytics` | GET | Analytics stats for Ordino AI Usage page |
| `/api/ingest` | POST | Upload documents to Pinecone knowledge base |
| `/api/ingest-email` | POST | Parse DOB newsletter emails |
| `/api/knowledge/list` | GET | List all knowledge base files |
| `/api/knowledge/<path>` | GET | Serve a specific knowledge base file |
| `/api/roadmap/create` | POST | Create standalone roadmap item |
| `/dashboard` | GET | Railway admin dashboard (OAuth protected) |

---

## Dashboard

Admin dashboard at `https://beacon-production.up.railway.app/dashboard`

**Pages:** Analytics, Conversations, Feedback, Roadmap, Content Engine

**Analytics page shows:** Total Questions, Success Rate, Active Users, API Cost, Avg Response Time, Pending Reviews, Recent Conversations (with topic classification), Daily Usage chart, Questions by Topic distribution.

**Topic Classification:** Every question is classified by an LLM (Claude Haiku) into categories: DOB Filings, Zoning, DHCR, Violations, Certificates, Building Code, FDNY, MDL, Noise/Hours, Landmarks, Property Lookup, Plans/Drawings, General. Falls back to keyword matching if the LLM call fails.

**Authentication:** Google OAuth (admin-only). Update `ADMIN_EMAILS` in `bot_v2.py`.

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/lookup <address>, <borough>` | Property lookup via NYC Open Data |
| `/correct <wrong> → <right>` | Flag a correction (admin only) |
| `/suggest <wrong> → <right>` | Suggest a correction for review |
| `/tip <your tip>` | Add team knowledge |
| `/feedback <your idea>` | Suggest feature improvements |
| `/status` | Beacon system status |

Works in both Google Chat and the Ordino widget.

---

## Knowledge Base

**89 markdown files** in `knowledge/` organized into 14 subfolders.

**Document authority hierarchy** — When sources conflict, Beacon prioritizes: Determinations & Code (10) > Technical Bulletins (8) > Policy Memos (7) > Service Notices (6) > Internal Procedures (5) > Reference (4) > Historical (3)

**Adding documents:**
```bash
python ingestion/ingest.py path/to/document.pdf          # Single file
python ingestion/ingest.py path/to/documents/             # Entire folder
python ingestion/zoning_ingest.py path/to/zr_pdfs/        # Zoning Resolution
```

---

## Setup

1. Copy `env.example` to `.env` and fill in API keys
2. `pip install -r requirements.txt`
3. `python bot_v2.py`

**Required env vars:**
- `ANTHROPIC_API_KEY` — Claude API
- `PINECONE_API_KEY` — Vector store
- `VOYAGE_API_KEY` — Embeddings

**Supabase analytics:**
- `SUPABASE_URL` — Supabase project URL
- `BEACON_ANALYTICS_KEY` — Shared secret for edge function

**Google Chat:**
- `GOOGLE_SERVICE_ACCOUNT_FILE` — Service account JSON

**Dashboard OAuth:**
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `FLASK_SECRET_KEY`

---

## Deploy

Push to `main` → Railway auto-deploys.

```bash
gunicorn bot_v2:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

---

## License

Internal tool for Greenlight Expediting. Not for redistribution.

*Last updated: February 24, 2026*
