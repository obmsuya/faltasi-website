
import os
import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "faltasi_website.settings",
)
django.setup()

from django.apps import apps
from django.db.models import ForeignKey, OneToOneField, ManyToManyField

target_names = {
    "Customer",
    "BusinessRequest",
    "Department",
    "DepartmentMember",
    "RequestCategory",
    "RequestField",
    "RequestAssignment",
    "RequestApproval",
    "WorkflowStep",
    "RequestNotification",
    "StaffContact",
    "Conversation",
    "ConversationState",
    "Message",
}

print("MODELS THAT REFERENCE RECORDS PLANNED FOR DELETION")
print("=" * 55)

for model in apps.get_models():
    for field in model._meta.get_fields():
        if isinstance(field, (ForeignKey, OneToOneField, ManyToManyField)):
            related_model = getattr(field, "related_model", None)

            if related_model and related_model.__name__ in target_names:
                print(
                    f"{model._meta.label}.{field.name}"
                    f" -> {related_model._meta.label}"
                )

