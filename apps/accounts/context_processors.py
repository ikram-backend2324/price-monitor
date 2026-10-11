def organization(request):
    membership = getattr(request, "membership", None)
    user = getattr(request, "user", None)
    memberships = []
    if user is not None and user.is_authenticated:
        memberships = list(user.memberships.select_related("organization"))
    return {
        "current_org": getattr(request, "organization", None),
        "current_membership": membership,
        "all_memberships": memberships,
        "can_edit": bool(membership and membership.can_edit),
    }
