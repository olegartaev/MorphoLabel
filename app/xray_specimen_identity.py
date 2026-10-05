"""User-assigned specimen codes are independent of internal ordering and UUIDs."""


def specimen_display_id(item):
    if not item:return "—"
    return str(item.get("specimen_code") or "").strip() or str(int(item.get("ordinal") or 0))


def next_specimen_ordinal(items):
    items=list(items)
    ordinal=1+max((int(item.get("ordinal") or 0) for item in items),default=0)
    used={specimen_display_id(item) for item in items}
    while str(ordinal) in used:ordinal+=1
    return ordinal


def validate_specimen_code(value):
    code=str(value).strip()
    if not code:raise ValueError("Enter a specimen ID, for example A12 or 12-B.")
    if len(code)>128:raise ValueError("Use at most 128 characters for the specimen ID.")
    if any(ord(char)<32 or ord(char)==127 for char in code):
        raise ValueError("Use a single line for the specimen ID.")
    return code
