"""The firm's switch for document requests (owner ruling 2026-11-17: "for now, deactivate the
document request thing"). One system parameter, off unless it reads as on. While it is off every
entry point is hidden, the client portal pages are closed and a new request is refused; the
requests already made stay in the database untouched. Turning it on brings everything back."""

PARAM = "ea_audit_portal.document_requests"
ON_VALUES = ("1", "true", "yes", "on")


def reads_as_on(value):
    """The stored text of the parameter: only an explicit yes turns the requests on."""
    return str(value or "").strip().lower() in ON_VALUES
