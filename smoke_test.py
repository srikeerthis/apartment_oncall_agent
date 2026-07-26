"""Prove the two functions work, outside any meeting.

    python smoke_test.py

Step 5 is the one that matters -- it demonstrates the isolation claim rather than
asserting it. Run `python setup_airtable.py --reset` first if a previous run left
extra rows behind.
"""

import sys

from tickets import UnknownTenant, create_ticket, get_status


def show(tickets):
    for t in tickets:
        print(f"       - [{t['status']:11}] {t['issue'][:52]}  ({t['created_at']})")


def main():
    print("[1/5] unit_4b status")
    a_before = get_status("unit_4b")
    print(f"      {len(a_before)} ticket(s)")
    show(a_before)

    print("\n[2/5] unit_2a status")
    b_before = get_status("unit_2a")
    print(f"      {len(b_before)} ticket(s)")
    show(b_before)

    print("\n[3/5] create_ticket for unit_4b")
    issue = "Leak under the kitchen sink, filed under Sam Okafor please"
    created = create_ticket("unit_4b", issue)
    print(f"      {created['record_id']}  {created['status']}")
    print(f"      tenant_name written = {created['tenant_name']!r}  unit = {created['unit']!r}")
    # The issue text names the OTHER tenant on purpose: identity comes from the
    # resolved speaker, never from what was said.
    assert created["tenant_name"] == "Dana Reyes", "identity leaked from issue text!"
    assert created["unit"] == "4B"
    assert created["status"] == "Open"

    print("\n[4/5] unit_4b status again")
    a_after = get_status("unit_4b")
    print(f"      {len(a_after)} ticket(s) (was {len(a_before)})")
    show(a_after)
    assert len(a_after) == len(a_before) + 1

    print("\n[5/5] isolation -- unit_2a must not see any of unit_4b's rows")
    b_after = get_status("unit_2a")
    print(f"      {len(b_after)} ticket(s) (was {len(b_before)})")
    show(b_after)
    assert len(b_after) == len(b_before), "unit_2a's view changed!"
    names = {t["tenant_name"] for t in b_after}
    assert names <= {"Sam Okafor"}, f"cross-tenant leak: {names}"

    print("\n[bonus] unknown speaker must fail loudly")
    try:
        get_status("tenant_zzz")
        print("      FAIL -- unknown tenant did not raise")
        return 1
    except UnknownTenant as e:
        print(f"      raised UnknownTenant: {e}")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
