"""Create the Virtual MCP Server that the agent is allowed to see.

This is the structural half of the authorization story: of Airtable's 48 tools,
the agent's world contains exactly two. No delete, no update, no schema access,
no other bases. That boundary is enforced by Scalekit, outside our code, so no
prompt or transcript can talk its way past it.

Idempotent -- finds an existing config by name rather than creating duplicates.

    python setup_vmcp.py
"""

import os
import sys

import yaml
from dotenv import load_dotenv
from scalekit.actions.models.mcp_config import McpConfigConnectionToolMapping

from scalekit_client import scalekit_client

load_dotenv()

CONFIG_NAME = "property-call-agent"
ALLOWED_TOOLS = ["airtable_list_records", "airtable_create_records"]
TENANTS_PATH = os.path.join(os.path.dirname(__file__), "config", "tenants.yaml")

mcp = scalekit_client.actions.mcp


def load_connection_name():
    with open(TENANTS_PATH) as f:
        return yaml.safe_load(f)["property_manager"].get("connection_name", "airtable")


def find_existing(name):
    # list_configs caps page_size at 30 (list_tools allows 200 -- different limits).
    resp = mcp.list_configs(page_size=30)
    configs = getattr(resp, "configs", None) or getattr(resp, "mcp_configs", []) or []
    for c in configs:
        if getattr(c, "name", None) == name:
            return c
    return None


def main():
    connection_name = load_connection_name()

    existing = find_existing(CONFIG_NAME)
    if existing:
        cfg_id = getattr(existing, "id", None) or getattr(existing, "config_id", None)
        print(f"config '{CONFIG_NAME}' already exists: {cfg_id}")
    else:
        resp = mcp.create_config(
            name=CONFIG_NAME,
            description="Live-call maintenance agent: read ticket status, file new tickets.",
            connection_tool_mappings=[
                McpConfigConnectionToolMapping(
                    connection_name=connection_name,
                    tools=ALLOWED_TOOLS,
                )
            ],
        )
        cfg = getattr(resp, "config", None) or getattr(resp, "mcp_config", resp)
        cfg_id = getattr(cfg, "id", None) or getattr(cfg, "config_id", None)
        print(f"created config '{CONFIG_NAME}': {cfg_id}")
        print(f"  tools exposed: {', '.join(ALLOWED_TOOLS)}")

    print(f"\nAdd to .env:\n  SCALEKIT_MCP_CONFIG_ID={cfg_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
