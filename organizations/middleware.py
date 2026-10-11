class RequireOwnerPasswordChangeMiddleware:
    """Force provisioned organization owners to change their temporary password."""

    EXEMPT_PREFIXES = (
        "/accounts/force-password-change/",
        "/accounts/logout/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_superuser:
            if not request.path.startswith(self.EXEMPT_PREFIXES):
                # Import lazily to avoid loading models before Django is ready.
                from .models import OrganizationMember
                must_change = OrganizationMember.objects.filter(
                    user=user, is_active=True, must_change_password=True
                ).exists()
                if must_change:
                    from django.shortcuts import redirect
                    return redirect("accounts:force_password_change")
        return self.get_response(request)
