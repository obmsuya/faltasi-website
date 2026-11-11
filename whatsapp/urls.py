from django.urls import path

from . import views
from . import conversation_views


app_name = "whatsapp"


urlpatterns = [
    # Existing Meta webhook
    path(
        "webhook/",
        views.webhook,
        name="webhook",
    ),

    # Conversation management
    path(
        "conversations/",
        conversation_views.conversation_list,
        name="conversation_list",
    ),

    path(
        "conversations/<int:conversation_id>/",
        conversation_views.conversation_detail,
        name="conversation_detail",
    ),

    path(
        "conversations/<int:conversation_id>/send/",
        conversation_views.send_conversation_message,
        name="send_conversation_message",
    ),

    path(
        "conversations/<int:conversation_id>/close/",
        conversation_views.close_conversation,
        name="close_conversation",
    ),
    path(
        "conversations/<int:conversation_id>/take-over/",
        conversation_views.take_over_conversation,
        name="take_over_conversation",
    ),
    path(
        "conversations/<int:conversation_id>/return-to-ai/",
        conversation_views.return_conversation_to_ai,
        name="return_conversation_to_ai",
    ),
]