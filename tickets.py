"""The bridge server's entire interface to Airtable.

    from tickets import get_status, create_ticket

    get_status("tenant_a")                       -> [{issue, status, created_at, unit}, ...]
    create_ticket("tenant_b", "leak under sink") -> {issue, status, created_at, unit, record_id}

Nothing above the line needs to know Scalekit exists.

HOW SCOPING WORKS
Residents do not own Airtable accounts, so there is one connected account (the
property company). Per-tenant separation comes from three places:

  1. Tenant Name is written from the resolved identity in config/tenants.yaml,
     never from the transcript. `issue` is the ONLY caller-supplied value that
     reaches Airtable, so "file this under Dana" in a recording changes nothing.
  2. Every read carries filterByFormula built here, at one choke point.
  3. The Virtual MCP Server exposes 2 of Airtable's 48 tools. That one is
     enforced by Scalekit, outside this process.

Airtable itself has no row-level permissions -- any credential that can read the
base can read every row. Do not claim otherwise.
"""

import asyncio
import json
import os
from datetime import date, timedelta

import yaml
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import scalekit_client as sk

load_dotenv()

BASE_ID = os.getenv("AIRTABLE_BASE_ID")
MCP_CONFIG_ID = os.getenv("SCALEKIT_MCP_CONFIG_ID")
# "mcp" (default) routes through the Virtual MCP Server. "direct" bypasses it via
# actions.execute_tool -- same arguments, same return shape, kept as an escape
# hatch if the MCP transport misbehaves mid-demo.
TOOL_PATH = os.getenv("SCALEKIT_TOOL_PATH", "mcp")
TABLE = "Tickets"
TOKEN_TTL = timedelta(minutes=5)

TENANTS_PATH = os.path.join(os.path.dirname(__file__), "config", "tenants.yaml")


class TicketsError(Exception):
    """Base class. Every message here is safe to speak aloud in the call."""


class UnknownTenant(TicketsError):
    pass


class ToolCallFailed(TicketsError):
    pass


def _config():
    with open(TENANTS_PATH) as f:
        return yaml.safe_load(f)


def _resolve(tenant_id):
    """tenant_id -> (display_name, unit). Never falls back to a default: an
    unrecognized speaker must fail loudly, not get filed as someone else."""
    tenants = _config()["tenants"]
    if tenant_id not in tenants:
        raise UnknownTenant(
            f"I don't recognize {tenant_id} as a resident on this account."
        )
    t = tenants[tenant_id]
    return t["display_name"], t["unit"]


def _identifier():
    return _config()["property_manager"]["identifier"]


def _escape(value):
    """Airtable formulas use single quotes; a name containing one would break the
    filter. Not a security boundary -- display names come from our own config --
    but a correctness one."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


def _mint_token(identifier):
    """Short-lived token scoped to this identifier, minted per call. The vMCP
    server URL is the token's own `aud` claim, so it is never hardcoded."""
    resp = sk.get_client().actions.mcp.create_session_token(
        mcp_config_id=MCP_CONFIG_ID, identifier=identifier, expiry=TOKEN_TTL
    )
    payload = resp.token.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # JWT strips base64 padding
    import base64

    claims = json.loads(base64.urlsafe_b64decode(payload))
    return resp.token, claims["aud"][0]


async def _call_via_mcp(identifier, tool_name, params):
    token, url = _mint_token(identifier)
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, params)
            if result.isError:
                raise ToolCallFailed(f"{tool_name} failed: {result.content}")
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    payload = json.loads(text)
                    # The vMCP wraps results as {"data": {...}, "executionId": ...}
                    # while execute_tool returns the inner object directly. Both
                    # paths must hand back the same shape.
                    return payload.get("data", payload)
            raise ToolCallFailed(f"{tool_name} returned no content")


def _call_via_direct(identifier, tool_name, params):
    resp = sk.actions.execute_tool(
        tool_name=tool_name, identifier=identifier, tool_input=params
    )
    return resp.data


def _call_tool(tool_name, params):
    identifier = _identifier()
    params = {"base_id": BASE_ID, "table_id_or_name": TABLE, **params}
    try:
        if TOOL_PATH == "direct":
            return _call_via_direct(identifier, tool_name, params)
        return asyncio.run(_call_via_mcp(identifier, tool_name, params))
    except TicketsError:
        raise
    except BaseExceptionGroup as eg:
        # anyio's TaskGroup wraps our ToolCallFailed; surface the real message
        # rather than a generic one, or every schema mistake looks like an outage.
        for exc in eg.exceptions:
            if isinstance(exc, TicketsError):
                raise exc from eg
        raise ToolCallFailed(
            f"Airtable is not responding right now ({type(eg).__name__})."
        ) from eg
    except Exception as e:
        raise ToolCallFailed(
            f"Airtable is not responding right now ({type(e).__name__})."
        ) from e


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def _to_ticket(record):
    f = record.get("fields", {})
    return {
        "record_id": record.get("id"),
        "issue": f.get("Issue", ""),
        "status": f.get("Status", ""),
        "created_at": f.get("Created At", ""),
        "unit": f.get("Unit", ""),
        "tenant_name": f.get("Tenant Name", ""),
    }


def get_status(tenant_id):
    """Return this tenant's tickets, newest first. Empty list if they have none."""
    display_name, _ = _resolve(tenant_id)
    data = _call_tool(
        "airtable_list_records",
        {
            "filterByFormula": f"{{Tenant Name}}='{_escape(display_name)}'",
            "maxRecords": 50,
        },
    )
    tickets = [_to_ticket(r) for r in data.get("records", [])]
    # This tool's schema has no `sort` parameter, so order it here. Newest first
    # matters: the agent reads out the most recent ticket when asked "my ticket".
    tickets.sort(key=lambda t: t["created_at"], reverse=True)
    return tickets


def create_ticket(tenant_id, issue):
    """File a new Open ticket as this tenant. `issue` is the only caller-supplied
    value that reaches Airtable -- name and unit come from resolved identity."""
    display_name, unit = _resolve(tenant_id)
    if not issue or not issue.strip():
        raise TicketsError("I didn't catch what the issue was.")

    data = _call_tool(
        "airtable_create_records",
        {
            "records": [
                {
                    "fields": {
                        "Tenant Name": display_name,
                        "Unit": unit,
                        "Issue": issue.strip(),
                        "Status": "Open",
                        "Created At": str(date.today()),
                    }
                }
            ],
            "typecast": True,
        },
    )
    records = data.get("records", [])
    if not records:
        raise ToolCallFailed("The ticket did not come back from Airtable.")
    return _to_ticket(records[0])
