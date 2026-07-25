import os

import scalekit.client
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict
from scalekit.v1.tools.tools_pb2 import Filter

load_dotenv()

_REQUIRED = ("SCALEKIT_CLIENT_ID", "SCALEKIT_CLIENT_SECRET", "SCALEKIT_ENVIRONMENT_URL")

_client = None


def get_client():
    """Build the Scalekit client on first use.

    Constructing ScalekitClient authenticates immediately, so doing it at import
    time would mean no module that imports this one could be unit-tested offline.
    Deferred here instead; importers should reach for `scalekit_client.actions`
    at call time rather than binding the name at import.
    """
    global _client
    if _client is None:
        # The SDK does not validate these, so a missing env var surfaces five
        # frames deep as `NoneType + str` in core.py. Fail here, naming it.
        missing = [k for k in _REQUIRED if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"missing in .env: {', '.join(missing)}")
        _client = scalekit.client.ScalekitClient(
            client_id=os.getenv("SCALEKIT_CLIENT_ID"),
            client_secret=os.getenv("SCALEKIT_CLIENT_SECRET"),
            env_url=os.getenv("SCALEKIT_ENVIRONMENT_URL"),
        )
    return _client


def __getattr__(name):
    """Keep `from scalekit_client import actions` working, lazily (PEP 562)."""
    if name == "scalekit_client":
        return get_client()
    if name == "actions":
        return get_client().actions
    raise AttributeError(name)


def list_airtable_tools(name_filter=None):
    """Return {tool_name: tool_id} for the AIRTABLE provider.

    Quirks worth remembering: list_tools lives on client.tools (not actions), it
    returns a (response, headers) tuple, and each tool's definition is a protobuf
    Struct rather than a message with a .name field. Filter(connector="airtable")
    looks right but 400s until a connected account exists -- query= works cold.
    """
    resp, _ = get_client().tools.list_tools(
        filter=Filter(query="airtable"), page_size=200
    )
    out = {}
    for t in resp.tools:
        name = MessageToDict(t.definition).get("name", "")
        if name and (name_filter is None or name in name_filter):
            out[name] = t.id
    return out


if __name__ == "__main__":
    needed = ("airtable_list_records", "airtable_create_records")
    found = list_airtable_tools(name_filter=needed)
    for name in needed:
        print(f"  {name:26} {found.get(name, 'MISSING')}")