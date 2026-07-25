"""Build the Tickets table in the Maintenance Requests base and seed demo rows.

Idempotent: re-running leaves an existing table and its rows alone. Use --reset to
wipe all records and re-seed, which is what you want between demo runs.

    python setup_airtable.py
    python setup_airtable.py --reset

Uses AIRTABLE_PAT, which is a SETUP-ONLY credential -- it never enters the agent
runtime. At runtime every Airtable call goes through Scalekit's vaulted OAuth
connection instead.
"""

import argparse
import os
import sys
from datetime import date, timedelta

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

PAT = os.getenv("AIRTABLE_PAT")
# Accept either spelling so a rename in .env cannot silently break setup.
BASE_ID = os.getenv("AIRTABLE_BASE_ID") or os.getenv("AIRTABLE_BASEID")
TABLE_NAME = "Tickets"
TENANTS_PATH = os.path.join(os.path.dirname(__file__), "config", "tenants.yaml")

API = "https://api.airtable.com/v0"
HEADERS = {"Authorization": f"Bearer {PAT}", "Content-Type": "application/json"}

# Field order matters: Airtable makes the FIRST field the primary field, and the
# primary field cannot be a singleSelect or date. Tenant Name leads deliberately.
FIELDS = [
    {"name": "Tenant Name", "type": "singleLineText"},
    {"name": "Unit", "type": "singleLineText"},
    {"name": "Issue", "type": "multilineText"},
    {
        "name": "Status",
        "type": "singleSelect",
        "options": {
            "choices": [
                {"name": "Open"},
                {"name": "In Progress"},
                {"name": "Resolved"},
            ]
        },
    },
    {"name": "Created At", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
]


def load_tenants():
    with open(TENANTS_PATH) as f:
        return yaml.safe_load(f)["tenants"]


def get_table(base_id):
    """Return the Tickets table dict if it already exists, else None."""
    r = requests.get(f"{API}/meta/bases/{base_id}/tables", headers=HEADERS, timeout=30)
    if r.status_code == 403:
        sys.exit(
            "403 listing tables. The PAT needs schema.bases:read + schema.bases:write,\n"
            "and the base must be added under the token's Access section."
        )
    r.raise_for_status()
    for t in r.json()["tables"]:
        if t["name"] == TABLE_NAME:
            return t
    return None


def create_table(base_id):
    r = requests.post(
        f"{API}/meta/bases/{base_id}/tables",
        headers=HEADERS,
        json={"name": TABLE_NAME, "fields": FIELDS},
        timeout=30,
    )
    if not r.ok:
        sys.exit(f"failed to create table: {r.status_code} {r.text}")
    return r.json()


def seed_rows(tenants):
    """Hand-written rows, not generated ones -- during the demo you need to know
    exactly what the agent should say back before it says it."""
    a = tenants["tenant_a"]
    b = tenants["tenant_b"]
    today = date.today()
    return [
        {
            "Tenant Name": a["display_name"],
            "Unit": a["unit"],
            "Issue": "Kitchen faucet drips constantly, worse at night",
            "Status": "In Progress",
            "Created At": str(today - timedelta(days=6)),
        },
        {
            "Tenant Name": a["display_name"],
            "Unit": a["unit"],
            "Issue": "Bedroom window latch is broken",
            "Status": "Resolved",
            "Created At": str(today - timedelta(days=21)),
        },
        {
            "Tenant Name": b["display_name"],
            "Unit": b["unit"],
            "Issue": "Radiator in the living room will not turn on",
            "Status": "Open",
            "Created At": str(today - timedelta(days=2)),
        },
    ]


def list_record_ids(base_id):
    ids, offset = [], None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(
            f"{API}/{base_id}/{TABLE_NAME}", headers=HEADERS, params=params, timeout=30
        )
        r.raise_for_status()
        data = r.json()
        ids += [rec["id"] for rec in data["records"]]
        offset = data.get("offset")
        if not offset:
            return ids


def delete_all(base_id):
    ids = list_record_ids(base_id)
    for i in range(0, len(ids), 10):  # Airtable caps deletes at 10 per request
        requests.delete(
            f"{API}/{base_id}/{TABLE_NAME}",
            headers={"Authorization": f"Bearer {PAT}"},
            params=[("records[]", rid) for rid in ids[i : i + 10]],
            timeout=30,
        ).raise_for_status()
    return len(ids)


def insert(base_id, rows):
    r = requests.post(
        f"{API}/{base_id}/{TABLE_NAME}",
        headers=HEADERS,
        json={"records": [{"fields": row} for row in rows], "typecast": True},
        timeout=30,
    )
    if not r.ok:
        sys.exit(f"failed to insert rows: {r.status_code} {r.text}")
    return r.json()["records"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reset", action="store_true", help="delete all rows and re-seed"
    )
    args = ap.parse_args()

    missing = [
        k
        for k, v in (("AIRTABLE_PAT", PAT), ("AIRTABLE_BASE_ID", BASE_ID))
        if not v
    ]
    if missing:
        sys.exit(f"missing in .env: {', '.join(missing)}")

    tenants = load_tenants()

    table = get_table(BASE_ID)
    if table:
        print(f"table '{TABLE_NAME}' already exists ({table['id']})")
    else:
        table = create_table(BASE_ID)
        print(f"created table '{TABLE_NAME}' ({table['id']})")

    existing = list_record_ids(BASE_ID)
    if existing and not args.reset:
        print(f"{len(existing)} row(s) already present -- leaving them alone.")
        print("Re-run with --reset to wipe and re-seed.")
        return 0

    if existing:
        print(f"deleted {delete_all(BASE_ID)} existing row(s)")

    rows = seed_rows(tenants)
    created = insert(BASE_ID, rows)
    print(f"seeded {len(created)} row(s):")
    for row in rows:
        print(
            f"  {row['Tenant Name']:14} {row['Unit']:4} {row['Status']:12} {row['Issue'][:44]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
