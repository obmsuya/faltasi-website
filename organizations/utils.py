
from .models import Organization, OrganizationMember


def is_platform_administrator(user):
    """
    Check whether a user is authorized to administer the platform.
    """

    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return OrganizationMember.objects.filter(
        user=user,
        is_active=True,
        organization__organization_type="platform_owner",
        organization__status="active",
        role__in=["owner", "admin"],
    ).exists()


def get_user_organization(user, request=None):
    """
    Resolve the organization for the current user.

    Platform administrators:
        Use the organization selected in the session.
        Otherwise, default to the active platform-owner organization.

    Normal users:
        Use their first active organization membership.
    """

    if not user.is_authenticated:
        return None

    if is_platform_administrator(user):

        if request is not None:
            organization_id = request.session.get(
                "active_organization_id"
            )

            if organization_id:
                organization = Organization.objects.filter(
                    id=organization_id,
                    status="active",
                ).first()

                if organization:
                    return organization

                request.session.pop(
                    "active_organization_id",
                    None,
                )

        return Organization.objects.filter(
            organization_type="platform_owner",
            status="active",
        ).order_by("id").first()
    if request is not None:
        organization_id = request.session.get(
            "active_organization_id"
        )

        if organization_id:
            membership = OrganizationMember.objects.filter(
                user=user,
                organization_id=organization_id,
                is_active=True,
                organization__status="active",
            ).select_related("organization").first()

            if membership:
                return membership.organization
            request.session.pop(
                "active_organization_id",
                None,
            )

    membership = (
        OrganizationMember.objects
        .filter(
            user=user,
            is_active=True,
            organization__status="active",
        )
        .select_related("organization")
        .first()
    )

    return membership.organization if membership else None
