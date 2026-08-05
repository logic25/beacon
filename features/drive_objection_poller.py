"""
Drive Objection Poller — the closed-loop objection moat.

Chris exports DOB NOW objections per job (renamed to the Job#, e.g. B01187662-I1.xlsx)
into a shared Google Drive folder. Today someone hand-loads them into Beacon. This
poller reads that folder on a schedule, parses each NEW export into an
objection-intelligence doc, and ingests it into Beacon — no human in the loop, so
Beacon gets smarter with every batch Chris exports.

Idempotent: an export whose Job# already has a KB doc is skipped, so the loop is safe
to run as often as you like and survives restarts (state lives in the KB, not on disk).

Google access uses the Drive v3 REST API with a service-account bearer token — the same
pattern the Gmail poller uses — so it needs NO extra pip deps (no google-api-python-client,
which drags in a conflicting protobuf).

Setup (one-time):
  1. Reuse the existing service account (GOOGLE_SERVICE_ACCOUNT_JSON / _FILE).
  2. Give it read access to the objection folder — either share the folder with the
     service-account email, OR set DRIVE_IMPERSONATE_USER to a Workspace user who can
     see it (domain-wide delegation, same as the Gmail poller).
  3. Set DRIVE_OBJECTIONS_FOLDER_ID to the folder's Drive ID.
The poller stays completely inert until DRIVE_OBJECTIONS_FOLDER_ID is set, so deploying
this before setup is a no-op.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
POLL_INTERVAL = int(os.getenv("DRIVE_POLL_INTERVAL", "86400"))  # daily by default
FOLDER_ID = os.getenv("DRIVE_OBJECTIONS_FOLDER_ID", "").strip()
IMPERSONATE = os.getenv("DRIVE_IMPERSONATE_USER", os.getenv("BEACON_EMAIL", "")).strip()
SELF_URL = os.getenv("BEACON_SELF_URL", f"http://localhost:{os.getenv('PORT', '8080')}").rstrip("/")
BEACON_KEY = os.getenv("BEACON_ANALYTICS_KEY", "")

DRIVE_API = "https://www.googleapis.com/drive/v3"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"

# A DOB NOW job number: 1 letter (borough) + 8 digits, optional -I1/-S2/-P1 filing suffix.
_JOB_RE = re.compile(r"([A-Z]\d{8}(?:-[A-Z]\d+)?)", re.I)

# Fuzzy header → canonical field. First match wins per column.
_COLMAP = [
    ("objection", ["objection", "deficiency", "comment", "condition", "issue"]),
    ("code", ["code", "reference", "ac ", "ac#", "section", "zr", "bc "]),
    ("examiner", ["examiner", "reviewer", "plan exam"]),
    ("status", ["status", "resolution", "disposition"]),
    ("details", ["detail", "reasoning", "notes", "response", "remarks", "description"]),
    ("date", ["date", "created", "issued"]),
]


def _job_from_name(name: str) -> str:
    m = _JOB_RE.search(name or "")
    return m.group(1).upper() if m else ""


def _map_columns(header) -> dict:
    """header cell index -> canonical field name."""
    out = {}
    for idx, cell in enumerate(header):
        low = (cell or "").strip().lower()
        if not low:
            continue
        for field, needles in _COLMAP:
            if field in out.values():
                continue
            if any(n in low for n in needles):
                out[idx] = field
                break
    return out


def _to_markdown(job: str, rows) -> str:
    """Render parsed objection rows into an objection-intelligence KB doc."""
    lines = [
        f"# DOB NOW Objection Intelligence — Job {job}",
        "",
        "Real DOB plan-examination objections from a GLE filing, auto-imported from the "
        "objection-export Drive folder. Each entry: the objection, its code/AC reference, "
        "the examiner, the status, and the reasoning where present. Treat as a PATTERN of "
        "what this work type gets flagged for — not fixed values for any one project.",
        "",
        f"**Job:** {job}",
        "",
    ]
    for i, r in enumerate(rows, 1):
        obj = (r.get("objection") or "").strip()
        if not obj:
            continue
        bits = [f"- **#{i}** {obj}"]
        if r.get("code"):
            bits.append(f"(ref: {r['code'].strip()})")
        if r.get("examiner"):
            bits.append(f"— examiner: {r['examiner'].strip()}")
        if r.get("status"):
            bits.append(f"[{r['status'].strip()}]")
        line = " ".join(bits)
        if r.get("details") and r["details"].strip().lower() != obj.lower():
            line += f"\n    - Details: {r['details'].strip()}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def parse_xlsx_bytes(content: bytes):
    """Parse DOB NOW objection-export .xlsx bytes into objection rows.
    Pure (no Drive/network) so the /api/ingest upload path can reuse it — a person can
    drop an export into Ordino's KB and it parses server-side, same as the poller does."""
    # DOB NOW's export engine writes a stylesheet openpyxl can't parse ("expected Fill").
    # We only need cell VALUES, so read the sheet XML directly (stdlib) — robust and
    # dependency-light, immune to the malformed stylesheet.
    import zipfile
    import re as _re
    from xml.etree import ElementTree as _ET
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except Exception:
        return []
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        _r = _ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in _r.findall(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    sheets = sorted(n for n in z.namelist() if _re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        return []

    def _col(ref):
        m = _re.match(r"[A-Z]+", ref or "")
        n = 0
        for ch in (m.group(0) if m else ""):
            n = n * 26 + (ord(ch) - 64)
        return n - 1

    grid = []
    root = _ET.fromstring(z.read(sheets[0]))
    for row in root.iter(f"{NS}row"):
        cells, maxc = {}, -1
        for c in row.findall(f"{NS}c"):
            ci = _col(c.get("r", ""))
            t = c.get("t")
            v = c.find(f"{NS}v")
            isn = c.find(f"{NS}is")
            if t == "s" and v is not None:
                try:
                    val = shared[int(v.text)]
                except Exception:
                    val = ""
            elif t == "inlineStr" and isn is not None:
                val = "".join(x.text or "" for x in isn.iter(f"{NS}t"))
            else:
                val = (v.text if v is not None else "") or ""
            cells[ci] = val.strip()
            if ci > maxc:
                maxc = ci
        grid.append([cells.get(i, "") for i in range(maxc + 1)] if maxc >= 0 else [])
    grid = [r for r in grid if any(c for c in r)]
    if not grid:
        return []
    # Find the header row: the first row whose cells map to >=2 canonical fields incl. objection.
    header_idx, colmap = None, {}
    for i, row in enumerate(grid[:15]):
        m = _map_columns(row)
        if len(set(m.values())) >= 2 and "objection" in m.values():
            header_idx, colmap = i, m
            break
    rows = []
    if header_idx is not None:
        for row in grid[header_idx + 1:]:
            rec = {}
            for idx, field in colmap.items():
                if idx < len(row):
                    rec[field] = row[idx]
            if rec.get("objection"):
                rows.append(rec)
    else:
        # No clear header — don't lose the data: emit each non-empty row as an objection.
        for row in grid:
            text = " | ".join(c for c in row if c)
            if text:
                rows.append({"objection": text})
    return rows


def _now() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


class DriveObjectionPoller:
    """Polls a Drive folder of DOB NOW objection exports and ingests new ones."""

    def __init__(self, retriever=None, analytics_db=None):
        self.retriever = retriever
        self.analytics_db = analytics_db
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.last_run = ""
        self.last_error = ""
        self.ingested_total = 0

    # ---- lifecycle ----
    def start(self):
        if not FOLDER_ID:
            logger.info("[Drive Poller] DRIVE_OBJECTIONS_FOLDER_ID not set — poller inert.")
            return
        if self.retriever is None:
            logger.warning("[Drive Poller] no retriever — not starting.")
            return
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="drive-objection-poller")
        self._thread.start()
        logger.info(f"[Drive Poller] started — folder={FOLDER_ID}, every {POLL_INTERVAL}s, impersonate={IMPERSONATE or '(none)'}")

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        return {
            "enabled": bool(FOLDER_ID),
            "folder_id": FOLDER_ID,
            "interval_seconds": POLL_INTERVAL,
            "impersonate": IMPERSONATE,
            "last_run": self.last_run,
            "last_error": self.last_error,
            "ingested_total": self.ingested_total,
        }

    def _poll_loop(self):
        time.sleep(45)  # let the app settle before the first cycle
        while not self._stop.is_set():
            try:
                n = self.sync_once()
                self.last_run = _now()
                self.last_error = ""
                if n:
                    logger.info(f"[Drive Poller] ingested {n} new objection export(s)")
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"[Drive Poller] cycle failed: {e}", exc_info=True)
            self._stop.wait(POLL_INTERVAL)

    # ---- google auth (REST, no google-api-python-client) ----
    def _get_credentials(self):
        from google.oauth2 import service_account
        sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_json:
            info = json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
        else:
            path = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "google-chat-bot-key.json"))
            creds = service_account.Credentials.from_service_account_file(str(path), scopes=DRIVE_SCOPES)
        # Domain-wide delegation: act as a user who can see the folder (same as Gmail poller).
        if IMPERSONATE:
            creds = creds.with_subject(IMPERSONATE)
        return creds

    def _auth_headers(self) -> dict:
        from google.auth.transport.requests import Request as GARequest
        creds = self._get_credentials()
        creds.refresh(GARequest())
        return {"Authorization": f"Bearer {creds.token}"}

    # ---- core sync ----
    def sync_once(self, folder_id: Optional[str] = None) -> int:
        """List the folder and ingest any export whose Job# isn't already in the KB.
        Returns the number of new exports ingested."""
        import requests
        fid = (folder_id or FOLDER_ID).strip()
        if not fid:
            raise RuntimeError("no folder id configured (DRIVE_OBJECTIONS_FOLDER_ID)")
        headers = self._auth_headers()
        q = (f"'{fid}' in parents and trashed = false "
             f"and (mimeType = '{XLSX_MIME}' or mimeType = '{SHEET_MIME}')")
        files, page = [], None
        while True:
            params = {
                "q": q,
                "fields": "nextPageToken, files(id,name,mimeType,modifiedTime)",
                "pageSize": 200,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page:
                params["pageToken"] = page
            resp = requests.get(f"{DRIVE_API}/files", headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            files += data.get("files", [])
            page = data.get("nextPageToken")
            if not page:
                break

        already = self._already_ingested_jobs()
        count = 0
        for f in files:
            job = _job_from_name(f["name"])
            if not job:
                logger.info(f"[Drive Poller] '{f['name']}': no Job# in name — skip")
                continue
            if job in already:
                continue  # idempotent
            try:
                rows = self._parse_export(headers, f)
                if not rows:
                    logger.info(f"[Drive Poller] '{f['name']}': no objection rows — skip")
                    continue
                self._ingest(job, _to_markdown(job, rows), f["name"])
                count += 1
                self.ingested_total += 1
                already.add(job)
            except Exception as e:
                logger.warning(f"[Drive Poller] failed on '{f['name']}': {e}")
        return count

    def _parse_export(self, headers: dict, f: dict):
        import openpyxl
        import requests
        fid = f["id"]
        if f["mimeType"] == SHEET_MIME:
            url = f"{DRIVE_API}/files/{fid}/export"
            params = {"mimeType": XLSX_MIME}
        else:
            url = f"{DRIVE_API}/files/{fid}"
            params = {"alt": "media", "supportsAllDrives": "true"}
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
        ws = wb.active
        grid = [[("" if c is None else str(c)).strip() for c in r] for r in ws.iter_rows(values_only=True)]
        grid = [r for r in grid if any(c for c in r)]
        if not grid:
            return []
        # Find the header row: the first row whose cells map to >=2 canonical fields incl. objection.
        header_idx, colmap = None, {}
        for i, row in enumerate(grid[:15]):
            m = _map_columns(row)
            if len(set(m.values())) >= 2 and "objection" in m.values():
                header_idx, colmap = i, m
                break
        rows = []
        if header_idx is not None:
            for row in grid[header_idx + 1:]:
                rec = {}
                for idx, field in colmap.items():
                    if idx < len(row):
                        rec[field] = row[idx]
                if rec.get("objection"):
                    rows.append(rec)
        else:
            # No clear header — don't lose the data: emit each non-empty row as an objection.
            for row in grid:
                text = " | ".join(c for c in row if c)
                if text:
                    rows.append({"objection": text})
        return rows

    def _already_ingested_jobs(self) -> set:
        """Job#s that already have a KB doc, so we never re-ingest. Reads the KB list."""
        jobs = set()
        try:
            import urllib.request
            req = urllib.request.Request(f"{SELF_URL}/api/knowledge/list",
                                         headers={"x-beacon-key": BEACON_KEY})
            data = json.load(urllib.request.urlopen(req, timeout=30))
            for d in data.get("details", []):
                j = _job_from_name(d.get("filename", ""))
                if j:
                    jobs.add(j)
        except Exception as e:
            logger.warning(f"[Drive Poller] couldn't read KB list for idempotency: {e}")
        return jobs

    def _ingest(self, job: str, markdown: str, src_name: str):
        """Ingest via the normal /api/ingest path so manifest/tagging/attribution all apply."""
        import urllib.request
        body = json.dumps({
            "text": markdown,
            "title": f"DOB NOW Objections — {job}",
            "source_type": "objection_intelligence",
            "jurisdiction": "NYC",
            "metadata": {
                "folder": "objections",
                "jurisdiction": "NYC",
                "uploaded_by": "Chris Henry (auto: Drive)",
                "source_export": src_name,
            },
        }).encode()
        req = urllib.request.Request(f"{SELF_URL}/api/ingest", data=body,
                                     headers={"x-beacon-key": BEACON_KEY, "Content-Type": "application/json"},
                                     method="POST")
        r = json.load(urllib.request.urlopen(req, timeout=120))
        logger.info(f"[Drive Poller] ingested Job {job}: {r.get('chunks_created', '?')} chunks (from '{src_name}')")
        if self.analytics_db and hasattr(self.analytics_db, "notify_ingest"):
            try:
                self.analytics_db.notify_ingest(
                    title=f"New objection data: Job {job}",
                    body=f"Auto-imported {r.get('chunks_created', '?')} objection chunks from the Drive export folder.",
                    link="/documents",
                )
            except Exception:
                pass
