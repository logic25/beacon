const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType, 
        ShadingType, LevelFormat, PageBreak, PageNumber } = require('docx');

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function statusCell(text, color) {
  return new TableCell({
    borders, width: { size: 1500, type: WidthType.DXA },
    shading: { fill: color, type: ShadingType.CLEAR },
    margins: cellMargins, verticalAlign: "center",
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text, bold: true, font: "Arial", size: 18, color: "FFFFFF" })
    ]})]
  });
}

function textCell(text, width, bold = false) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA }, margins: cellMargins,
    children: [new Paragraph({ children: [
      new TextRun({ text, font: "Arial", size: 20, bold })
    ]})]
  });
}

function headerCell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA }, margins: cellMargins,
    shading: { fill: "1A1A2E", type: ShadingType.CLEAR },
    children: [new Paragraph({ children: [
      new TextRun({ text, font: "Arial", size: 20, bold: true, color: "FFFFFF" })
    ]})]
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "1A1A2E" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "16213E" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "0F3460" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: {
    config: [
      { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "steps2", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "steps3", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "steps4", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
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
      default: new Header({ children: [new Paragraph({
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "1A1A2E", space: 1 } },
        children: [
          new TextRun({ text: "Beacon + Ordino V2", font: "Arial", size: 18, bold: true, color: "1A1A2E" }),
          new TextRun({ text: "\tFebruary 26, 2026 Action Plan", font: "Arial", size: 18, color: "888888" }),
        ],
        tabStops: [{ type: "right", position: 9360 }],
      })] })
    },
    children: [
      // TITLE
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [
        new TextRun({ text: "Tomorrow's Action Plan", font: "Arial", size: 48, bold: true, color: "1A1A2E" })
      ]}),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 }, children: [
        new TextRun({ text: "Ordered for momentum \u2014 quick wins first, Beacon debugging last", font: "Arial", size: 22, color: "666666", italics: true })
      ]}),

      // ==========================================
      // TASK 1
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Task 1: Push Sonnet Model Fix & Test @Beacon")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Time: ", bold: true }), new TextRun("5 minutes"),
        new TextRun({ text: "  |  Priority: ", bold: true }), new TextRun("Do this first thing")
      ]}),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun("The model fix is already saved in your local beacon repo. Just push it.")
      ]}),
      new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun("Terminal Commands (copy/paste):")] }),
      new Paragraph({ shading: { fill: "F5F5F5", type: ShadingType.CLEAR }, spacing: { after: 40 },
        children: [new TextRun({ text: "cd ~/beacon", font: "Courier New", size: 20 })] }),
      new Paragraph({ shading: { fill: "F5F5F5", type: ShadingType.CLEAR }, spacing: { after: 40 },
        children: [new TextRun({ text: "git add core/llm_client.py", font: "Courier New", size: 20 })] }),
      new Paragraph({ shading: { fill: "F5F5F5", type: ShadingType.CLEAR }, spacing: { after: 40 },
        children: [new TextRun({ text: 'git commit -m "Use Sonnet for all requests temporarily"', font: "Courier New", size: 20 })] }),
      new Paragraph({ shading: { fill: "F5F5F5", type: ShadingType.CLEAR }, spacing: { after: 200 },
        children: [new TextRun({ text: "git push origin main", font: "Courier New", size: 20 })] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Then wait 2 min for Railway to redeploy, go to Google Chat, and type ", }),
        new TextRun({ text: "@Beacon hello", bold: true }),
        new TextRun(" in the AI Bot Testing space. You should get an actual answer this time.")
      ]}),

      // ==========================================
      // TASK 2
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Task 2: Ordino KB Page \u2014 Show Real Knowledge Base")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Time: ", bold: true }), new TextRun("~2 hours (Lovable)"),
        new TextRun({ text: "  |  Priority: ", bold: true }), new TextRun("High \u2014 quick visible win")
      ]}),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun("The Ordino Knowledge Base page currently shows 0 documents. Meanwhile, Beacon has 87 files across 14 folders in its knowledge/ directory that power all RAG responses. The Ordino page needs to show these real files, not an empty folder.")
      ]}),
      new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun("Lovable Prompt (copy/paste into Lovable):")] }),

      // Lovable prompt box
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "Fix the Knowledge Base page to show Beacon's actual knowledge files.", font: "Arial", size: 20, bold: true })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "CURRENT STATE: The 'Beacon Knowledge Base' section in the sidebar shows 0 documents. All actual company documents (contracts, plans, etc.) sit in 'All Documents' outside the KB folder. Meanwhile, Beacon's actual knowledge base has 87 markdown files across 14 folders (processes/, dob_notices/, zoning/, building_code/, etc.) that power its RAG responses.", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "WHAT TO BUILD:", font: "Arial", size: 20, bold: true })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "1. Call Beacon's existing API endpoint GET https://beaconrag.up.railway.app/api/knowledge/list to fetch the list of knowledge base files. This returns the folder structure and file names.", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "2. Display these files in the Knowledge Base page organized by folder (processes, dob_notices, zoning, building_code, building_code_1968, building_code_2022, mdl, rcny, hmc, energy_code, communication, historical, case_studies, objections). Show folder names as collapsible sections with file counts.", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "3. Add an 'Upload to Knowledge Base' button that accepts PDF, MD, and TXT files. When a file is uploaded, POST it to https://beaconrag.up.railway.app/api/ingest as multipart form data with the file and a 'source_type' field matching the selected folder.", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "4. Keep the existing 'All Documents' section separate \u2014 that's for company files (contracts, plans, insurance). The Knowledge Base section is specifically for Beacon's reference material.", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 40 }, children: [new TextRun({ text: "5. Update the stats cards at the top to show real numbers: total documents (from the API response), total folders, and document types breakdown.", font: "Arial", size: 20 })] }),
      new Paragraph({ shading: { fill: "F0F7FF", type: ShadingType.CLEAR }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "2196F3", space: 4 } },
        spacing: { after: 200 }, children: [new TextRun({ text: "6. Remove the empty 'Beacon Knowledge Base' folder concept from the sidebar \u2014 replace it with a 'Knowledge Base' nav item that goes to this page.", font: "Arial", size: 20 })] }),

      // ==========================================
      // TASK 3
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Task 3: Clean Up Ordino Documents")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Time: ", bold: true }), new TextRun("15 minutes (manual)"),
        new TextRun({ text: "  |  Priority: ", bold: true }), new TextRun("Medium \u2014 housekeeping")
      ]}),
      new Paragraph({ spacing: { after: 200 }, children: [
        new TextRun("Go through the 11 documents in 'All Documents' and remove the ones that don't belong. The signed proposals, DD reports, and plans that are actual company documents should stay. Anything that was a test upload or duplicate should be deleted.")
      ]}),

      // ==========================================
      // TASK 4
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Task 4: Test Ordino UI Changes")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Time: ", bold: true }), new TextRun("15 minutes"),
        new TextRun({ text: "  |  Priority: ", bold: true }), new TextRun("Medium")
      ]}),
      new Paragraph({ spacing: { after: 200 }, children: [
        new TextRun("Lovable made several UI changes that haven't been tested yet: the thinking/brain animation, expandable source citations, and model badges. Go to ordinov3.lovable.app/chat and verify these work. Also check task card attachments \u2014 they were reported as not showing.")
      ]}),

      // PAGE BREAK
      new Paragraph({ children: [new PageBreak()] }),

      // ==========================================
      // TASK 5
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Task 5: Fix Haiku Model Access")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Time: ", bold: true }), new TextRun("30 minutes"),
        new TextRun({ text: "  |  Priority: ", bold: true }), new TextRun("Medium \u2014 cost savings")
      ]}),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun("Right now both simple and complex questions use Sonnet ($3/MTok input). Simple questions should use Haiku ($0.25-$1/MTok). Both claude-3-5-haiku-20241022 and claude-3-5-haiku-latest returned 404 errors from the Anthropic API.")
      ]}),
      new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun("Steps:")] }),
      new Paragraph({ numbering: { reference: "steps3", level: 0 }, children: [
        new TextRun("Go to console.anthropic.com and check which models your API key has access to")
      ]}),
      new Paragraph({ numbering: { reference: "steps3", level: 0 }, children: [
        new TextRun("Check if there's a billing or plan restriction blocking Haiku")
      ]}),
      new Paragraph({ numbering: { reference: "steps3", level: 0 }, children: [
        new TextRun("Once you find the correct model string, update HAIKU_MODEL in core/llm_client.py and push")
      ]}),
      new Paragraph({ numbering: { reference: "steps3", level: 0 }, spacing: { after: 200 }, children: [
        new TextRun("The model routing decision tree is already built (SONNET_SIGNALS and HAIKU_SIGNALS in llm_client.py) \u2014 just needs the right model string")
      ]}),

      // ==========================================
      // TASK 6
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Task 6: Auto-Ingest Email Newsletters into KB")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: "Time: ", bold: true }), new TextRun("2-3 hours"),
        new TextRun({ text: "  |  Priority: ", bold: true }), new TextRun("Lower \u2014 tackle after wins above")
      ]}),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun("Beacon already has POST /api/ingest-email that parses DOB Buildings News HTML emails and ingests them into Pinecone. But someone has to manually call it. The goal is to automate this so new newsletters and service notices automatically feed into Beacon's brain.")
      ]}),
      new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun("Options:")] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [
        new TextRun({ text: "Gmail API polling: ", bold: true }), new TextRun("Scheduled task (cron or Railway cron) that checks Gmail every hour for new DOB emails, then calls /api/ingest-email. Needs Gmail API OAuth setup in the greenlight-bot or ordinocrm GCP project.")
      ]}),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [
        new TextRun({ text: "Gmail forwarding rule: ", bold: true }), new TextRun("Simpler \u2014 set up a Gmail filter that auto-forwards DOB newsletters to a webhook URL. Beacon receives them and ingests automatically. No OAuth needed.")
      ]}),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 200 }, children: [
        new TextRun({ text: "Manual with Ordino UI: ", bold: true }), new TextRun("Add a 'Paste Newsletter' button to the KB page that accepts raw HTML email content and sends it to /api/ingest-email. Quickest to build, still requires human action.")
      ]}),

      // ==========================================
      // REFERENCE
      // ==========================================
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Quick Reference: Key URLs")] }),
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [3000, 6360],
        rows: [
          new TableRow({ children: [headerCell("Service", 3000), headerCell("URL", 6360)] }),
          new TableRow({ children: [textCell("Beacon (Railway)", 3000, true), textCell("beaconrag.up.railway.app", 6360)] }),
          new TableRow({ children: [textCell("Ordino V2 (Lovable)", 3000, true), textCell("ordinov3.lovable.app", 6360)] }),
          new TableRow({ children: [textCell("Lovable Editor", 3000, true), textCell("lovable.dev/projects/70bf8720-e3b8-4051-b5e6-8e6475ae5ea1", 6360)] }),
          new TableRow({ children: [textCell("Supabase", 3000, true), textCell("mimlfjkisguktiqqkpkm.supabase.co", 6360)] }),
          new TableRow({ children: [textCell("GCloud (Beacon)", 3000, true), textCell("console.cloud.google.com \u2192 project: greenlight-bot", 6360)] }),
          new TableRow({ children: [textCell("GCloud (Ordino)", 3000, true), textCell("console.cloud.google.com \u2192 project: ordinocrm", 6360)] }),
          new TableRow({ children: [textCell("Railway Logs", 3000, true), textCell("railway.com/project/fec8c03c-72bf-4ad5-809f-cec874ee2537/logs", 6360)] }),
          new TableRow({ children: [textCell("Beacon GitHub", 3000, true), textCell("github.com/logic25/beacon", 6360)] }),
          new TableRow({ children: [textCell("Ordino GitHub", 3000, true), textCell("github.com/logic25/ordino-v2", 6360)] }),
        ]
      }),

      new Paragraph({ spacing: { before: 400 }, children: [] }),
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("What Got Done Tonight")] }),
      new Paragraph({ numbering: { reference: "steps4", level: 0 }, children: [
        new TextRun({ text: "Found root cause of @Beacon not responding: ", bold: true }), new TextRun("The greenlight-bot GCP project was pointing to a dead Railway URL (web-production-44b7c). Updated both HTTP endpoint URL and App Home URL to the Supabase edge function.")
      ]}),
      new Paragraph({ numbering: { reference: "steps4", level: 0 }, children: [
        new TextRun({ text: "Confirmed @Beacon receives messages: ", bold: true }), new TextRun("After the URL fix, Beacon started receiving and processing @mention messages in spaces. The error response confirmed end-to-end connectivity works.")
      ]}),
      new Paragraph({ numbering: { reference: "steps4", level: 0 }, children: [
        new TextRun({ text: "Identified Haiku model 404: ", bold: true }), new TextRun("Both claude-3-5-haiku-20241022 and claude-3-5-haiku-latest return 404. Set both models to Sonnet temporarily. File is saved locally, needs push.")
      ]}),
      new Paragraph({ numbering: { reference: "steps4", level: 0 }, children: [
        new TextRun({ text: "Mapped KB architecture: ", bold: true }), new TextRun("87 knowledge files across 14 folders in beacon/knowledge/. Pinecone index 'greenlight-docs' stores embeddings. Ordino KB page disconnected from actual data.")
      ]}),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/confident-charming-meitner/mnt/beacon/Tomorrow_Action_Plan.docx", buffer);
  console.log("Created Tomorrow_Action_Plan.docx");
});
