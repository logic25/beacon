# Beacon

**NYC Zoning & Permit Expert — RAG-powered Google Chat Bot**

Internal tool for Green Light Expediting. Provides instant answers on NYC zoning codes, building codes, MDL, HMC, DHCR regulations, and DOB filing procedures.

## Architecture

- **LLM:** Claude (Anthropic) — Haiku for speed, Sonnet for complex queries
- **Vector Store:** Pinecone (1024-dim, cosine similarity)
- **Embeddings:** Voyage AI (voyage-2)
- **Hosting:** Railway (auto-deploy from GitHub)
- **Interface:** Google Chat (webhook)

## Key Files

| File | Purpose |
|------|---------|
| `bot_v2.py` | Main Flask app — webhook handler, slash commands |
| `llm_client.py` | Claude API integration, system prompts, response filtering |
| `google_chat.py` | Google Chat API client (send/update messages) |
| `retriever.py` | RAG retrieval — queries Pinecone, formats context |
| `vector_store.py` | Pinecone operations (search, upsert, stats) |
| `config.py` | Pydantic settings — all env vars validated here |
| `ingest.py` | Document ingestion pipeline (PDF → chunks → vectors) |
| `zoning_ingest.py` | Specialized ZR article ingestion |
| `chat_ingest.py` | Google Chat export ingestion |
| `nyc_open_data.py` | Live NYC property lookups (BIS, DOB, HPD) |
| `objections.py` | Common DOB objections knowledge base |
| `plan_reader.py` | Plan reading capabilities |
| `knowledge_capture.py` | Team corrections & tips (/correct, /tip) |
| `rate_limiter.py` | Usage tracking and cost controls |
| `response_cache.py` | Semantic response caching |
| `session_manager.py` | Conversation history per user |
| `document_processor.py` | PDF/text chunking and processing |
| `document_metadata.py` | Document metadata extraction |

## Slash Commands

- `/help` — Show available commands
- `/lookup <address>, <borough>` — Property lookup via NYC Open Data
- `/zoning <address>, <borough>` — Full zoning analysis
- `/correct <wrong> | <right>` — Flag a correction
- `/tip <your tip>` — Add team knowledge
- `/objections <filing type>` — Common DOB objections (ALT1, NB, etc.)
- `/plans` — Plan reading capabilities
- `/stats` — Knowledge base stats
- `/usage` — Your usage stats

## Setup

See `DEPLOYMENT_GUIDE.md` for full instructions.

**Quick start:**
1. Copy `.env.example` to `.env` and fill in API keys
2. `pip install -r requirements.txt`
3. `python bot_v2.py`

**Required env vars:**
- `ANTHROPIC_API_KEY`
- `PINECONE_API_KEY`
- `VOYAGE_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_FILE`

## Deploy

Push to `main` → Railway auto-deploys via `railway.json`.

Start command: `gunicorn bot_v2:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
