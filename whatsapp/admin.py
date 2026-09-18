from django.contrib import admin

from .models import (
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    WhatsAppConnection,
    Conversation,
    ConversationState,
    Message,
)


@admin.register(WhatsAppBusinessAccount)
class WhatsAppBusinessAccountAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "business_name",
        "waba_id",
        "status",
        "is_active",
        "created_at",
    )

    list_filter = (
        "status",
        "is_active",
        "created_at",
    )

    search_fields = (
        "organization__name",
        "business_name",
        "waba_id",
        "business_manager_id",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "organization__name",
        "business_name",
    )


@admin.register(WhatsAppPhoneNumber)
class WhatsAppPhoneNumberAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "whatsapp_business_account",
        "phone_number",
        "display_name",
        "verified_name",
        "status",
        "quality_rating",
        "is_default",
        "is_active",
    )

    list_filter = (
        "status",
        "is_active",
        "is_default",
        "quality_rating",
    )

    search_fields = (
        "organization__name",
        "phone_number",
        "phone_number_id",
        "display_name",
        "verified_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "organization__name",
        "phone_number",
    )


@admin.register(WhatsAppConnection)
class WhatsAppConnectionAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "whatsapp_business_account",
        "status",
        "last_connected_at",
        "created_at",
    )

    list_filter = (
        "status",
        "created_at",
        "last_connected_at",
    )

    search_fields = (
        "organization__name",
        "whatsapp_business_account__business_name",
        "whatsapp_business_account__waba_id",
    )

    readonly_fields = (
        "last_connected_at",
        "created_at",
        "updated_at",
    )

    exclude = (
        "access_token",
    )

    ordering = (
        "organization__name",
    )


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "whatsapp_phone_number",
        "customer",
        "phone_number",
        "status",
        "started_at",
        "last_message_at",
        "closed_at",
    )

    list_filter = (
        "status",
        "started_at",
        "last_message_at",
        "closed_at",
    )

    search_fields = (
        "organization__name",
        "customer__name",
        "customer__phone",
        "phone_number",
        "whatsapp_user_id",
    )

    readonly_fields = (
        "started_at",
        "last_message_at",
    )

    ordering = (
        "-last_message_at",
    )


@admin.register(ConversationState)
class ConversationStateAdmin(admin.ModelAdmin):

    list_display = (
        "conversation",
        "current_step",
        "waiting_for",
        "updated_at",
    )

    list_filter = (
        "current_step",
        "waiting_for",
        "updated_at",
    )

    search_fields = (
        "conversation__phone_number",
        "conversation__customer__name",
        "current_step",
        "waiting_for",
    )

    readonly_fields = (
        "updated_at",
    )

    ordering = (
        "-updated_at",
    )


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):

    list_display = (
        "organization",
        "conversation",
        "direction",
        "sender_type",
        "message_type",
        "delivery_status",
        "whatsapp_message_id",
        "created_at",
    )

    list_filter = (
        "direction",
        "sender_type",
        "message_type",
        "delivery_status",
        "created_at",
    )

    search_fields = (
        "organization__name",
        "conversation__phone_number",
        "conversation__customer__name",
        "content",
        "whatsapp_message_id",
    )

    readonly_fields = (
        "created_at",
    )

    ordering = (
        "-created_at",
    )