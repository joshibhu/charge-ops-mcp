"""Turn personal data into something useful but not identifying.

Pure functions — no I/O, no database, no model. They are applied at the
tool boundary (piece 2), which is the only place that covers every tool
including ones written later.

The goal is NOT total redaction. '***' everywhere destroys the data: you
could no longer tell two sessions apart, or spot one driver with forty
failed payments. Keep the shape, lose the identity.
"""

from collections.abc import Callable


def mask_name(value: str) -> str:
    """'Divya Kulkarni' -> 'D*** K***'. Initials survive; the name does not."""
    if "*" in value:
        return value   # already masked — see db.py
    parts = [p for p in value.split() if p]
    return " ".join(f"{p[0]}***" for p in parts) if parts else "***"


def mask_phone(value: str) -> str:
    """'+919572623548' -> '+91*****3548'. Last 4 match a support ticket."""
    if "*" in value:
        return value   # already masked — see db.py
    digits = [c for c in value if c.isdigit()]
    if len(digits) < 4:
        return "***"
    prefix = "+91" if value.startswith("+91") else ""
    hidden = "*" * max(1, len(digits) - (3 if prefix else 0) - 4)
    return f"{prefix}{hidden}{''.join(digits[-4:])}"


def mask_email(value: str) -> str:
    """'divya.kulkarni15@example.com' -> 'd***@example.com'.

    The DOMAIN is kept deliberately: it distinguishes a corporate account
    from a personal one, which is operationally useful and not identifying.
    """
    if "*" in value:
        return value   # already masked — see db.py
    if "@" not in value:
        return "***"
    local, _, domain = value.partition("@")
    first = local[0] if local else "*"
    return f"{first}***@{domain}"


def mask_vehicle_reg(value: str) -> str:
    """'GJ01CC1814' -> 'GJ01****1814'. State and district code survive."""
    if "*" in value:
        return value   # already masked — see db.py
    cleaned = value.replace(" ", "")
    if len(cleaned) <= 8:
        return f"{cleaned[:2]}***{cleaned[-2:]}" if len(cleaned) > 4 else "***"
    return f"{cleaned[:4]}****{cleaned[-4:]}"


# Which columns are personal, and how each is masked.
#
# THIS DICT IS THE THING TO MAINTAIN. Adding a personal column to the
# database without adding it here is the failure mode — so a test asserts
# that every column whose name looks personal appears in this map.
PERSONAL_FIELDS: dict[str, Callable[[str], str]] = {
    "driver_name": mask_name,
    "driver_phone": mask_phone,
    "driver_email": mask_email,
    "vehicle_reg": mask_vehicle_reg,
}


def mask_value(field: str, value: object) -> object:
    """Mask one value if its column is personal. Leaves everything else alone."""
    if value is None:
        return None
    masker = PERSONAL_FIELDS.get(field.lower())
    return masker(str(value)) if masker else value
