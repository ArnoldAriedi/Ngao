def transition_allowed(role: str, current: str, target: str, restoring_own_suspension: bool) -> bool:
    """Admins may do anything. Reviewers may suspend, or undo a suspension their own report caused."""
    if role == "ADMIN" or current == target:
        return True
    if (current, target) == ("APPROVED", "SUSPENDED"):
        return True
    return (current, target) == ("SUSPENDED", "APPROVED") and restoring_own_suspension
