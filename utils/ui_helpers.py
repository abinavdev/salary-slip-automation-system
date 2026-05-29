"""UI helpers for templates (flash filtering, etc.)."""

# Flashes matching these are expected empty-state copy — show inline on pages, not as toasts.
_EMPTY_STATE_FLASH_MARKERS = (
    "no employees found",
    "no salary records found",
    "no email logs found",
    "no upload history found",
    "no uploads yet",
    "no salary data available",
)


def is_action_flash(message: str) -> bool:
    """Return True if a flash message should appear in the toast stack."""
    if not message:
        return False
    lower = message.strip().lower()
    return not any(marker in lower for marker in _EMPTY_STATE_FLASH_MARKERS)
