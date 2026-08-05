"""
Ordino Tools for Beacon Agent

These tools allow Beacon to query Ordino's database and take actions.
Each tool is a function that Claude can call via the tool_use API.

Tools are read-only queries unless explicitly marked as actions.
Actions require PM approval before execution.
"""

import os
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
    like = f"ilike.%{name}%"

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
    for filt in ({"name": like}, {"company_name": like}):
        for c in q("client_contacts", csel, filt):
            key = f"{c.get('email') or ''}|{c.get('name') or ''}".strip("|")
            if key and key not in seen:
                seen.add(key)
                contacts.append(c)

    # 2) Client companies on our roster.
    companies = q("companies", "id,name,email,phone", {"name": like})

    # 3) Projects where they were the architect / GC / owner = a professional relationship.
    proj_sel = ("id,name,architect_company_name,architect_contact_name,"
                "gc_company_name,gc_contact_name,building_owner_name")
    projects, pseen = [], set()
    for col, role in (("architect_company_name", "architect"),
                      ("gc_company_name", "general contractor"),
                      ("building_owner_name", "building owner")):
        for p in q("projects", proj_sel, {col: like}, limit=15):
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
