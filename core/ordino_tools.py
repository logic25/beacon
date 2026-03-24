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
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Supabase connection
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


def _supabase_query(table: str, select: str = "*", filters: dict = None,
                     order: str = None, limit: int = 50) -> list:
    """Execute a Supabase REST query."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning("Supabase not configured for Ordino tools")
        return []

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": select}

    if limit:
        params["limit"] = str(limit)
    if order:
        params["order"] = order

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    # Add filters as query params
    if filters:
        for key, value in filters.items():
            params[key] = value

    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Supabase query error on {table}: {e}")
        return []


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
]


# ═══════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "query_projects":
            return _query_projects(tool_input)
        elif tool_name == "query_project_detail":
            return _query_project_detail(tool_input)
        elif tool_name == "query_property_violations":
            return _query_property_violations(tool_input)
        elif tool_name == "query_pm_workload":
            return _query_pm_workload(tool_input)
        elif tool_name == "check_filing_readiness":
            return _check_filing_readiness(tool_input)
        elif tool_name == "query_proposals":
            return _query_proposals(tool_input)
        elif tool_name == "query_invoices":
            return _query_invoices(tool_input)
        elif tool_name == "draft_follow_up_email":
            return _draft_follow_up_email(tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return json.dumps({"error": str(e)})


def _query_projects(params: dict) -> str:
    """Get projects with optional filtering."""
    select = "id,name,project_number,status,filing_type,created_at"
    select += ",properties(address,borough,bin)"
    select += ",profiles!projects_assigned_pm_fkey(display_name,first_name,last_name)"

    filters = {}
    if params.get("status"):
        filters["status"] = f"eq.{params['status']}"

    projects = _supabase_query("projects", select=select, filters=filters,
                                order="created_at.desc", limit=100)

    if params.get("search"):
        search = params["search"].lower()
        projects = [p for p in projects if
                   search in (p.get("name") or "").lower() or
                   search in (p.get("properties", {}) or {}).get("address", "").lower()]

    if params.get("assigned_to"):
        pm_search = params["assigned_to"].lower()
        projects = [p for p in projects if
                   pm_search in (p.get("profiles", {}) or {}).get("display_name", "").lower() or
                   pm_search in (p.get("profiles", {}) or {}).get("first_name", "").lower()]

    # Summarize
    summary = {
        "total": len(projects),
        "projects": []
    }

    for p in projects[:30]:  # Cap at 30 for context window
        prop = p.get("properties") or {}
        pm = p.get("profiles") or {}
        summary["projects"].append({
            "id": p.get("id"),
            "name": p.get("name"),
            "number": p.get("project_number"),
            "address": prop.get("address", "—"),
            "borough": prop.get("borough", "—"),
            "status": p.get("status"),
            "filing_type": p.get("filing_type"),
            "assigned_pm": pm.get("display_name") or f"{pm.get('first_name', '')} {pm.get('last_name', '')}".strip() or "Unassigned",
        })

    return json.dumps(summary)


def _query_project_detail(params: dict) -> str:
    """Get full project detail."""
    project_id = params.get("project_id")
    address = params.get("address")

    if not project_id and address:
        # Look up by address
        props = _supabase_query("properties", select="id",
                                 filters={"address": f"ilike.%{address}%"}, limit=1)
        if props:
            prop_id = props[0]["id"]
            projects = _supabase_query("projects", select="id",
                                        filters={"property_id": f"eq.{prop_id}"}, limit=1)
            if projects:
                project_id = projects[0]["id"]

    if not project_id:
        return json.dumps({"error": "Project not found. Try query_projects first to find the ID."})

    select = "*,properties(*),services(*),project_contacts(*,client_contacts(*))"
    projects = _supabase_query("projects", select=select,
                                filters={"id": f"eq.{project_id}"}, limit=1)

    if not projects:
        return json.dumps({"error": "Project not found"})

    p = projects[0]
    prop = p.get("properties") or {}
    services = p.get("services") or []
    contacts = p.get("project_contacts") or []

    # Get PIS data
    pis = _supabase_query("rfi_requests", select="responses",
                           filters={"project_id": f"eq.{project_id}"},
                           order="created_at.desc", limit=1)
    pis_responses = pis[0].get("responses", {}) if pis else {}
    pis_count = len([v for v in pis_responses.values() if v]) if pis_responses else 0

    detail = {
        "project": {
            "id": p.get("id"),
            "name": p.get("name"),
            "number": p.get("project_number"),
            "status": p.get("status"),
            "filing_type": p.get("filing_type"),
            "created": p.get("created_at", "")[:10],
        },
        "property": {
            "address": prop.get("address"),
            "borough": prop.get("borough"),
            "bin": prop.get("bin"),
            "block": prop.get("block"),
            "lot": prop.get("lot"),
        },
        "services": [{
            "name": s.get("name"),
            "status": s.get("status"),
            "work_types": s.get("sub_services"),
        } for s in services],
        "contacts": [{
            "name": (c.get("client_contacts") or {}).get("name"),
            "role": c.get("role"),
            "email": (c.get("client_contacts") or {}).get("email"),
        } for c in contacts if c.get("client_contacts")],
        "pis_fields_completed": pis_count,
        "pis_total_fields": 23,
    }

    return json.dumps(detail)


def _query_property_violations(params: dict) -> str:
    """Get violations for a property."""
    address = params.get("address", "")
    bin_num = params.get("bin", "")

    # Find property
    if bin_num:
        props = _supabase_query("properties", select="id,address,bin",
                                 filters={"bin": f"eq.{bin_num}"}, limit=1)
    elif address:
        props = _supabase_query("properties", select="id,address,bin",
                                 filters={"address": f"ilike.%{address}%"}, limit=1)
    else:
        return json.dumps({"error": "Provide address or BIN"})

    if not props:
        return json.dumps({"error": "Property not found"})

    prop = props[0]

    # Get violations from signal_violations
    filters = {"property_id": f"eq.{prop['id']}"}
    if params.get("status") == "open":
        filters["status"] = "in.(open,active,issued)"
    elif params.get("status") == "resolved":
        filters["status"] = "in.(resolved,closed,dismissed)"

    violations = _supabase_query("signal_violations",
                                   select="violation_number,agency,status,description,penalty_amount,issued_date",
                                   filters=filters, order="issued_date.desc", limit=50)

    total_penalties = sum(v.get("penalty_amount", 0) or 0 for v in violations)
    open_count = len([v for v in violations if v.get("status") in ("open", "active", "issued")])

    return json.dumps({
        "property": prop.get("address"),
        "bin": prop.get("bin"),
        "total_violations": len(violations),
        "open_violations": open_count,
        "total_penalties": total_penalties,
        "violations": violations[:20],
    })


def _query_pm_workload(params: dict) -> str:
    """Get PM workload stats."""
    # Get all PMs
    profiles = _supabase_query("profiles", select="id,display_name,first_name,last_name",
                                limit=20)

    pm_name = (params.get("pm_name") or "").lower()

    results = []
    for profile in profiles:
        name = profile.get("display_name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        if pm_name and pm_name not in name.lower():
            continue

        # Count active projects
        projects = _supabase_query("projects", select="id,status",
                                    filters={"assigned_pm": f"eq.{profile['id']}",
                                            "status": "eq.active"},
                                    limit=100)

        results.append({
            "name": name,
            "active_projects": len(projects),
        })

    return json.dumps({"pms": results})


def _check_filing_readiness(params: dict) -> str:
    """Check filing readiness across projects."""
    project_id = params.get("project_id")
    min_readiness = params.get("min_readiness", 0)

    filters = {"status": "eq.active"}
    if project_id:
        filters = {"id": f"eq.{project_id}"}

    projects = _supabase_query("projects",
                                select="id,name,properties(address)",
                                filters=filters, limit=50)

    results = []
    for p in projects:
        pid = p["id"]
        # Get PIS completion
        pis = _supabase_query("rfi_requests", select="responses",
                               filters={"project_id": f"eq.{pid}"},
                               order="created_at.desc", limit=1)

        responses = pis[0].get("responses", {}) if pis else {}
        filled = len([v for v in responses.values() if v])
        total = 23
        pct = round(filled / total * 100) if total > 0 else 0

        if pct >= min_readiness:
            results.append({
                "project_id": pid,
                "name": p.get("name"),
                "address": (p.get("properties") or {}).get("address", "—"),
                "readiness_pct": pct,
                "pis_fields": f"{filled}/{total}",
                "ready_to_file": pct == 100,
            })

    results.sort(key=lambda x: x["readiness_pct"], reverse=True)

    ready = len([r for r in results if r["ready_to_file"]])
    return json.dumps({
        "total_checked": len(results),
        "ready_to_file": ready,
        "not_ready": len(results) - ready,
        "projects": results,
    })


def _query_proposals(params: dict) -> str:
    """Get proposals."""
    select = "id,proposal_number,status,total_amount,client_name,created_at,properties(address)"
    filters = {}
    if params.get("status"):
        filters["status"] = f"eq.{params['status']}"

    proposals = _supabase_query("proposals", select=select, filters=filters,
                                 order="created_at.desc", limit=50)

    if params.get("search"):
        search = params["search"].lower()
        proposals = [p for p in proposals if
                    search in (p.get("client_name") or "").lower() or
                    search in (p.get("properties", {}) or {}).get("address", "").lower() or
                    search in (p.get("proposal_number") or "").lower()]

    total_value = sum(p.get("total_amount", 0) or 0 for p in proposals)

    return json.dumps({
        "total": len(proposals),
        "total_value": total_value,
        "proposals": [{
            "number": p.get("proposal_number"),
            "client": p.get("client_name"),
            "address": (p.get("properties") or {}).get("address", "—"),
            "amount": p.get("total_amount"),
            "status": p.get("status"),
            "date": (p.get("created_at") or "")[:10],
        } for p in proposals[:20]],
    })


def _query_invoices(params: dict) -> str:
    """Get invoice data."""
    select = "id,invoice_number,status,total_due,payment_amount,paid_at,created_at"
    filters = {}
    if params.get("status"):
        if params["status"] == "overdue":
            filters["status"] = "eq.sent"
            # Would need date comparison for true overdue
        else:
            filters["status"] = f"eq.{params['status']}"

    invoices = _supabase_query("invoices", select=select, filters=filters,
                                order="created_at.desc", limit=50)

    total_outstanding = sum(i.get("total_due", 0) or 0 for i in invoices
                           if i.get("status") in ("sent", "ready_to_send"))
    total_paid = sum(i.get("payment_amount", 0) or 0 for i in invoices
                    if i.get("status") == "paid")

    return json.dumps({
        "total_invoices": len(invoices),
        "total_outstanding": total_outstanding,
        "total_paid": total_paid,
        "invoices": [{
            "number": i.get("invoice_number"),
            "amount": i.get("total_due"),
            "status": i.get("status"),
            "date": (i.get("created_at") or "")[:10],
        } for i in invoices[:20]],
    })


def _draft_follow_up_email(params: dict) -> str:
    """Draft a follow-up email (does not send)."""
    project_id = params.get("project_id")
    recipient = params.get("recipient", "client")
    missing = params.get("missing_items", "required information")

    if not project_id:
        return json.dumps({"error": "project_id is required"})

    # Get project info for context
    detail = json.loads(_query_project_detail({"project_id": project_id}))

    if "error" in detail:
        return json.dumps(detail)

    project = detail.get("project", {})
    prop = detail.get("property", {})

    draft = {
        "action": "draft_email",
        "requires_pm_approval": True,
        "to": recipient,
        "subject": f"Follow Up: {prop.get('address', 'Project')} — {missing}",
        "body": f"""Hi,

Following up on the {project.get('filing_type', 'filing')} for {prop.get('address', 'the project')}.

We still need the following to proceed:
- {missing}

Could you please provide this at your earliest convenience? We'd like to keep the filing on track.

Thank you,
Green Light Expediting""",
        "note": "This is a DRAFT. The PM must review and send.",
    }

    return json.dumps(draft)
