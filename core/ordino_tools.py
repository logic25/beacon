"""
Ordino Tools for Beacon Agent

These tools allow Beacon to query Ordino's database and take actions.
Each tool is a function that Claude can call via the tool_use API.

Tools are read-only queries unless explicitly marked as actions.
Actions require PM approval before execution.
"""

import os
import re
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Ordino connection via beacon-data-proxy edge function
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
BEACON_ANALYTICS_KEY = os.getenv("BEACON_ANALYTICS_KEY", "")


def _proxy_call(action: str, params: dict = None, user_jwt: str = None) -> dict:
    """Call the beacon-data-proxy edge function on Ordino's Supabase.

    When user_jwt (the forwarded end-user Supabase access token, as a full
    "Bearer <token>" header value) is provided, it is sent as the Authorization
    header so beacon-data-proxy can verify the user and derive their company_id
    for per-tenant scoping. When absent, behavior is unchanged (shared-secret
    only) — non-breaking, so this can deploy before the Ordino side forwards a
    JWT and before the proxy's strict flag is flipped.
    """
    if not SUPABASE_URL or not BEACON_ANALYTICS_KEY:
        logger.warning("Ordino proxy not configured (SUPABASE_URL or BEACON_ANALYTICS_KEY missing)")
        return {"error": "Ordino connection not configured"}

    url = f"{SUPABASE_URL}/functions/v1/beacon-data-proxy"

    headers = {
        "Content-Type": "application/json",
        "x-beacon-key": BEACON_ANALYTICS_KEY,
    }
    if user_jwt:
        headers["Authorization"] = user_jwt

    try:
        resp = httpx.post(
            url,
            json={"action": action, "params": params or {}},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("data", result)
    except Exception as e:
        logger.error(f"Ordino proxy error ({action}): {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════
# TOOL DEFINITIONS (for Claude's tools parameter)
# ═══════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "name": "query_projects",
        "description": "Get all projects with their status, assigned PM, property address, client, services, and readiness percentage. Use this to answer questions about project status, what's pending, how many projects are active, PM workload, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'active', 'completed', 'on_hold', 'cancelled'. Leave empty for all.",
                },
                "assigned_to": {
                    "type": "string",
                    "description": "Filter by PM name (partial match). Leave empty for all PMs.",
                },
                "search": {
                    "type": "string",
                    "description": "Search by property address, client name, or project name.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_project_detail",
        "description": "Get full detail for a specific project including property info, all services with status, contacts, PIS completion, filing readiness, recent activity, and documents. Use when someone asks about a specific project or address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project UUID. Use query_projects first to find the ID.",
                },
                "address": {
                    "type": "string",
                    "description": "Property address to search for (if project_id not known).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_property_violations",
        "description": "Get violations for a property by address or BIN. Returns open and resolved violations with penalty amounts, hearing dates, and status. Use for compliance questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Property address to search for.",
                },
                "bin": {
                    "type": "string",
                    "description": "BIN (Building Identification Number) if known.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter: 'open', 'resolved', or leave empty for all.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_pm_workload",
        "description": "Get workload statistics for project managers: active project count, filing count this month, overdue items, billable hours. Use when asked about PM performance or capacity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pm_name": {
                    "type": "string",
                    "description": "PM name to filter by. Leave empty for all PMs.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "check_filing_readiness",
        "description": "Check which projects are ready to file and which have missing items. Returns readiness percentage and list of missing fields/documents for each project. Use when asked 'what's ready to file' or 'what's missing'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Check a specific project. Leave empty to check all active projects.",
                },
                "min_readiness": {
                    "type": "number",
                    "description": "Only show projects above this readiness % (0-100). Default 0.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_proposals",
        "description": "Get proposals with status, amounts, client info. Use for revenue pipeline questions, proposal tracking, or client lookup.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter: 'draft', 'sent', 'signed', 'declined'. Leave empty for all.",
                },
                "search": {
                    "type": "string",
                    "description": "Search by client name, address, or proposal number.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_invoices",
        "description": "Get invoice data: outstanding amounts, overdue invoices, payment status. Use for billing and AR questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter: 'draft', 'sent', 'paid', 'overdue'. Leave empty for all.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "draft_follow_up_email",
        "description": "Draft a follow-up email to chase missing information for a project. Returns the draft text for PM review — does NOT send. Use when asked to follow up on missing plans, PIS data, or client responses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project to follow up on.",
                },
                "recipient": {
                    "type": "string",
                    "description": "Who to email: 'client', 'architect', 'owner', or a specific name.",
                },
                "missing_items": {
                    "type": "string",
                    "description": "What's missing (e.g., 'plans', 'owner address', 'cost breakdown').",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "query_ordino",
        "description": "General-purpose query tool for ANY data in Ordino. IMPORTANT: If you are not 100% certain of the exact column names for a table, call describe_table FIRST to discover the schema. Do NOT guess column names — wrong names cause errors. For example, the companies table uses 'ein' not 'tax_id', and profiles uses 'monthly_goal' not 'billing_goal'. You can query any table: companies, profiles, properties, projects, proposals, invoices, services, activities, client_contacts, project_contacts, rfi_requests, calendar_events, billing_schedules, change_orders, documents, email threads, and more.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "The database table to query (e.g., 'companies', 'profiles', 'services', 'activities', 'client_contacts', 'calendar_events', 'billing_schedules', 'change_orders')",
                },
                "select": {
                    "type": "string",
                    "description": "Columns to select, Supabase format (e.g., 'id,name,email' or '*' for all). Can include joins like 'id,name,properties(address)'",
                },
                "filters": {
                    "type": "object",
                    "description": "Filters as key-value pairs in Supabase format (e.g., {\"status\": \"eq.active\", \"name\": \"ilike.%green%\"})",
                },
                "order": {
                    "type": "string",
                    "description": "Order by column (e.g., 'created_at.desc')",
                },
                "limit": {
                    "type": "number",
                    "description": "Max rows to return (default 50, max 200)",
                },
            },
            "required": ["table"],
        },
    },
    {
        "name": "describe_table",
        "description": "Discover the columns and data types in any Ordino database table. Use this BEFORE query_ordino when you don't know what columns a table has. For example, to find PM goals: describe_table('profiles') → see 'monthly_goal' column → then query_ordino('profiles', 'display_name,monthly_goal').",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Table name to describe (e.g., 'profiles', 'services', 'invoices')",
                },
            },
            "required": ["table"],
        },
    },
    {
        "name": "who_do_we_know",
        "description": "Find GLE's EXISTING relationship with a company or person in ONE call: contacts we hold, client companies, and past projects where they were the architect, GC, or building owner. Use this whenever someone asks 'who do we know at X', 'do we have a contact at X', 'have we worked with X', or is planning outreach/BD. Prefer this over composing multiple query_ordino calls — it searches all the relationship tables together and returns a consolidated answer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Company or person name to look up (e.g. 'Tishman Speyer', 'Robert Derector', 'Frank Monterisi').",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "dob_capture",
        "description": "GLE's CAPTURE RATE for a developer/owner or architect, from live NYC DOB Open Data (DOB NOW Build, 2020+). Given a name, returns their total DOB filings, how many GLE filed, GLE's share %, and the incumbent expediter to displace — computed both as building-owner and as architect-of-record. Use for 'what's our capture at X', 'how much of X's work do we do', 'who's the incumbent expediter at X', or Client-Health 'are we losing X'. Public data, always current.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Developer/owner or architect name (e.g. 'Tishman Speyer', 'Robert Derector', 'Rudin')."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "dob_team_sheet",
        "description": "The full CAST at a building from live NYC DOB Open Data: top owners, architects/engineers, expediters (filing reps), and whether GLE has filed there. Accepts a street address or a 7-digit BIN. Use for 'who works at 250 Vesey', 'who's the expediter at <building>', team-sheet / competitive-intel questions on a specific building.",
        "input_schema": {
            "type": "object",
            "properties": {
                "building": {"type": "string", "description": "Street address (e.g. '250 Vesey Street') or a BIN (e.g. '1000060')."},
            },
            "required": ["building"],
        },
    },
    {
        "name": "resolve_owner",
        "description": "Given a street address, resolve the building's OWNER + the incumbent expediter + whether GLE files there, from live DOB Open Data. Lighter than dob_team_sheet — use for the reactive BD cascade: a deal-signal names an address, and you need 'who owns it / who files there / are we in'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Street address (e.g. '250 Vesey Street')."},
            },
            "required": ["address"],
        },
    },
    {
        "name": "extract_deal_leads",
        "description": "Turn a raw market-news SIGNAL (a Bisnow/CO/TRD real-estate email) into actionable LEADS. Reads the text, pulls out the concrete opportunities inside it (each a party + space/building that will likely need permit/expediting work), then enriches each with DOB Open Data (owner, incumbent expediter, GLE's gap) and 'who do we know'. Use when someone pastes/points at a market signal and asks to crack it into leads, or 'what's the opportunity here'. This is the reactive BD cascade: signal → the leads inside it → matched to who we know.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The market-signal / news email text to crack into leads."},
            },
            "required": ["text"],
        },
    },
]


# ═══════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════

def execute_tool(tool_name: str, tool_input: dict, user_jwt: str = None) -> str:
    """Execute a tool and return the result as a string.

    user_jwt (the forwarded end-user Supabase access token) is passed through to
    the proxy so beacon-data-proxy can scope queries to the caller's company.
    """
    try:
        # Most tools go directly through the proxy
        proxy_actions = [
            "query_projects", "query_project_detail", "query_property_violations",
            "query_pm_workload", "check_filing_readiness", "query_proposals",
            "query_invoices",
        ]

        if tool_name in proxy_actions:
            result = _proxy_call(tool_name, tool_input, user_jwt=user_jwt)
            return json.dumps(result)
        elif tool_name == "describe_table":
            result = _proxy_call("describe_table", tool_input, user_jwt=user_jwt)
            return json.dumps(result)
        elif tool_name == "query_ordino":
            result = _proxy_call("query_ordino", tool_input, user_jwt=user_jwt)
            return json.dumps(result)
        elif tool_name == "draft_follow_up_email":
            return _draft_follow_up_email(tool_input, user_jwt=user_jwt)
        elif tool_name == "who_do_we_know":
            return _who_do_we_know(tool_input, user_jwt=user_jwt)
        elif tool_name == "dob_capture":
            return _dob_capture(tool_input, user_jwt=user_jwt)
        elif tool_name == "dob_team_sheet":
            return _dob_team_sheet(tool_input, user_jwt=user_jwt)
        elif tool_name == "resolve_owner":
            return _resolve_owner(tool_input, user_jwt=user_jwt)
        elif tool_name == "extract_deal_leads":
            return _extract_deal_leads(tool_input, user_jwt=user_jwt)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return json.dumps({"error": str(e)})


def _who_do_we_know(params: dict, user_jwt: str = None) -> str:
    """Consolidated 'who/how do we know them' search across all relationship tables.

    One tool call fans out to: client_contacts (by person name AND company name),
    companies (client roster), and projects (where they were the architect / GC /
    building owner). Returns contacts we hold + past project relationships + a summary,
    so Beacon can answer 'who do we know at X' reliably instead of improvising queries.
    """
    name = (params.get("name") or "").strip()
    if not name:
        return json.dumps({"error": "name is required"})
    like = f"%{name}%"

    def ilf(col):
        # Ordino's query_ordino expects filters as an ARRAY of {column, operator, value}.
        # Passing a dict (or an "ilike.%x%" string value) applies NO filter → every query
        # returned all company-scoped rows up to the cap (the "25 contacts / 45 projects for
        # everyone" false-positive bug). This builds the shape the proxy actually reads.
        return [{"column": col, "operator": "ilike", "value": like}]

    def q(table, select, filters, limit=25):
        r = _proxy_call("query_ordino", {"table": table, "select": select,
                                         "filters": filters, "limit": limit}, user_jwt=user_jwt)
        if isinstance(r, list):
            return r
        if isinstance(r, dict):
            if "error" in r:
                return []
            for k in ("data", "rows", "results"):
                if isinstance(r.get(k), list):
                    return r[k]
        return []

    # 1) Contacts we hold — match on the person's name OR their company_name.
    contacts, seen = [], set()
    csel = "name,first_name,last_name,email,phone,mobile,company_name,is_referrer,license_type"
    for filt in (ilf("name"), ilf("company_name")):
        for c in q("client_contacts", csel, filt):
            key = f"{c.get('email') or ''}|{c.get('name') or ''}".strip("|")
            if key and key not in seen:
                seen.add(key)
                contacts.append(c)

    # 2) Client companies on our roster.
    companies = q("companies", "id,name,email,phone", ilf("name"))

    # 3) Projects where they were the architect / GC / owner = a professional relationship.
    proj_sel = ("id,name,architect_company_name,architect_contact_name,"
                "gc_company_name,gc_contact_name,building_owner_name")
    projects, pseen = [], set()
    for col, role in (("architect_company_name", "architect"),
                      ("gc_company_name", "general contractor"),
                      ("building_owner_name", "building owner")):
        for p in q("projects", proj_sel, ilf(col), limit=15):
            firm = p.get(col)
            contact = (p.get("architect_contact_name") if col.startswith("architect")
                       else p.get("gc_contact_name") if col.startswith("gc") else None)
            pkey = f"{p.get('id')}|{role}"
            if pkey not in pseen:
                pseen.add(pkey)
                projects.append({"project": p.get("name"), "role": role,
                                 "firm": firm, "contact": contact})

    found = bool(contacts or companies or projects)
    summary = (
        f"We know '{name}': {len(contacts)} contact(s) on file, {len(companies)} client-company "
        f"record(s), and {len(projects)} project(s) where they were an architect/GC/owner."
        if found else
        f"No existing relationship found for '{name}' in Ordino's contacts, clients, or projects."
    )
    return json.dumps({"query": name, "found": found, "summary": summary,
                       "contacts": contacts[:25], "companies": companies[:10],
                       "projects": projects[:20]})


# ═══════════════════════════════════════════════════════
# DOB OPEN DATA TOOLS — live NYC Socrata (public, no auth)
# ═══════════════════════════════════════════════════════

DOB_NOW_BUILD = "w9ak-ipjd"  # DOB NOW: Build job filings, 2020+, has filing_representative_business_name
_OWNER_PLACEHOLDERS = {"PR", "N/A", "NA", "NOT APPLICABLE", "OWNER", "OWNERS REP", "SELF", ""}


def _dob_soql(dataset: str, params: dict) -> list:
    """Query NYC Open Data (Socrata). Public, no auth. Returns rows or []."""
    try:
        resp = httpx.get(f"https://data.cityofnewyork.us/resource/{dataset}.json",
                         params=params, timeout=25.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"DOB Open Data query failed ({dataset}): {e}")
        return []


def _dob_building_where(target: str):
    """Locate a building by BIN or address → (soql_where, label, bin). BIN via GeoSearch,
    fallback to a house_no + street parse. Returns (None, target, None) if unresolvable."""
    t = (target or "").strip()
    # 7-digit-ish BIN passthrough
    if t.isdigit() and 6 <= len(t) <= 7:
        return f"bin='{t}'", f"BIN {t}", t
    # GeoSearch the address → BIN
    try:
        resp = httpx.get("https://geosearch.planninglabs.nyc/v2/search",
                         params={"text": t, "size": 1}, timeout=15.0)
        resp.raise_for_status()
        feats = resp.json().get("features", [])
        if feats:
            props = feats[0].get("properties", {}) or {}
            layer = (props.get("layer") or "").lower()
            housenumber = props.get("housenumber")
            bin_ = ((props.get("addendum", {}) or {}).get("pad", {}) or {}).get("bin")
            label = props.get("label", t)
            # Only trust a PRECISE address match (house number present / layer == 'address').
            # A street ("Park Avenue") or venue/name ("Penn 2") match resolves to an arbitrary
            # building → a confidently WRONG owner, which is worse than no owner. Skip those.
            precise = layer == "address" or bool(housenumber)
            if bin_ and str(bin_).isdigit() and precise:
                return f"bin='{bin_}'", label, str(bin_)
    except Exception as e:
        logger.warning(f"GeoSearch failed for {t!r}: {e}")
    # Fallback: parse "250 Vesey Street" → house_no + street token
    m = re.match(r"\s*(\d+)\s+(.+)", t)
    if m:
        hn = m.group(1)
        st = re.sub(r"[^A-Z0-9 ]", " ", m.group(2).upper())
        st = re.sub(r"\b(STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|PLACE|PL|DRIVE|DR|LANE|LN)\b", "", st).strip()
        tok = (st.split() or [st])[0]
        if tok:
            return f"house_no='{hn}' AND upper(street_name) like '%{tok}%'", t, None
    return None, t, None


def _dob_capture(params: dict, user_jwt: str = None) -> str:
    """GLE's capture rate for an owner/architect from DOB NOW Build (2020+)."""
    name = (params.get("name") or "").strip()
    if not name:
        return json.dumps({"error": "name is required"})
    esc = name.upper().replace("'", "''")

    def cap_for(col):
        rows = _dob_soql(DOB_NOW_BUILD, {
            "$select": "filing_representative_business_name,count(*)",
            "$where": f"upper({col}) like '%{esc}%' AND filing_representative_business_name IS NOT NULL",
            "$group": "filing_representative_business_name",
            "$order": "count(*) desc", "$limit": "50"})
        if not rows:
            return None
        total = sum(int(r["count"]) for r in rows)
        if total < 3:
            return None
        gle = sum(int(r["count"]) for r in rows
                  if "GREEN LIGHT" in (r.get("filing_representative_business_name") or "").upper())
        top = rows[0].get("filing_representative_business_name") or "?"
        first_tok = (esc.split() or [""])[0]
        return {
            "total_filings": total, "gle_filings": gle,
            "gle_capture_pct": round(gle / total * 100, 1) if total else 0,
            "incumbent_expediter": top,
            "self_files": bool(first_tok) and first_tok in top.upper(),
            "top_expediters": [f"{r.get('filing_representative_business_name')} ({r['count']})" for r in rows[:5]],
        }

    as_owner = cap_for("owner_s_business_name")
    as_arch = cap_for("applicant_business_name")
    if not as_owner and not as_arch:
        return json.dumps({"name": name, "found": False,
                           "summary": f"No DOB NOW Build filings found matching '{name}' (2020+). "
                                      f"Note: owners using per-project LLCs are undercounted, and BIS-era "
                                      f"filings aren't in this dataset."})
    parts = []
    if as_owner:
        parts.append(f"as OWNER: GLE {as_owner['gle_capture_pct']}% ({as_owner['gle_filings']}/"
                     f"{as_owner['total_filings']}), incumbent {as_owner['incumbent_expediter']}"
                     + (" [SELF-FILES]" if as_owner['self_files'] else ""))
    if as_arch:
        parts.append(f"as ARCHITECT: GLE {as_arch['gle_capture_pct']}% ({as_arch['gle_filings']}/"
                     f"{as_arch['total_filings']}), incumbent {as_arch['incumbent_expediter']}")
    return json.dumps({"name": name, "found": True,
                       "summary": f"{name} — " + " · ".join(parts),
                       "as_owner": as_owner, "as_architect": as_arch,
                       "caveat": "DOB NOW Build 2020+. LLC-heavy owners undercounted; entity name-matching is fuzzy."})


def _dob_team_sheet(params: dict, user_jwt: str = None) -> str:
    """Full cast at a building: owners, architects, expediters, GLE presence."""
    target = (params.get("building") or params.get("address") or "").strip()
    if not target:
        return json.dumps({"error": "building (address or BIN) is required"})
    where, label, bin_ = _dob_building_where(target)
    if not where:
        return json.dumps({"error": f"Couldn't resolve '{target}' to a building (try a full address or a BIN)."})

    def top(col, n=6):
        rows = _dob_soql(DOB_NOW_BUILD, {
            "$select": f"{col},count(*)", "$where": f"{where} AND {col} IS NOT NULL",
            "$group": col, "$order": "count(*) desc", "$limit": str(n)})
        return [f"{(r.get(col) or '?')} ({r['count']})" for r in rows]

    owners = top("owner_s_business_name")
    architects = top("applicant_business_name")
    expediters = top("filing_representative_business_name")
    gle_rows = _dob_soql(DOB_NOW_BUILD, {
        "$select": "count(*)",
        "$where": f"{where} AND upper(filing_representative_business_name) like '%GREEN LIGHT%'"})
    gle_here = int(gle_rows[0]["count"]) if gle_rows else 0
    if not (owners or architects or expediters):
        return json.dumps({"building": label, "found": False,
                           "summary": f"No DOB NOW Build filings found for {label}."})
    incumbent = expediters[0] if expediters else "?"
    return json.dumps({
        "building": label, "bin": bin_, "found": True,
        "owners": owners, "architects": architects, "expediters": expediters,
        "gle_filings_here": gle_here,
        "summary": f"{label}: incumbent expediter {incumbent}; "
                   f"top owner {owners[0] if owners else '?'}; top architect {architects[0] if architects else '?'}; "
                   f"GLE has {gle_here} filing(s) here.",
    })


def _resolve_owner(params: dict, user_jwt: str = None) -> str:
    """Reactive-cascade helper: address → owner + incumbent expediter + GLE presence."""
    address = (params.get("address") or "").strip()
    if not address:
        return json.dumps({"error": "address is required"})
    where, label, bin_ = _dob_building_where(address)
    if not where:
        return json.dumps({"error": f"Couldn't resolve '{address}' to a building."})
    owners = _dob_soql(DOB_NOW_BUILD, {
        "$select": "owner_s_business_name,count(*)", "$where": f"{where} AND owner_s_business_name IS NOT NULL",
        "$group": "owner_s_business_name", "$order": "count(*) desc", "$limit": "8"})
    owner = next((r["owner_s_business_name"] for r in owners
                  if (r.get("owner_s_business_name") or "").strip().upper() not in _OWNER_PLACEHOLDERS), None)
    reps = _dob_soql(DOB_NOW_BUILD, {
        "$select": "filing_representative_business_name,count(*)",
        "$where": f"{where} AND filing_representative_business_name IS NOT NULL",
        "$group": "filing_representative_business_name", "$order": "count(*) desc", "$limit": "5"})
    incumbent = reps[0].get("filing_representative_business_name") if reps else None
    gle_rows = _dob_soql(DOB_NOW_BUILD, {
        "$select": "count(*)",
        "$where": f"{where} AND upper(filing_representative_business_name) like '%GREEN LIGHT%'"})
    gle_here = int(gle_rows[0]["count"]) if gle_rows else 0
    if not owner and not incumbent:
        return json.dumps({"address": label, "found": False,
                           "summary": f"No DOB NOW Build filings found for {label}."})
    return json.dumps({
        "address": label, "bin": bin_, "found": True,
        "owner": owner, "incumbent_expediter": incumbent, "gle_filings_here": gle_here,
        "summary": f"{label} — owner: {owner or 'unknown'}; incumbent expediter: {incumbent or 'none'}; "
                   f"GLE filings here: {gle_here}."
                   + (" GLE is absent — open wedge." if gle_here == 0 else ""),
    })


_SIGNAL_URL_RE = re.compile(r'https?://[^\s"\'<>)\]]+', re.I)
_SIGNAL_SKIP_URL = re.compile(
    r'(unsubscribe|/unsub|mailto:|utm_source=email|list-manage|/pixel|/track|'
    r'(?:facebook|twitter|x|linkedin|instagram|youtube)\.com|'
    r'\.(?:png|jpe?g|gif|svg|css|js|pdf|ico)(?:\?|$))', re.I)


def _crawl_signal_links(text: str, max_links: int = 4, per_char_cap: int = 2500, total_cap: int = 8000) -> str:
    """Crawl the article links inside a market-news signal so the LLM extracts the REAL
    parties / buildings / addresses from the full story, not just the email blurb.
    Public-web (news) links, SSRF-guarded via net_guard.safe_get (blocks internal IPs)."""
    try:
        from core import net_guard
        from bs4 import BeautifulSoup
    except Exception:
        return ""
    seen, urls = set(), []
    for m in _SIGNAL_URL_RE.finditer(text or ""):
        u = m.group(0).rstrip('.,);]”"')
        if u in seen or _SIGNAL_SKIP_URL.search(u):
            continue
        seen.add(u)
        urls.append(u)
        if len(urls) >= max_links:
            break
    out, total = [], 0
    for u in urls:
        try:
            resp = net_guard.safe_get(u, timeout=12, headers={"User-Agent": "Mozilla/5.0 (BeaconBD/1.0)"})
            if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "").lower():
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript", "aside"]):
                tag.decompose()
            title = soup.title.get_text(strip=True) if soup.title else u
            body = soup.get_text(" ", strip=True)
            if len(body) < 200:
                continue
            snippet = body[:per_char_cap]
            out.append(f"[Article: {title}]\n{snippet}")
            total += len(snippet)
            if total >= total_cap:
                break
        except Exception as e:
            logger.info(f"[signal-crawl] skipped {u[:70]}: {e}")
            continue
    if out:
        logger.info(f"[signal-crawl] pulled {len(out)} linked article(s), {total} chars")
    return "\n\n".join(out)


def _extract_deal_leads(params: dict, user_jwt: str = None) -> str:
    """Reactive cascade: crack a market-news signal into enriched, actionable leads.

    1) LLM-extract the concrete opportunities (party + space/address + deal type + angle).
    2) For each with an address → resolve_owner (owner / incumbent / GLE gap).
    3) who_do_we_know on the party AND the resolved owner → the warm path in.
    """
    text = (params.get("text") or "").strip()
    if not text:
        return json.dumps({"error": "text is required"})

    # Crawl the article links so extraction sees the REAL parties/buildings/addresses from
    # the full story, not just the newsletter blurb (the Signals requirement).
    crawled = _crawl_signal_links(text)
    enriched = (text + "\n\n--- LINKED ARTICLE CONTENT ---\n" + crawled) if crawled else text
    # The source article links, so the UI can offer "read the full article".
    article_urls, _seen_u = [], set()
    for _m in _SIGNAL_URL_RE.finditer(text or ""):
        _u = _m.group(0).rstrip('.,);]”"')
        if _u not in _seen_u and not _SIGNAL_SKIP_URL.search(_u):
            _seen_u.add(_u)
            article_urls.append(_u)
        if len(article_urls) >= 5:
            break

    # 1) Extract opportunities
    try:
        import anthropic
        from config import get_settings
        client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        prompt = (
            "You are a senior BD analyst for Green Light Expediting, a NYC permit-expediting firm. "
            "From this real-estate news AND the linked article text, extract the CONCRETE opportunities — "
            "each a specific party and/or building that will likely need DOB permit / expediting / filing "
            "work. Reason about WHY it needs filings and what GLE would do. Ignore pure macro/finance news.\n"
            'Return STRICT JSON: {"opportunities":[{"party":str,"address":str|null,'
            '"deal_type":"lease|sale|development|renovation|other","angle":str,"why":str}]}\n'
            "- party = the ACTUAL company/person name. Use the real entity name when it's clear "
            "(e.g. 'Snap Inc.' rather than 'Snapchat parent company', 'Alexandria Real Estate Equities' "
            "as written) so it can be matched against our CRM; if you're unsure of the real name, use it "
            "as stated in the article — do not guess a name.\n"
            "- address = ONLY an address or building name that appears VERBATIM in the article text — copy it "
            "as written. NEVER invent, guess, or complete an address; do not add a street number the article "
            "doesn't state. If the article gives only a neighborhood/area with no specific building, use null.\n"
            "- angle = the specific permit work (tenant fit-out, base-building/white-box, new building, "
            "conversion, facade, etc.).\n"
            "- why = 1-2 sentences on WHY this generates filing/expediting work and the timing "
            "(e.g. 'A $450M retail repositioning = ALT-2 fit-out + facade filings once the buyer closes; "
            "the pre-filing window is now').\n\n"
            f"News + linked article text:\n{enriched[:12000]}\n\nJSON only."
        )
        msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=1500,
                                     temperature=0, messages=[{"role": "user", "content": prompt}])
        raw = re.sub(r"^```(?:json)?|```$", "", msg.content[0].text.strip(), flags=re.I | re.M).strip()
        opps = (json.loads(raw) or {}).get("opportunities", [])
    except Exception as e:
        logger.warning(f"extract_deal_leads: extraction failed: {e}")
        return json.dumps({"error": f"Could not extract opportunities: {e}"})

    if not opps:
        return json.dumps({"found": False, "summary": "No concrete permit/expediting opportunities in this signal (looks like macro/finance news)."})

    # 2 + 3) Enrich each opportunity
    leads, wdwk_cache = [], {}

    def wdwk(name):
        if not name:
            return None
        key = name.strip().lower()
        if key not in wdwk_cache:
            try:
                wdwk_cache[key] = json.loads(_who_do_we_know({"name": name}, user_jwt=user_jwt))
            except Exception:
                wdwk_cache[key] = None
        r = wdwk_cache[key]
        return r if (r and r.get("found")) else None

    for o in opps[:5]:
        lead = {"party": o.get("party"), "deal_type": o.get("deal_type"),
                "angle": o.get("angle"), "why": o.get("why"), "address": o.get("address")}
        # property / owner enrichment
        if o.get("address"):
            prop = json.loads(_resolve_owner({"address": o["address"]}))
            if prop.get("found"):
                lead["property"] = {"owner": prop.get("owner"),
                                    "incumbent_expediter": prop.get("incumbent_expediter"),
                                    "gle_filings_here": prop.get("gle_filings_here"),
                                    "resolved_address": prop.get("address")}
        # who do we know — the tenant/party AND the building owner
        owner = (lead.get("property") or {}).get("owner")
        wk_party = wdwk(o.get("party"))
        wk_owner = wdwk(owner)
        rels = []
        if wk_party:
            rels.append(f"{o.get('party')}: {wk_party['summary']}")
        if wk_owner and owner:
            rels.append(f"{owner} (building owner): {wk_owner['summary']}")
        lead["who_we_know"] = rels or ["No existing relationship on file — cold."]
        leads.append(lead)

    return json.dumps({
        "found": True, "lead_count": len(leads), "leads": leads,
        "story": (crawled[:6000] if crawled else ""),  # full crawled article text so the UI can show "read the full story"
        "article_urls": article_urls,  # source links so the UI can offer "read the article"
        "summary": f"Cracked the signal into {len(leads)} lead(s). "
                   "Each includes the party, the permit angle, the building owner + incumbent expediter "
                   "(where an address was given), and who we already know — the warm path in.",
    })


def _draft_follow_up_email(params: dict, user_jwt: str = None) -> str:
    """Draft a follow-up email (does not send)."""
    project_id = params.get("project_id")
    recipient = params.get("recipient", "client")
    missing = params.get("missing_items", "required information")

    if not project_id:
        return json.dumps({"error": "project_id is required"})

    # Get project detail from proxy
    detail = _proxy_call("query_project_detail", {"project_id": project_id}, user_jwt=user_jwt)

    if isinstance(detail, dict) and "error" in detail:
        return json.dumps(detail)

    project = detail if isinstance(detail, dict) else {}
    prop = project.get("properties") or {}
    address = prop.get("address", "the project")
    filing_type = project.get("filing_type", "filing")

    draft = {
        "action": "draft_email",
        "requires_pm_approval": True,
        "to": recipient,
        "subject": f"Follow Up: {address} — {missing}",
        "body": f"""Hi,

Following up on the {filing_type} for {address}.

We still need the following to proceed:
- {missing}

Could you please provide this at your earliest convenience? We'd like to keep the filing on track.

Thank you,
Green Light Expediting""",
        "note": "This is a DRAFT. The PM must review and send.",
    }

    return json.dumps(draft)


# Legacy implementations removed — all queries go through beacon-data-proxy
