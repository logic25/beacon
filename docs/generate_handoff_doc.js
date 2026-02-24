const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, PageBreak, LevelFormat, TabStopType, TabStopPosition } = require('docx');
const fs = require('fs');

const orange = "F59E0B";
const darkGray = "333333";
const medGray = "666666";
const lightGray = "F3F4F6";
const borderDef = { style: BorderStyle.SINGLE, size: 1, color: "DDDDDD" };
const borders = { top: borderDef, bottom: borderDef, left: borderDef, right: borderDef };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, bold: true, size: 32, font: "Arial", color: darkGray })]
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, bold: true, size: 26, font: "Arial", color: darkGray })]
  });
}

function heading3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 120 },
    children: [new TextRun({ text, bold: true, size: 22, font: "Arial", color: "444444" })]
  });
}

function para(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({ text, size: 21, font: "Arial", color: medGray, ...opts })]
  });
}

function boldPara(label, text) {
  return new Paragraph({
    spacing: { after: 100 },
    children: [
      new TextRun({ text: label, bold: true, size: 21, font: "Arial", color: darkGray }),
      new TextRun({ text: " " + text, size: 21, font: "Arial", color: medGray })
    ]
  });
}

function bullet(text, ref = "bullets", level = 0) {
  return new Paragraph({
    numbering: { reference: ref, level },
    spacing: { after: 60 },
    children: [new TextRun({ text, size: 21, font: "Arial", color: medGray })]
  });
}

function bulletBold(label, desc, ref = "bullets", level = 0) {
  return new Paragraph({
    numbering: { reference: ref, level },
    spacing: { after: 60 },
    children: [
      new TextRun({ text: label, bold: true, size: 21, font: "Arial", color: darkGray }),
      new TextRun({ text: " " + desc, size: 21, font: "Arial", color: medGray })
    ]
  });
}

function spacer() {
  return new Paragraph({ spacing: { after: 80 }, children: [] });
}

function headerCell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: { fill: "F59E0B", type: ShadingType.CLEAR },
    margins: cellMargins,
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, size: 20, font: "Arial", color: "FFFFFF" })] })]
  });
}

function cell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    margins: cellMargins,
    children: [new Paragraph({ children: [new TextRun({ text, size: 20, font: "Arial", color: medGray })] })]
  });
}

function statusTable(rows) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3200, 2600, 3560],
    rows: [
      new TableRow({ children: [headerCell("Component", 3200), headerCell("Status", 2600), headerCell("Location", 3560)] }),
      ...rows.map(r => new TableRow({
        children: [cell(r[0], 3200), cell(r[1], 2600), cell(r[2], 3560)]
      }))
    ]
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } }
        ] },
      { reference: "numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } }
        ] }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: orange, space: 4 } },
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          children: [
            new TextRun({ text: "Greenlight Expediting", bold: true, size: 18, font: "Arial", color: orange }),
            new TextRun({ text: "\tOrdino + Beacon Technical Handoff", size: 16, font: "Arial", color: "999999" })
          ]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Page ", size: 16, font: "Arial", color: "999999" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, font: "Arial", color: "999999" }),
            new TextRun({ text: "  |  Confidential  |  February 2026", size: 16, font: "Arial", color: "999999" })
          ]
        })]
      })
    },
    children: [
      // TITLE PAGE
      spacer(), spacer(), spacer(), spacer(), spacer(),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 },
        children: [new TextRun({ text: "ORDINO + BEACON", size: 48, bold: true, font: "Arial", color: orange })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "Technical Architecture, Prompts & SOPs", size: 28, font: "Arial", color: darkGray })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
        children: [new TextRun({ text: "Handoff Document for Greenlight Expediting", size: 22, font: "Arial", color: medGray })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "February 2026", size: 22, font: "Arial", color: medGray })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "Version 1.0", size: 20, font: "Arial", color: "999999" })] }),

      new Paragraph({ children: [new PageBreak()] }),

      // TABLE OF CONTENTS
      heading1("Table of Contents"),
      para("1. System Architecture Overview"),
      para("2. Where Everything Lives"),
      para("3. Lovable Prompts (Ready to Submit)"),
      para("   3a. Beacon Analytics Dashboard"),
      para("   3b. Project Context for Beacon Widget"),
      para("   3c. Objection Review Workflow"),
      para("   3d. Documents Folder Structure (Already Submitted)"),
      para("   3e. Beacon Analytics Edge Function (Already Submitted)"),
      para("4. Railway Backend SOPs"),
      para("5. Knowledge Base Management SOPs"),
      para("6. Environment Variables Reference"),
      para("7. Pending Tasks & Roadmap"),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 1: ARCHITECTURE
      heading1("1. System Architecture Overview"),
      para("The Ordino + Beacon system is a two-part platform for NYC construction expediting firms. Ordino is the CRM (built on Lovable/Supabase), and Beacon is the AI assistant (built on Railway/Python)."),
      spacer(),

      heading2("1.1 Ordino (Frontend CRM)"),
      bulletBold("Platform:", "Lovable (React + Supabase)"),
      bulletBold("Database:", "Supabase PostgreSQL (managed by Lovable)"),
      bulletBold("Auth:", "Supabase Auth with Google OAuth"),
      bulletBold("Hosting:", "Lovable-managed deployment"),
      bulletBold("URL:", "ordinocrm.com"),
      bulletBold("Supabase URL:", "https://mimlfjkisguktiqqkpkm.supabase.co"),
      spacer(),

      heading2("1.2 Beacon (AI Backend)"),
      bulletBold("Platform:", "Railway (Python/Flask)"),
      bulletBold("LLM:", "Anthropic Claude (Haiku for simple, Sonnet for complex)"),
      bulletBold("Vector DB:", "Pinecone (index: beacon-docs)"),
      bulletBold("Embeddings:", "Voyage AI (voyage-2)"),
      bulletBold("Repo:", "github.com/logic25/beacon"),
      bulletBold("Railway URL:", "beacon-production.up.railway.app"),
      spacer(),

      heading2("1.3 How They Connect"),
      bullet("Ordino\u2019s BeaconChatWidget calls Railway\u2019s POST /api/chat"),
      bullet("Beacon analytics flow: Railway \u2192 Supabase edge function (beacon-analytics) \u2192 Supabase DB"),
      bullet("Document sync: Ordino upload \u2192 Railway /api/ingest \u2192 Pinecone"),
      bullet("DOB newsletters: beacon@ email \u2192 Railway /api/ingest-email \u2192 Pinecone + Content Engine"),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 2: WHERE EVERYTHING LIVES
      heading1("2. Where Everything Lives"),
      spacer(),

      heading2("2.1 Current Status"),
      statusTable([
        ["Beacon AI Backend", "Deployed", "Railway (Python/Flask)"],
        ["Ordino CRM Frontend", "Deployed", "Lovable (React/Supabase)"],
        ["Knowledge Base (87 files)", "Built, needs re-ingest", "Git repo: /knowledge/"],
        ["Supabase Analytics Tables", "Created", "Supabase SQL editor"],
        ["Beacon Analytics Edge Function", "Deployed", "Supabase Edge Functions"],
        ["Documents Folder Structure", "Submitted to Lovable", "Lovable prompt"],
        ["AI Usage Dashboard", "Submitted to Lovable", "Lovable prompt"],
        ["Project Context Widget", "Prompt ready", "This document"],
        ["Objection Workflow", "Prompt ready", "This document"],
        ["Custom Domain", "Not started", "Namecheap + Railway"],
        ["beacon@ email", "Not started", "Google Workspace"],
      ]),
      spacer(),

      heading2("2.2 Ordino Page Map"),
      para("Where each feature lives in the Ordino UI:"),
      bulletBold("Dashboard (/dashboard):", "Main CRM dashboard, projects overview"),
      bulletBold("Projects (/projects):", "Project list with objection badges (future)"),
      bulletBold("Project Detail (/projects/:id):", "Details, Documents, Action Items, Objections tab (future)"),
      bulletBold("Chat (/chat):", "Google Chat integration with DM/space list"),
      bulletBold("Documents (/documents):", "Company-wide docs with folder tree, preview, editor, Beacon sync"),
      bulletBold("Settings (/settings):", "Templates, Beacon connection status, team management"),
      bulletBold("Help Center \u2192 AI Usage:", "Beacon analytics dashboard with KPIs, charts, cost tracking"),
      bulletBold("Floating Widget (every page):", "Ask Beacon orange button, project-context-aware on project pages"),
      spacer(),

      heading2("2.3 Railway Backend Endpoints"),
      para("All endpoints on the Beacon Railway backend:"),
      bulletBold("POST /api/chat:", "Main chat endpoint (Ordino widget + Google Chat)"),
      bulletBold("POST /api/ingest:", "Upload file or text \u2192 chunk \u2192 Pinecone"),
      bulletBold("POST /api/ingest-email:", "DOB newsletter HTML \u2192 parse \u2192 Pinecone + Content Engine"),
      bulletBold("GET /api/analytics:", "Stats endpoint for Ordino AI Usage page"),
      bulletBold("GET /api/health:", "Health check"),
      bulletBold("GET /dashboard:", "Built-in admin dashboard (Railway URL/dashboard)"),
      spacer(),

      heading2("2.4 Key Files in Beacon Repo"),
      bulletBold("bot_v2.py:", "Main Flask app, all endpoints, Google Chat webhook handler"),
      bulletBold("llm_client.py:", "Claude API client with smart Haiku/Sonnet routing"),
      bulletBold("retriever.py:", "RAG retrieval from Pinecone"),
      bulletBold("config.py:", "All settings/env vars"),
      bulletBold("analytics_supabase.py:", "Analytics via Supabase edge function proxy"),
      bulletBold("content_engine/engine.py:", "Content Intelligence for blog/newsletter generation"),
      bulletBold("content_engine/parser.py:", "DOB newsletter HTML parser"),
      bulletBold("ingest.py:", "CLI tool for bulk knowledge base ingestion"),
      bulletBold("document_processor.py:", "PDF/markdown chunking with doc-type-aware sizes"),
      bulletBold("knowledge/:", "87 markdown files organized by category (the knowledge base)"),
      bulletBold("system_prompt.py:", "GLE-specific system prompt for Beacon"),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 3: LOVABLE PROMPTS
      heading1("3. Lovable Prompts"),
      para("These are the prompts to submit to Lovable AI. Submit them one at a time, in order. Wait for each to complete before submitting the next."),
      spacer(),

      heading2("3a. Beacon Analytics Dashboard"),
      boldPara("Status:", "Already submitted to Lovable"),
      boldPara("What it does:", "Updates Help Center \u2192 AI Usage page to show live Beacon analytics from Supabase. KPI cards (total questions, active users, avg confidence, pending suggestions), bar charts for questions over time and topics, donut chart for confidence distribution, top questions table, recent conversations list, cost tracking by API provider, team activity leaderboard. Date range picker filters everything."),
      boldPara("Tables used:", "beacon_interactions, beacon_api_usage, beacon_suggestions, beacon_feedback"),
      boldPara("File:", "lovable_ai_usage_beacon_prompt.md in the beacon repo"),
      spacer(),

      heading2("3b. Project Context for Beacon Widget"),
      boldPara("Status:", "Ready to submit"),
      boldPara("What it does:", "Makes the Ask Beacon floating widget context-aware on project pages. When you\u2019re on /projects/:id, the widget automatically includes the project\u2019s address, BIN, block/lot, project type, and filing numbers in every question sent to Beacon. Shows a badge (\u201CProject: 123 Main St\u201D) and swaps quick question chips to project-specific ones like \u201CAny active violations at this address?\u201D"),
      boldPara("Files modified:", "BeaconChatWidget.tsx"),
      boldPara("Backend change needed:", "None \u2014 Railway backend already handles project_context if present, falls back gracefully if missing"),
      para("Full prompt is in lovable_project_context_prompt.md in the beacon repo."),
      spacer(),

      heading2("3c. Objection Review Workflow"),
      boldPara("Status:", "Ready to submit (recommend Phase 1 only first)"),
      boldPara("What it does:", "Adds an Objections tab to each project detail page. Team members can add DOB objections (examiner comment, code reference, priority, due date, assigned to), track status through a workflow (New \u2192 Researching \u2192 Drafting \u2192 Submitted \u2192 Resolved), add comments for collaboration, attach documents, and use Beacon for research and draft response generation."),
      boldPara("Database tables:", "objections, objection_comments, objection_documents"),
      boldPara("UI components:", "ObjectionsTab, ObjectionDetailPanel, ObjectionTable, ObjectionForm, ObjectionsBadge"),
      boldPara("Recommended phasing:", ""),
      bullet("Phase 1 (now): Just the objection tracker \u2014 table, status workflow, assignments, due dates, comments. No Beacon AI integration yet.", "numbers"),
      bullet("Phase 2 (after KB grows): Add \u201CResearch with Beacon\u201D button for code citations and precedent search.", "numbers"),
      bullet("Phase 3: Add \u201CGenerate Draft\u201D for AI-assisted response letters.", "numbers"),
      para("Full prompt is in lovable_objection_workflow_prompt.md in the beacon repo."),
      spacer(),

      heading2("3d. Documents Folder Structure"),
      boldPara("Status:", "Already submitted to Lovable"),
      boldPara("What it does:", "Adds folder/subfolder system to Documents page with folder tree sidebar, document preview panel (PDF/image/markdown inline viewer), in-app markdown editor with save, Beacon source viewer improvements (colored relevance bars, chunk preview, \u201CView Document\u201D links), and auto-sync to Beacon (upload to KB folder \u2192 auto-call /api/ingest)."),
      boldPara("Database:", "document_folders table, new columns on universal_documents (folder_id, beacon_status, beacon_synced_at, beacon_chunks)"),
      para("Full prompt is in lovable_documents_folders_prompt.md in the beacon repo."),
      spacer(),

      heading2("3e. Beacon Analytics Edge Function"),
      boldPara("Status:", "Already submitted and deployed"),
      boldPara("What it does:", "Supabase edge function (beacon-analytics) that acts as a proxy between Railway and Supabase. Railway sends analytics data via HTTP POST with a shared secret (BEACON_ANALYTICS_KEY), and the edge function writes to the beacon_ tables using the service_role key. This avoids needing the Supabase service_role key on Railway."),
      boldPara("Auth:", "Shared secret via x-beacon-key header"),
      para("Full prompt is in lovable_beacon_analytics_prompt.md in the beacon repo."),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 4: RAILWAY SOPs
      heading1("4. Railway Backend SOPs"),
      spacer(),

      heading2("4.1 Deploying Code Changes"),
      para("Railway auto-deploys from the main branch. To deploy:"),
      bullet("Make changes in /beacon/ folder"),
      bullet("git add [files] && git commit -m \u201Cdescription\u201D"),
      bullet("git push origin main"),
      bullet("Railway detects the push and builds automatically (takes 2-3 minutes)"),
      bullet("Check Railway dashboard for build status and logs"),
      spacer(),

      heading2("4.2 Viewing Logs"),
      bullet("Railway dashboard \u2192 beacon project \u2192 Deployments tab \u2192 click latest deployment \u2192 View Logs"),
      bullet("Or use Railway CLI: railway logs"),
      spacer(),

      heading2("4.3 Re-ingesting Knowledge Base"),
      para("When knowledge base files are updated or new files are added:"),
      bullet("railway login (authenticate if needed)"),
      bullet("railway link (select beacon project, production environment)"),
      bullet("railway run python ingest.py knowledge/ (ingest all 87 files)"),
      bullet("railway run python ingest.py knowledge/processes/specific_file.md (single file)"),
      bullet("railway run python ingest.py --stats (check index stats)"),
      spacer(),

      heading2("4.4 Adding Environment Variables"),
      bullet("Go to railway.com \u2192 beacon project \u2192 service \u2192 Variables tab"),
      bullet("Click + New Variable, enter name and value"),
      bullet("Railway auto-redeploys after adding/changing variables"),
      spacer(),

      heading2("4.5 Rollback"),
      para("If a deployment breaks something:"),
      bullet("Go to Railway dashboard \u2192 Deployments"),
      bullet("Find the last working deployment"),
      bullet("Click the three dots menu \u2192 Rollback"),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 5: KB SOPs
      heading1("5. Knowledge Base Management SOPs"),
      spacer(),

      heading2("5.1 Adding New Content"),
      para("There are two ways to add content to Beacon\u2019s knowledge base:"),
      spacer(),
      heading3("Method A: Via Ordino Documents Page (Recommended)"),
      bullet("Navigate to Documents \u2192 Beacon Knowledge Base folder"),
      bullet("Upload a .md or .pdf file"),
      bullet("Ordino auto-calls /api/ingest on Railway"),
      bullet("Document is chunked and added to Pinecone"),
      bullet("Status badge shows \u201CSynced (X chunks)\u201D"),
      spacer(),
      heading3("Method B: Via Git + CLI (Bulk)"),
      bullet("Add .md files to /knowledge/[category]/ in the beacon repo"),
      bullet("git push origin main"),
      bullet("railway run python ingest.py knowledge/ to ingest all files"),
      spacer(),

      heading2("5.2 Editing Existing Content"),
      bullet("In Ordino: Documents \u2192 find the file \u2192 click to preview \u2192 Edit \u2192 make changes \u2192 Save"),
      bullet("Save automatically re-syncs to Beacon if in a KB folder"),
      bullet("In Git: Edit the .md file, push, then run railway run python ingest.py [file]"),
      spacer(),

      heading2("5.3 Knowledge Base File Format"),
      para("Markdown files should follow this format for best results:"),
      para("---"),
      para("title: Guide Title Here"),
      para("category: processes (or dob_notices, building_code, zoning, etc.)"),
      para("tags: [filing, permit, alt1]"),
      para("last_updated: 2026-02-23"),
      para("---"),
      para("# Main Heading"),
      para("[Content organized with headers, lists, and clear sections]"),
      spacer(),

      heading2("5.4 Content Categories"),
      bulletBold("processes:", "Filing guides, procedures, SOPs"),
      bulletBold("dob_notices:", "Service notices, technical bulletins, policy memos"),
      bulletBold("building_code:", "2022 Building Code references"),
      bulletBold("zoning:", "Zoning resolution, use groups, FAR"),
      bulletBold("mdl:", "Multiple Dwelling Law"),
      bulletBold("historical:", "Past project resolutions, precedents"),
      bulletBold("violations:", "DOB/ECB/HPD violation guides"),
      bulletBold("common_objections:", "Common objections and resolution strategies"),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 6: ENV VARS
      heading1("6. Environment Variables Reference"),
      spacer(),

      heading2("6.1 Railway (Beacon Backend)"),
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [3400, 5960],
        rows: [
          new TableRow({ children: [headerCell("Variable", 3400), headerCell("Purpose", 5960)] }),
          new TableRow({ children: [cell("ANTHROPIC_API_KEY", 3400), cell("Claude API key for LLM calls", 5960)] }),
          new TableRow({ children: [cell("PINECONE_API_KEY", 3400), cell("Pinecone vector database key", 5960)] }),
          new TableRow({ children: [cell("PINECONE_INDEX_NAME", 3400), cell("Pinecone index name (beacon-docs)", 5960)] }),
          new TableRow({ children: [cell("VOYAGE_API_KEY", 3400), cell("Voyage AI embedding model key", 5960)] }),
          new TableRow({ children: [cell("GOOGLE_CHAT_CREDENTIALS", 3400), cell("Google Chat service account JSON", 5960)] }),
          new TableRow({ children: [cell("SUPABASE_URL", 3400), cell("https://mimlfjkisguktiqqkpkm.supabase.co", 5960)] }),
          new TableRow({ children: [cell("BEACON_ANALYTICS_KEY", 3400), cell("Shared secret for edge function auth", 5960)] }),
          new TableRow({ children: [cell("CLAUDE_MAX_TOKENS", 3400), cell("Max tokens per response (optional)", 5960)] }),
          new TableRow({ children: [cell("CLAUDE_TEMPERATURE", 3400), cell("Temperature for responses (optional)", 5960)] }),
        ]
      }),
      spacer(),

      heading2("6.2 Lovable/Supabase Secrets"),
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [4200, 5160],
        rows: [
          new TableRow({ children: [headerCell("Secret", 4200), headerCell("Purpose", 5160)] }),
          new TableRow({ children: [cell("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", 4200), cell("Google Chat integration", 5160)] }),
          new TableRow({ children: [cell("FIRECRAWL_API_KEY", 4200), cell("Web scraping for content engine", 5160)] }),
          new TableRow({ children: [cell("GMAIL_CLIENT_ID", 4200), cell("Gmail OAuth client ID", 5160)] }),
          new TableRow({ children: [cell("GMAIL_CLIENT_SECRET", 4200), cell("Gmail OAuth secret", 5160)] }),
          new TableRow({ children: [cell("BEACON_ANALYTICS_KEY", 4200), cell("Must match Railway value", 5160)] }),
          new TableRow({ children: [cell("LOVABLE_API_KEY", 4200), cell("Lovable platform key (auto-managed)", 5160)] }),
        ]
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // SECTION 7: ROADMAP
      heading1("7. Pending Tasks & Roadmap"),
      spacer(),

      heading2("7.1 Immediate (This Week)"),
      bullet("Re-ingest 87 knowledge base files into Pinecone (railway run python ingest.py knowledge/)"),
      bullet("Submit Project Context prompt to Lovable"),
      bullet("Submit Objection Workflow Phase 1 prompt to Lovable"),
      bullet("Test Beacon analytics flow end-to-end (ask Beacon a question, check AI Usage page for the logged interaction)"),
      spacer(),

      heading2("7.2 Near-Term"),
      bulletBold("beacon@greenlightexpediting.com:", "Create in Google Workspace Admin, subscribe to DOB Buildings News, set up forwarding rule to /api/ingest-email"),
      bulletBold("Custom domain:", "Add CNAME record in Namecheap pointing beacon.ordinocrm.com to Railway, configure in Railway settings"),
      bulletBold("Objection Workflow Phase 2:", "Add Beacon research integration after knowledge base grows with more objection precedents"),
      bulletBold("Content Engine:", "Wire up the Lovable Content Engine page to Railway\u2019s /api/content/* endpoints for blog/newsletter generation"),
      spacer(),

      heading2("7.3 Future"),
      bulletBold("BIS Monitoring:", "Auto-pull new objections from DOB BIS for active filings"),
      bulletBold("Objection PDF Parsing:", "Upload DOB objection sheets and auto-extract individual objections"),
      bulletBold("Beacon Learning:", "Use correction/suggestion data to improve responses over time"),
      bulletBold("Project-to-Project Context:", "Beacon remembers context across project conversations"),
      bulletBold("Response Templates:", "Pre-built response letter templates for common objection types"),
      spacer(), spacer(),

      new Paragraph({
        border: { top: { style: BorderStyle.SINGLE, size: 6, color: orange, space: 8 } },
        spacing: { before: 400 },
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "End of Document", size: 18, font: "Arial", color: "999999", italics: true })]
      }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/stoic-youthful-thompson/mnt/beacon/GLE_Ordino_Beacon_Handoff.docx", buffer);
  console.log("Document created successfully");
});
