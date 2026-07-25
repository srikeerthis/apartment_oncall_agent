"""Authorize the property manager's Airtable account and validate the tenant roster.

Residents do not have Airtable accounts -- the property company owns the base, so
exactly one connected account gets authorized here. Per-tenant separation happens
downstream (see config/tenants.yaml).

Run it, open the link if one is printed, complete Airtable OAuth as the property
manager, then run it again. Exits 0 once the account is ACTIVE.

    python connect_tenants.py
"""

import os
import sys

import yaml
from dotenv import load_dotenv

from scalekit_client import actions

load_dotenv()

TENANTS_PATH = os.path.join(os.path.dirname(__file__), "config", "tenants.yaml")


def load_config():
    with open(TENANTS_PATH) as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    pm = cfg["property_manager"]
    identifier = pm["identifier"]
    connection_name = pm.get("connection_name", "airtable")

    resp = actions.get_or_create_connected_account(
        connection_name=connection_name,
        identifier=identifier,
    )
    status = resp.connected_account.status

    print(f"property manager: {identifier}")
    print(f"connection:       {connection_name}")
    print(f"status:           {status}\n")

    if status != "ACTIVE":
        link = actions.get_authorization_link(
            connection_name=connection_name,
            identifier=identifier,
        )
        print(f"  authorize -> {link.link}\n")
        print(
            "Open that link, sign in as the property manager's Airtable account,\n"
            "and grant access to the 'Maintenance Requests' base. Then re-run this."
        )
        return 1

    # Roster sanity check -- these display names must match Airtable cells exactly.
    tenants = cfg["tenants"]
    print(f"Connected. {len(tenants)} tenant(s) in the roster:")
    for tenant_id, t in tenants.items():
        print(f"  {tenant_id:10} {t['display_name']:14} unit {t['unit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
