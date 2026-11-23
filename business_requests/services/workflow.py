"""Business Request assignment and workflow services."""

from django.core.mail import send_mail
from django.utils import timezone

from business_requests.models import (
    DepartmentMember,
    RequestAssignment,
    WhatsAppAutomationSettings,
    WorkflowStep,
)


def _organization_settings(organization):
    if not organization:
        return None
    return WhatsAppAutomationSettings.objects.filter(
        organization=organization,
        is_active=True,
    ).first()


def create_request_workflow(business_request):
    """Assign the request fairly and create its configured initial step."""
    if not business_request or not business_request.department:
        return None

    department = business_request.department
    organization = department.organization
    if business_request.customer.organization_id != organization.pk:
        return None
    if business_request.category_id and business_request.category.organization_id != organization.pk:
        return None

    config = _organization_settings(organization)
    if not config or not config.workflow_review_step_name:
        return None

    assignment = RequestAssignment.objects.filter(
        request=business_request,
        is_current=True,
    ).select_related("assigned_to", "department").first()
    created_assignment = False

    if assignment is None:
        members = DepartmentMember.objects.filter(
            department=department,
            is_active=True,
            user__is_active=True,
            user__organization_memberships__organization=organization,
            user__organization_memberships__is_active=True,
        ).select_related("user").distinct()

        selected_member = None
        selected_load = None
        for member in members:
            load = RequestAssignment.objects.filter(
                assigned_to=member.user,
                is_current=True,
                request__status__in=("new", "in_progress"),
            ).count()
            if selected_member is None or load < selected_load:
                selected_member = member
                selected_load = load

        assigned_user = selected_member.user if selected_member else None
        notes = config.assignment_notes if assigned_user else config.unassigned_notes
        assignment = RequestAssignment.objects.create(
            request=business_request,
            department=department,
            assigned_to=assigned_user,
            is_current=True,
            assigned_at=timezone.now(),
            notes=notes,
        )
        created_assignment = bool(assigned_user)
    else:
        assigned_user = assignment.assigned_to

    step = WorkflowStep.objects.filter(
        request=business_request,
        name=config.workflow_review_step_name,
    ).first()
    if step is None:
        WorkflowStep.objects.create(
            request=business_request,
            name=config.workflow_review_step_name,
            description=config.workflow_review_step_description,
            step_order=config.workflow_review_step_order,
            status="active",
            assigned_to=assigned_user,
        )
    elif step.assigned_to_id != getattr(assigned_user, "pk", None):
        step.assigned_to = assigned_user
        step.save(update_fields=["assigned_to"])

    if assigned_user and business_request.status != "in_progress":
        business_request.status = "in_progress"
        business_request.save(update_fields=["status", "updated_at"])

    if created_assignment and assigned_user:
        notify_assigned_staff(business_request, assignment, config=config)

    return assignment


def notify_assigned_staff(business_request, assignment, *, config=None):
    """Send a configured assignment email; no template is embedded in code."""
    if not assignment or not assignment.assigned_to or not assignment.assigned_to.email:
        return False

    config = config or _organization_settings(
        business_request.department.organization if business_request.department_id else None
    )
    if not config or not config.assignment_email_subject_template or not config.assignment_email_body_template:
        return False

    customer = business_request.customer
    department = business_request.department
    context = {
        "staff_name": assignment.assigned_to.get_full_name() or assignment.assigned_to.username,
        "request_id": business_request.pk,
        "subject": business_request.subject or config.assignment_email_missing_value,
        "department": department.name if department else config.assignment_email_missing_value,
        "customer_name": customer.name if customer else config.assignment_email_missing_value,
        "customer_phone": customer.phone if customer else config.assignment_email_missing_value,
        "request_text": business_request.request_text,
        "priority": business_request.priority,
        "status": business_request.status,
        "organization_name": business_request.department.organization.name if business_request.department_id else "",
    }
    try:
        subject = config.assignment_email_subject_template.format_map(context)
        message = config.assignment_email_body_template.format_map(context)
        send_mail(subject, message, from_email=None, recipient_list=[assignment.assigned_to.email], fail_silently=False)
        return True
    except Exception:
        return False


def create_manual_assignment_workflow_step(business_request, assigned_user):
    """Update or create the configured workflow step for a manual assignment."""
    if not business_request or not business_request.department_id:
        return None
    organization = business_request.department.organization
    if business_request.customer.organization_id != organization.pk:
        return None
    config = _organization_settings(organization)
    if not config or not config.workflow_review_step_name:
        return None
    step = WorkflowStep.objects.filter(
        request=business_request,
        status="active",
    ).order_by("step_order", "pk").first()
    if step:
        step.assigned_to = assigned_user
        step.save(update_fields=["assigned_to"])
        return step
    return WorkflowStep.objects.create(
        request=business_request,
        name=config.workflow_review_step_name,
        description=config.workflow_review_step_description,
        step_order=config.workflow_review_step_order,
        status="active",
        assigned_to=assigned_user,
    )


def format_assignment_whatsapp_message(business_request, assigned_user):
    """Render the configured staff assignment message for WhatsApp."""
    if not business_request or not assigned_user:
        return None
    organization = business_request.customer.organization
    if business_request.department_id and business_request.department.organization_id != organization.pk:
        return None
    config = _organization_settings(organization)
    if not config or not config.assignment_whatsapp_message_template:
        return None
    missing = config.assignment_email_missing_value
    customer = business_request.customer
    department = business_request.department
    context = {
        "staff_name": assigned_user.get_full_name() or assigned_user.username,
        "request_id": business_request.pk,
        "subject": business_request.subject or missing,
        "department": department.name if department else missing,
        "customer_name": customer.name if customer else missing,
        "customer_phone": customer.phone if customer else missing,
        "organization_name": organization.name,
        "request_text": business_request.request_text,
    }
    try:
        return config.assignment_whatsapp_message_template.format_map(context)
    except (KeyError, ValueError, TypeError):
        return None


def create_manual_request_assignment(business_request, assigned_user, assigned_by):
    """Create a new current assignment using configured audit-note text."""
    if not business_request or not assigned_user or not business_request.department_id:
        return None
    organization = business_request.department.organization
    if business_request.customer.organization_id != organization.pk:
        return None
    config = _organization_settings(organization)
    if not config:
        return None
    if not DepartmentMember.objects.filter(
        department=business_request.department,
        user=assigned_user,
        is_active=True,
        user__is_active=True,
        user__organization_memberships__organization=organization,
        user__organization_memberships__is_active=True,
    ).exists():
        return None

    RequestAssignment.objects.filter(
        request=business_request,
        is_current=True,
    ).update(is_current=False)

    missing = config.assignment_email_missing_value
    notes = ""
    if config.manual_assignment_notes_template:
        context = {
            "assigned_to": assigned_user.get_full_name() or assigned_user.username,
            "assigned_by": (
                assigned_by.get_full_name() or assigned_by.username
                if assigned_by else missing
            ),
            "request_id": business_request.pk,
        }
        try:
            notes = config.manual_assignment_notes_template.format_map(context)
        except (KeyError, ValueError, TypeError):
            notes = ""

    assignment = RequestAssignment.objects.create(
        request=business_request,
        assigned_to=assigned_user,
        department=business_request.department,
        is_current=True,
        notes=notes,
    )
    create_manual_assignment_workflow_step(business_request, assigned_user)
    return assignment
