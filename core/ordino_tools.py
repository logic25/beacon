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


def _proxy_call(action: str, params: dict = None) -> dict:
    """Call the beacon-data-proxy edge function on Ordino's Supabase."""
    if not SUPABASE_URL or not BEACON_ANALYTICS_KEY:
        logger.warning("Ordino proxy not configured (SUPABASE_URL or BEACON_ANALYTICS_KEY missing)")
        return {"error": "Ordino connection not configured"}

    url = f"{SUPABASE_URL}/functions/v1/beacon-data-proxy"

    try:
        resp = httpx.post(
            url,
            json={"action": action, "params": params or {}},
            headers={
                "Content-Type": "application/json",
                "x-beacon-key": BEACON_ANALYTICS_KEY,
            },
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
        "description": "General-purpose query tool for ANY data in Ordino. Use this when the specific tools (query_projects, query_invoices, etc.) don't cover what you need. You can query any table: companies, profiles, properties, projects, proposals, invoices, services, activities, client_contacts, project_contacts, rfi_requests, calendar_events, billing_schedules, change_orders, documents, email threads, and more. Always filter by the user's company to avoid accessing other companies' data.",
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
]


# ═══════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        # Most tools go directly through the proxy
        proxy_actions = [
            "query_projects", "query_project_detail", "query_property_violations",
            "query_pm_workload", "check_filing_readiness", "query_proposals",
            "query_invoices",
        ]

        if tool_name in proxy_actions:
            result = _proxy_call(tool_name, tool_input)
            return json.dumps(result)
        elif tool_name == "query_ordino":
            result = _proxy_call("query_ordino", tool_input)
            return json.dumps(result)
        elif tool_name == "draft_follow_up_email":
            return _draft_follow_up_email(tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return json.dumps({"error": str(e)})


def _draft_follow_up_email(params: dict) -> str:
    """Draft a follow-up email (does not send)."""
    project_id = params.get("project_id")
    recipient = params.get("recipient", "client")
    missing = params.get("missing_items", "required information")

    if not project_id:
        return json.dumps({"error": "project_id is required"})

    # Get project detail from proxy
    detail = _proxy_call("query_project_detail", {"project_id": project_id})

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
