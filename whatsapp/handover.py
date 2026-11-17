
from django.db import transaction
from django.utils import timezone

from .tasks import (
    send_handover_reminder,
    return_handover_to_ai,
)


def activate_human_handover(conversation):
    """
    Activate human handling and schedule its timeout tasks.
    """
    handover_at = timezone.now()

    conversation.handling_mode = "human"
    conversation.handover_at = handover_at

    conversation.save(
        update_fields=[
            "handling_mode",
            "handover_at",
        ]
    )

    conversation_id = conversation.id
    handover_timestamp = handover_at.isoformat()

    def schedule_tasks():
        send_handover_reminder.apply_async(
            args=[conversation_id, handover_timestamp],
            countdown=900,
        )

        return_handover_to_ai.apply_async(
            args=[conversation_id, handover_timestamp],
            countdown=1800,
        )

    transaction.on_commit(schedule_tasks)

    return conversation
