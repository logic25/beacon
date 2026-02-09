# Beacon

**NYC Zoning & Permit Expert — RAG-powered Google Chat Bot**

Internal tool for Green Light Expediting. Provides instant answers on NYC zoning codes, building codes, MDL, HMC, DHCR regulations, and DOB filing procedures.

---

## Architecture

* **LLM**: Claude (Anthropic) — Haiku for speed, Sonnet for complex queries
* **Vector Store**: Pinecone (1024-dim, cosine similarity)
* **Embeddings**: Voyage AI (voyage-2)
* **Hosting**: Railway (auto-deploy from GitHub)
* **Interface**: Google Chat (webhook)
* **Analytics**: SQLite database with web dashboard

---

## Key Files

| File | Purpose |
|------|---------|
| `bot_v2.py` | Main Flask app — webhook handler, slash commands |
| `analytics.py` | **NEW** — Analytics database (tracks all interactions) |
| `dashboard.py` | **NEW** — Web dashboard for usage analytics |
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
| `knowledge_capture.py` | Team corrections & tips (`/correct`, `/tip`) |
| `rate_limiter.py` | Usage tracking and cost controls |
| `response_cache.py` | Semantic response caching |
| `session_manager.py` | Conversation history per user |
| `document_processor.py` | PDF/text chunking and processing |
| `document_metadata.py` | Document metadata extraction |

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/lookup <address>, <borough>` | Property lookup via NYC Open Data |
| `/zoning <address>, <borough>` | Full zoning analysis |
| `/correct <wrong> \| <right>` | Flag a correction (admin only) |
| `/suggest <wrong> \| <right>` | Suggest a correction for review |
| `/tip <your tip>` | Add team knowledge |
| `/feedback <your idea>` | **NEW** — Suggest feature improvements |
| `/objections <filing type>` | Common DOB objections (ALT1, NB, etc.) |
| `/plans` | Plan reading capabilities |
| `/stats` | Knowledge base stats |
| `/usage` | Your usage stats |

---

## Analytics Dashboard

**NEW**: Real-time analytics dashboard at `/dashboard`

**Features:**
- Total questions asked (last 7 days)
- Success rate percentage
- Active users count
- API cost tracking
- Top 10 most active users
- Top 20 most asked questions
- Suggestions queue (approve/reject pending corrections)

**Access:** `https://your-railway-url.up.railway.app/dashboard`

**Authentication:** Google OAuth (admin-only access)

See `OAUTH_SETUP.md` for setup instructions.

---

## Smart Features

### **Automatic RAG Filtering**
Beacon skips document retrieval for simple greetings and tests, improving response speed:
- "test" → no RAG lookup
- "what is zoning?" → RAG lookup

### **Response Caching**
Semantically similar questions hit cache for instant responses

### **Rate Limiting**
- 100 requests per user per day
- 100K tokens per user per day
- Cost tracking per user

### **Knowledge Capture**
- `/correct` (admin) — applies immediately
- `/suggest` (team) — logs for review
- `/tip` — captures team wisdom
- `/feedback` — feature requests

---

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

**Optional (for OAuth dashboard):**
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `FLASK_SECRET_KEY`

---

## Deploy

Push to `main` → Railway auto-deploys via `railway.json`.

**Start command:**
```bash
gunicorn bot_v2:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

**Post-deployment:**
1. Verify bot responds in Google Chat
2. Visit `/dashboard` to confirm analytics tracking
3. Set up OAuth (see `OAUTH_SETUP.md`)

---

## Knowledge Base

**Current sources:**
- DOB Building Bulletins
- DOB Service Notices
- MDL regulations
- DHCR guidelines
- Team corrections and tips

**Adding documents:**
```bash
# Single file
python ingest.py path/to/document.pdf

# Entire folder
python ingest.py path/to/documents/

# Zoning Resolution
python zoning_ingest.py path/to/zr_pdfs/ --article II
```

---

## Admin Access

**Admins (can use `/correct`):**
- manny@greenlightexpediting.com
- chris@greenlightexpediting.com

Update `ADMIN_EMAILS` in `bot_v2.py` to add admins.

---

## Monitoring

**Dashboard metrics:**
- Questions per day/week
- Success rate (answered vs "I don't know")
- Most active users
- Most asked questions
- Pending suggestions
- API costs

**Cost estimate:** $10-30/month for team of 5-6 users

---

## Troubleshooting

### Bot not responding
1. Check Railway logs for errors
2. Verify environment variables are set
3. Test `/health` endpoint

### Dashboard not loading
1. Ensure `analytics.py` and `dashboard.py` are deployed
2. Check Railway logs for import errors
3. Verify database file is created (`beacon_analytics.db`)

### "I don't have access" on dashboard
1. Check Google OAuth credentials
2. Verify your email is in `AUTHORIZED_EMAILS` (in `dashboard_auth.py`)
3. Clear browser cookies and try again

---

## Security

- Analytics data stored locally in SQLite
- Dashboard protected by Google OAuth
- Only authorized emails can access dashboard
- Service account credentials in environment variables (not committed)
- `.gitignore` excludes `beacon_analytics.db`

---

## Documentation

- `DEPLOYMENT_GUIDE.md` — Full deployment walkthrough
- `OAUTH_SETUP.md` — Google OAuth configuration
- `ANALYTICS_INTEGRATION.md` — Analytics implementation details

---

## License

Internal tool for Green Light Expediting. Not for redistribution.

---

*Last updated: February 2026*
