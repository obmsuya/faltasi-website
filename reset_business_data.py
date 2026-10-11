
import os
import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "faltasi_website.settings",
)
django.setup()

from django.db import transaction
from django.contrib.auth import get_user_model

from customers.models import Customer

from business_requests.models import (
    BusinessRequest,
    RequestAssignment,
    RequestApproval,
    WorkflowStep,
    RequestNotification,
    StaffContact,
    DepartmentMember,
    Department,
    RequestCategory,
    RequestField,
)

from whatsapp.models import (
    Message,
    ConversationState,
    Conversation,
)

from organizations.models import (
    Organization,
    OrganizationMember,
    Country,
)


def count_records():
    User = get_user_model()

    print("Users:", User.objects.count())
    print("Organizations:", Organization.objects.count())
    print("Organization memberships:", OrganizationMember.objects.count())
    print("Countries:", Country.objects.count())
    print("Customers:", Customer.objects.count())
    print("Business requests:", BusinessRequest.objects.count())
    print("Departments:", Department.objects.count())
    print("Request categories:", RequestCategory.objects.count())
    print("Request fields:", RequestField.objects.count())
    print("Conversations:", Conversation.objects.count())
    print("Conversation states:", ConversationState.objects.count())
    print("Messages:", Message.objects.count())


def reset_business_data():
    User = get_user_model()

    # Safety check: preserve the expected administrator account.
    if not User.objects.filter(username="obmsuya").exists():
        raise RuntimeError(
            "Reset stopped: user 'obmsuya' was not found."
        )

    # Safety check: preserve the expected active organization.
    if not Organization.objects.filter(
        id=6,
        name="Faltasi Innovations Limited",
        organization_type="platform_owner",
        status="active",
    ).exists():
        raise RuntimeError(
            "Reset stopped: the expected Faltasi organization "
            "was not found."
        )

    # Delete related business data in one transaction.
    with transaction.atomic():
        Message.objects.all().delete()
        ConversationState.objects.all().delete()
        Conversation.objects.all().delete()

        RequestNotification.objects.all().delete()
        RequestApproval.objects.all().delete()
        RequestAssignment.objects.all().delete()
        WorkflowStep.objects.all().delete()
        StaffContact.objects.all().delete()
        BusinessRequest.objects.all().delete()

        DepartmentMember.objects.all().delete()
        RequestField.objects.all().delete()
        RequestCategory.objects.all().delete()
        Department.objects.all().delete()

        Customer.objects.all().delete()

    # Verify the essential records still exist.
    if not User.objects.filter(username="obmsuya").exists():
        raise RuntimeError(
            "Verification failed: administrator account missing."
        )

    if not Organization.objects.filter(
        id=6,
        name="Faltasi Innovations Limited",
    ).exists():
        raise RuntimeError(
            "Verification failed: Faltasi organization missing."
        )

    print("\nRESET COMPLETED SUCCESSFULLY")
    print("\nRECORD COUNTS AFTER RESET")
    count_records()


if __name__ == "__main__":
    print("CURRENT DATABASE COUNTS")
    count_records()

    print(
        "\nWARNING: This permanently deletes the selected "
        "business data and WhatsApp conversation history."
    )
    print(
        "User accounts, organizations, organization memberships, "
        "countries, and products are intended to be preserved."
    )

    confirmation = input(
        "\nType RESET BUSINESS DATA to continue: "
    )

    if confirmation != "RESET BUSINESS DATA":
        print("\nCancelled. No records were intentionally deleted.")
    else:
        reset_business_data()
