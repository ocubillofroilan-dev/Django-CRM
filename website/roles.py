"""Role definitions. Roles are plain Django groups, so admins can manage them in /admin/."""

AGENT_GROUP = "Agent"      # default for self-registered users: sees only their own customers
MANAGER_GROUP = "Manager"  # sees and manages every customer


def ensure_roles():
    """Create the Agent / Manager groups and attach the manager permission. Idempotent."""
    from django.contrib.auth.models import Group, Permission

    agent, _ = Group.objects.get_or_create(name=AGENT_GROUP)
    manager, _ = Group.objects.get_or_create(name=MANAGER_GROUP)
    permission = Permission.objects.filter(
        content_type__app_label="website", codename="manage_all_records"
    ).first()
    if permission is None:
        raise RuntimeError("Permission not found. Run `python manage.py migrate` first.")
    manager.permissions.add(permission)
    return agent, manager