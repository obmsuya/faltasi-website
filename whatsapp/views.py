"""WhatsApp Cloud API views and conversation orchestration.

Django owns tenant routing, consent, product selection, request creation,
and published Product Builder progression. AI is optional and cannot write
business records or bypass organization-level authorization.
"""
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
import json
import logging
import re
import hmac
import hashlib
from urllib.parse import urlsplit
from .models import WhatsAppPhoneNumber, WhatsAppConnection, Conversation, ConversationState, Message
from customers.models import Customer
from products.models import Product
from business_requests.models import BusinessRequest, RequestCategory
from .handover import activate_human_handover
from business_requests.whatsapp_config import get_whatsapp_message
logger = logging.getLogger(__name__)

def _whatsapp_ai_is_enabled(organization):
    """Read the active organization's WhatsApp AI switch safely."""
    organization_settings = getattr(organization, 'settings', None)
    if not isinstance(organization_settings, dict):
        return True
    ai_settings = organization_settings.get('whatsapp_ai', {})
    if not isinstance(ai_settings, dict):
        return True
    return ai_settings.get('enabled', True) is True

def verify_meta_webhook_signature(request):
    """Verify that a WhatsApp webhook POST came from Meta."""
    app_secret = getattr(settings, 'WHATSAPP_APP_SECRET', '')
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not app_secret or not signature:
        return False
    expected_signature = 'sha256=' + hmac.new(app_secret.encode('utf-8'), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature)

def find_request_category(text, organization=None):
    """Delegate category matching to Business Requests."""
    from business_requests.services.whatsapp import find_request_category as service
    return service(text, organization)

def normalize_phone_number(phone_number):
    """
    Normalize Tanzanian phone numbers to international format.

    Examples:
        0764819996  -> +255764819996
        255764819996 -> +255764819996
        +255764819996 -> +255764819996
    """
    if not phone_number:
        return ''
    phone = str(phone_number).strip()
    phone = re.sub('[^\\d+]', '', phone)
    if phone.startswith('+'):
        return phone
    if phone.startswith('255'):
        return f'+{phone}'
    if phone.startswith('0') and len(phone) >= 9:
        return f'+255{phone[1:]}'
    return phone

def _get_whatsapp_sender_credentials(whatsapp_phone):
    """
    Resolve credentials for the selected WhatsApp sender.

    Tenant isolation:
    - A tenant phone can only use its own organization's connection.
    - Faltasi global credentials are never substituted for another tenant.
    - Development fallback is allowed only when no phone record is supplied.
    """
    from django.conf import settings
    from whatsapp.models import WhatsAppConnection
    if whatsapp_phone is None:
        if not settings.DEBUG:
            return (None, None)
        token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', None)
        phone_number_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', None)
        if token and phone_number_id:
            return (token, phone_number_id)
        return (None, None)
    organization = getattr(whatsapp_phone, 'organization', None)
    business_account = getattr(whatsapp_phone, 'whatsapp_business_account', None)
    if not organization or not business_account:
        return (None, None)
    if whatsapp_phone.organization_id != business_account.organization_id:
        return (None, None)
    if organization.status != 'active':
        return (None, None)
    if not whatsapp_phone.is_active or whatsapp_phone.status != 'connected' or (not whatsapp_phone.phone_number_id):
        return (None, None)
    if not business_account.is_active or business_account.status != 'connected':
        return (None, None)
    connection = WhatsAppConnection.objects.filter(organization=organization, whatsapp_business_account=business_account, status='connected').first()
    access_token = connection.access_token if connection and connection.access_token else None
    is_platform_owner = organization.organization_type == 'platform_owner'
    if not access_token and is_platform_owner:
        access_token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', None)
    if not access_token:
        return (None, None)
    return (access_token, whatsapp_phone.phone_number_id)

def customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
    """
    Prevent outbound WhatsApp sends to inactive, blocked, or removed
    customer phone channels.

    Check both current customer records and retained conversation
    history within the receiving organization.

    Unknown recipients retain existing behavior.
    """
    if not whatsapp_phone or not phone_number:
        return False
    organization = whatsapp_phone.organization
    raw_phone = str(phone_number).strip()
    if not raw_phone:
        return False
    normalized = normalize_phone_number(raw_phone)
    candidates = {raw_phone}
    if normalized:
        candidates.add(str(normalized).strip())
        candidates.add(str(normalized).strip().lstrip('+'))
    candidates.discard('')
    customers = Customer.objects.filter(organization=organization, phone__in=candidates)
    for customer in customers:
        if customer.phone_status != 'active' or customer.status != 'active':
            return False
    prior_conversations = Conversation.objects.filter(organization=organization, phone_number__in=candidates, customer__isnull=False).select_related('customer').order_by('-last_message_at', '-id')
    for conversation in prior_conversations:
        customer = conversation.customer
        if customer.phone_status != 'active' or customer.status != 'active':
            return False
    return True

def send_whatsapp_template(whatsapp_phone, phone_number, template_name, language_code='en_US', components=None):
    """Send an approved WhatsApp template using the authorized sender."""
    import requests
    if not phone_number or not template_name:
        return None
    if not customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
        return None
    access_token, phone_number_id = _get_whatsapp_sender_credentials(whatsapp_phone)
    if not access_token or not phone_number_id:
        return None
    try:
        url = f'https://graph.facebook.com/v26.0/{phone_number_id}/messages'
        headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
        template = {'name': str(template_name).strip(), 'language': {'code': str(language_code).strip()}}
        if components:
            template['components'] = components
        payload = {'messaging_product': 'whatsapp', 'to': str(phone_number).strip().lstrip('+'), 'type': 'template', 'template': template}
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        return response
    except requests.RequestException as exc:
        return None
    except Exception as exc:
        return None

def send_whatsapp_message(whatsapp_phone, phone_number, message):
    """Send a WhatsApp text message using the authorized sender."""
    import requests
    if not phone_number or not message:
        return None
    if not customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
        return None
    access_token, phone_number_id = _get_whatsapp_sender_credentials(whatsapp_phone)
    if not access_token or not phone_number_id:
        return None
    try:
        url = f'https://graph.facebook.com/v26.0/{phone_number_id}/messages'
        headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
        payload = {'messaging_product': 'whatsapp', 'to': str(phone_number).strip().lstrip('+'), 'type': 'text', 'text': {'body': message}}
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        return response
    except requests.RequestException as exc:
        return None
    except Exception as exc:
        return None

def send_whatsapp_image(whatsapp_phone, phone_number, image_url, caption=''):
    """Send a product image using the authorized WhatsApp sender."""
    import requests
    if not image_url or not phone_number:
        return None
    if not customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
        return None
    access_token, phone_number_id = _get_whatsapp_sender_credentials(whatsapp_phone)
    if not access_token or not phone_number_id:
        return None
    try:
        url = f'https://graph.facebook.com/v26.0/{phone_number_id}/messages'
        headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
        payload = {'messaging_product': 'whatsapp', 'to': str(phone_number).strip().lstrip('+'), 'type': 'image', 'image': {'link': image_url}}
        if caption:
            payload['image']['caption'] = caption[:1024]
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        return response
    except requests.RequestException as exc:
        return None
    except Exception as exc:
        return None

def send_product_marketing_template(customer, whatsapp_phone, phone_number, conversation, incoming_message_id):
    """
    Send and log the product marketing template.

    Explicit marketing consent and an active customer phone are both
    required. Duplicate sends and cross-organization sends are blocked.
    """
    if not customer or not whatsapp_phone or (not conversation) or (not phone_number) or (not incoming_message_id):
        return False
    organization = customer.organization
    if not organization:
        return False
    if customer.organization_id != organization.id or conversation.organization_id != organization.id or whatsapp_phone.organization_id != organization.id or (conversation.customer_id != customer.id):
        return False
    if not customer.whatsapp_marketing_opt_in:
        return False
    if customer.status != 'active':
        return False
    if customer.phone_status != 'active':
        return False
    recipient_normalized = normalize_phone_number(phone_number)
    customer_normalized = normalize_phone_number(customer.phone)
    conversation_normalized = normalize_phone_number(conversation.phone_number)
    if not recipient_normalized or not customer_normalized or (not conversation_normalized) or (recipient_normalized != customer_normalized) or (recipient_normalized != conversation_normalized):
        return False
    if not customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
        return False
    template_name = getattr(settings, 'WHATSAPP_PRODUCT_ENQUIRY_TEMPLATE_NAME', '')
    language_code = getattr(settings, 'WHATSAPP_PRODUCT_ENQUIRY_TEMPLATE_LANGUAGE', 'en_US')
    if not template_name:
        return False
    already_sent = Message.objects.filter(organization=organization, conversation=conversation, direction='outgoing', metadata__template_name=template_name, metadata__triggered_by_incoming_message_id=incoming_message_id).exists()
    if already_sent:
        return False
    response = send_whatsapp_template(whatsapp_phone=whatsapp_phone, phone_number=phone_number, template_name=template_name, language_code=language_code, components=None)
    if response is None or response.status_code != 200:
        return False
    try:
        response_data = response.json()
    except ValueError:
        response_data = {'raw_response': response.text}
    template_message_id = None
    try:
        template_message_id = response_data.get('messages', [{}])[0].get('id')
    except (IndexError, AttributeError, TypeError):
        pass
    Message.objects.create(organization=organization, conversation=conversation, direction='outgoing', sender_type='faltasi', message_type='text', content=f'Marketing template: {template_name}', whatsapp_message_id=template_message_id, delivery_status='sent', metadata={'template_name': template_name, 'language_code': language_code, 'triggered_by_incoming_message_id': incoming_message_id, 'provider_response': response_data})
    return True

def get_public_product_image_url(product, request=None):
    """Return an absolute HTTPS image URL that Meta can attempt to fetch."""
    try:
        if not product or not product.image:
            return None
        image_url = product.image.url
    except (AttributeError, ValueError, OSError) as exc:
        return None
    if not urlsplit(image_url).scheme and request is not None:
        image_url = request.build_absolute_uri(image_url)
    parsed_url = urlsplit(image_url)
    if parsed_url.scheme.lower() != 'https' or not parsed_url.netloc:
        return None
    return image_url

def send_and_log_whatsapp_product_image(whatsapp_phone, phone_number, product, conversation, organization, request=None):
    """Send one verified product image and save the WhatsApp message record."""
    if not all([whatsapp_phone, phone_number, product, conversation, organization]):
        return False
    if whatsapp_phone.organization_id != organization.id or conversation.organization_id != organization.id or product.organization_id != organization.id:
        return False
    if not customer_phone_allows_whatsapp(whatsapp_phone, phone_number):
        return False
    image_url = get_public_product_image_url(product, request=request)
    if not image_url:
        return False
    from products.services.whatsapp_discovery import format_whatsapp_product_caption
    caption = format_whatsapp_product_caption(product, organization)
    if not caption:
        return False
    response = send_whatsapp_image(whatsapp_phone, phone_number, image_url, caption=caption)
    succeeded = response is not None and response.status_code in (200, 201)
    try:
        response_data = response.json() if response is not None else {'error': 'No response received from WhatsApp image endpoint.'}
    except ValueError:
        response_data = {'raw_response': response.text}
    whatsapp_message_id = None
    try:
        whatsapp_message_id = response_data.get('messages', [{}])[0].get('id')
    except (AttributeError, IndexError, TypeError):
        whatsapp_message_id = None
    Message.objects.create(organization=organization, conversation=conversation, direction='outgoing', sender_type='faltasi', message_type='image', content=caption, whatsapp_message_id=whatsapp_message_id, delivery_status='sent' if succeeded else 'failed', metadata={'product_id': product.id, 'product_sku': product.sku, 'image_url': image_url, 'whatsapp_response': response_data})
    if succeeded:
        from django.utils import timezone
        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=['last_message_at'])
    return succeeded

def get_or_create_conversation_state(conversation):
    """
    Get the ConversationState for a conversation.
    Create it if it does not exist.
    """
    state, created = ConversationState.objects.get_or_create(conversation=conversation)
    if created:
        pass
    return state

def _get_configured_whatsapp_message(organization, message_type, language='sw'):
    """Read organization-owned message configuration without code fallbacks."""
    raw_language = str(language or '').lower()
    language_key = 'mixed' if raw_language.startswith('mixed') else (
        'en' if raw_language.startswith('en') else 'sw'
    )
    try:
        configured = get_whatsapp_message(
            organization,
            message_type,
            language=language_key,
        )
        if configured:
            return configured
    except Exception:
        logger.exception(
            'Unable to load WhatsApp message configuration (%s).',
            message_type,
        )

    return None

def process_whatsapp_marketing_consent(customer, text):
    """
    Process explicit WhatsApp marketing consent commands.

    YES  = subscribe
    NO   = decline the subscription invitation
    STOP = unsubscribe

    Marketing consent belongs to the customer's
    organization-specific record.
    """
    if not customer or not text:
        return None
    command = text.strip().upper()
    if command == 'YES':
        if not customer.whatsapp_marketing_opt_in:
            customer.whatsapp_marketing_opt_in = True
            customer.whatsapp_marketing_opt_in_at = timezone.now()
            customer.whatsapp_marketing_opt_in_source = 'whatsapp_reply'
        customer.whatsapp_marketing_opt_out_at = None
        customer.whatsapp_marketing_declined_at = None
        customer.save(update_fields=['whatsapp_marketing_opt_in', 'whatsapp_marketing_opt_in_at', 'whatsapp_marketing_opt_in_source', 'whatsapp_marketing_opt_out_at', 'whatsapp_marketing_declined_at', 'updated_at'])
        return _get_configured_whatsapp_message(customer.organization, 'marketing_opt_in_confirmation', getattr(customer.organization, 'language', 'sw'))
    if command == 'NO':
        if not customer.whatsapp_marketing_opt_in:
            customer.whatsapp_marketing_declined_at = timezone.now()
            customer.save(update_fields=['whatsapp_marketing_declined_at', 'updated_at'])
        return _get_configured_whatsapp_message(customer.organization, 'marketing_declined_confirmation', getattr(customer.organization, 'language', 'sw'))
    if command == 'STOP':
        customer.whatsapp_marketing_opt_in = False
        customer.whatsapp_marketing_opt_out_at = timezone.now()
        customer.save(update_fields=['whatsapp_marketing_opt_in', 'whatsapp_marketing_opt_out_at', 'updated_at'])
        return _get_configured_whatsapp_message(customer.organization, 'marketing_opt_out_confirmation', getattr(customer.organization, 'language', 'sw'))
    return None

def create_business_request(customer, text, category, conversation=None):
    """Delegate request creation and tenant checks to Business Requests."""
    from business_requests.services.whatsapp import create_business_request as service
    return service(customer, text, category, conversation)

def get_whatsapp_phone_number(phone_number_id):
    """
    Find the WhatsApp phone number configuration from
    Meta's phone_number_id.
    """
    if not phone_number_id:
        return None
    try:
        whatsapp_phone = WhatsAppPhoneNumber.objects.select_related('organization', 'whatsapp_business_account').get(phone_number_id=phone_number_id, is_active=True)
        return whatsapp_phone
    except WhatsAppPhoneNumber.DoesNotExist:
        return None
    except WhatsAppPhoneNumber.MultipleObjectsReturned:
        return None

def is_new_request_message(text, current_category=None, current_field=None, organization=None):
    """Use organization-configured request phrases and field rules."""
    from business_requests.services.whatsapp import is_new_request_message as service
    return service(text, current_category, current_field, organization)

def process_request_fields(category, state, text):
    """Delegate request question progression to Business Requests."""
    from business_requests.services.whatsapp import process_request_fields as service
    organization = getattr(category, "organization", None)
    language = getattr(organization, "language", None) if organization else None
    return service(category, state, text, organization=organization, language=language)

def update_business_request_details(business_request, state):
    """Delegate request answer persistence to Business Requests."""
    from business_requests.services.whatsapp import update_business_request_details as service
    return service(business_request, state)

def create_request_workflow(business_request):
    """Delegate assignment and workflow creation to Business Requests."""
    from business_requests.services.workflow import create_request_workflow as service
    return service(business_request)

def notify_assigned_staff(business_request, assignment):
    """Delegate configured staff notification to Business Requests."""
    from business_requests.services.workflow import notify_assigned_staff as service
    return service(business_request, assignment)

@csrf_exempt
def webhook(request):
    """

    WhatsApp Cloud API webhook.



    Handles:

    - Meta webhook verification

    - Multi-business WhatsApp routing

    - Incoming WhatsApp text messages

    - Duplicate message protection

    - Organization-specific customers

    - Organization-specific conversations

    - Conversation state

    - Request category detection

    - BusinessRequest creation/reuse

    - RequestField-based information collection

    - New request detection

    - Automatic WhatsApp replies

    - Outgoing message logging

    """
    if request.method == 'GET':
        verify_token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        if verify_token and challenge:
            if verify_token == settings.WHATSAPP_VERIFY_TOKEN:
                return HttpResponse(challenge)
            return HttpResponse('Invalid verify token', status=403)
        return HttpResponse('OK', status=200)
    if request.method != 'POST':
        return HttpResponse(status=405)
    if not verify_meta_webhook_signature(request):
        return HttpResponse('Invalid webhook signature', status=403)
    try:
        body = request.body.decode('utf-8', errors='replace')
        data = json.loads(body)
        entry = data.get('entry', [])
        if not entry:
            return JsonResponse({'status': 'ok'})
        changes = entry[0].get('changes', [])
        if not changes:
            return JsonResponse({'status': 'ok'})
        value = changes[0].get('value', {})
        metadata = value.get('metadata', {})
        phone_number_id = metadata.get('phone_number_id')
        if not phone_number_id:
            return JsonResponse({'status': 'ok', 'message': 'No phone number ID found'})
        try:
            whatsapp_phone = WhatsAppPhoneNumber.objects.select_related('organization', 'whatsapp_business_account').get(phone_number_id=phone_number_id)
        except WhatsAppPhoneNumber.DoesNotExist:
            return JsonResponse({'status': 'ok', 'message': 'Unknown WhatsApp phone number'})
        except WhatsAppPhoneNumber.MultipleObjectsReturned:
            return JsonResponse({'status': 'ok', 'message': 'Multiple WhatsApp phone numbers found'})
        organization = whatsapp_phone.organization
        whatsapp_business_account = whatsapp_phone.whatsapp_business_account
        if whatsapp_phone.organization_id != whatsapp_business_account.organization_id:
            return JsonResponse({'status': 'ok', 'message': 'WhatsApp organization mismatch'}, status=403)
        statuses = value.get('statuses', [])
        if statuses:
            for status_item in statuses:
                whatsapp_message_id = status_item.get('id')
                new_status = status_item.get('status')
                if new_status == 'failed':
                    pass
                allowed_statuses = {'sent', 'delivered', 'read', 'failed'}
                if not whatsapp_message_id or new_status not in allowed_statuses:
                    continue
                saved_message = Message.objects.filter(organization=organization, whatsapp_message_id=whatsapp_message_id, direction='outgoing').first()
                if not saved_message:
                    continue
                current_status = saved_message.delivery_status
                status_order = {'pending': 0, 'sent': 1, 'delivered': 2, 'read': 3, 'failed': 4}
                if current_status == 'failed':
                    continue
                if new_status != 'failed' and status_order.get(new_status, 0) < status_order.get(current_status, 0):
                    continue
                if new_status == 'failed' and current_status in {'delivered', 'read'}:
                    continue
                saved_message.delivery_status = new_status
                message_metadata = saved_message.metadata or {}
                message_metadata['whatsapp_status_update'] = status_item
                saved_message.metadata = message_metadata
                saved_message.save(update_fields=['delivery_status', 'metadata'])
        messages = value.get('messages', [])
        if messages:
            connection_is_valid = organization.status == 'active' and whatsapp_phone.is_active and (whatsapp_phone.status == 'connected') and whatsapp_business_account.is_active and (whatsapp_business_account.status == 'connected')
            if not connection_is_valid:
                return JsonResponse({'status': 'ok', 'message': 'WhatsApp connection is inactive'})
        if not messages:
            return JsonResponse({'status': 'ok'})
        message = messages[0]
        whatsapp_message_id = message.get('id')
        if whatsapp_message_id:
            existing_message = Message.objects.filter(organization=organization, whatsapp_message_id=whatsapp_message_id).first()
            if existing_message:
                return JsonResponse({'status': 'ok', 'duplicate': True})
        sender = normalize_phone_number(message.get('from'))
        message_type = message.get('type')
        if message_type != 'text':
            return JsonResponse({'status': 'ok', 'message': 'Non-text message received'})
        text = message.get('text', {}).get('body', '').strip()
        if not sender:
            return JsonResponse({'status': 'ok'})
        if not text:
            return JsonResponse({'status': 'ok'})
        customer = Customer.objects.filter(organization=organization, phone=sender).first()
        if customer:
            pass
        else:
            customer = Customer.objects.create(organization=organization, phone=sender, name='WhatsApp Customer', customer_type='individual', preferred_contact_method='whatsapp', status='active', relationship_stage='visitor', phone_status='active', contact_source='whatsapp', first_contact_at=timezone.now(), last_interaction_at=timezone.now())
        customer.last_interaction_at = timezone.now()
        if not customer.first_contact_at:
            customer.first_contact_at = timezone.now()
        customer.save(update_fields=['last_interaction_at', 'first_contact_at', 'updated_at'])
        conversation = Conversation.objects.filter(organization=organization, whatsapp_phone_number=whatsapp_phone, customer=customer, phone_number=sender, status='active').first()
        if not conversation:
            open_request = BusinessRequest.objects.filter(customer=customer, category__organization=organization, source='website', status__in=['new', 'in_progress', 'waiting_customer', 'waiting_approval']).order_by('-created_at').first()
            conversation = Conversation.objects.create(organization=organization, whatsapp_phone_number=whatsapp_phone, customer=customer, phone_number=sender, whatsapp_user_id=sender, business_request=open_request, status='active')
        state = get_or_create_conversation_state(conversation)
        if conversation.business_request:
            linked_request = conversation.business_request
            linked_category = linked_request.category
            state_data = state.data or {}
            if linked_category and (not state_data.get('category')):
                state_data['category'] = linked_category.name
                state_data['business_request_id'] = linked_request.id
                state.data = state_data
                state.current_step = None
                state.waiting_for = None
                state.save()
        incoming_message = Message.objects.create(organization=organization, conversation=conversation, direction='incoming', sender_type='customer', message_type=message_type, content=text, delivery_status='delivered', whatsapp_message_id=whatsapp_message_id, metadata=message)
        conversation.save(update_fields=['last_message_at'])
        state_data = state.data or {}
        stored_category_name = state_data.get('category')
        current_category = None
        if stored_category_name:
            try:
                current_category = RequestCategory.objects.get(name=stored_category_name, organization=organization, is_active=True)
            except RequestCategory.DoesNotExist:
                current_category = None
        product_images_to_send = []
        should_send_product_marketing_template = False
        reply = None
        consent_reply = process_whatsapp_marketing_consent(customer, text)
        if consent_reply is not None:
            reply = consent_reply
            product_flow_handled = True
            detected_category = None
        elif conversation.handling_mode == 'human':
            reply = None
            product_flow_handled = True
            detected_category = None
        else:
            state_data_for_discovery = (
                state.data if isinstance(state.data, dict) else {}
            )
            discovery_state = state_data_for_discovery.get(
                'whatsapp_product_discovery'
            )

            pending_product_discovery = (
                isinstance(discovery_state, dict)
                and discovery_state.get('status') == 'awaiting_clarification'
                and state.current_step == 'whatsapp_product_discovery'
                and state.waiting_for == 'product_discovery_clarification'
                and isinstance(discovery_state.get('original_request'), str)
                and bool(discovery_state.get('original_request').strip())
            )
            state_data_for_handover = state.data if isinstance(state.data, dict) else {}
            active_workflow = bool(state.current_step or state.waiting_for or state_data_for_handover.get('category') or state_data_for_handover.get('business_request_id') or state_data_for_handover.get('selected_whatsapp_product_id') or conversation.business_request_id)
            handover_language = None
            if active_workflow:
                handover_language = get_ai_human_support_language(text, organization, state, incoming_message.id if incoming_message else None)
            if handover_language:
                activate_human_handover(conversation)
                product_flow_reply = _human_handover_acknowledgement(handover_language, organization=organization)
            else:
                product_flow_reply = None
                product_flow_reply = handle_whatsapp_product_conversation(
                    text,
                    organization,
                    state,
                    incoming_message.id if incoming_message else None,
                )
            product_flow_handled = product_flow_reply is not None

            if product_flow_handled:
                reply = product_flow_reply
                detected_category = None

                discovery_state = (
                    state.data
                    if isinstance(state.data, dict)
                    else {}
                ).get('whatsapp_product_discovery')

                if (
                    isinstance(discovery_state, dict)
                    and discovery_state.get('status') == 'awaiting_next_option'
                ):
                    displayed_product_ids = (
                        state.data or {}
                    ).get('whatsapp_product_ids', [])

                    products_by_id = Product.objects.filter(
                        organization=organization,
                        id__in=displayed_product_ids,
                        is_active=True,
                        deleted_at__isnull=True,
                        show_on_whatsapp=True,
                    ).in_bulk()

                    product_images_to_send = [
                        products_by_id[product_id]
                        for product_id in displayed_product_ids
                        if product_id in products_by_id
                    ]


            else:
                detected_category = find_request_category(text, organization=organization)
                general_ai_result = None
                general_ai_attempted = False
                selected_product_id = state_data_for_handover.get('selected_whatsapp_product_id')
                if (
                    not pending_product_discovery
                    and detected_category is None
                    and (not current_category)
                    and (not selected_product_id)
                ):
                    general_ai_attempted = True
                    general_ai_result = get_ai_general_interpretation(
                        text,
                        organization,
                        state,
                        incoming_message.id if incoming_message else None,
                    )
                    if general_ai_result:
                        intent = general_ai_result.get('intent')
                        action = general_ai_result.get('action')
                        logger.info(
                            'WhatsApp general AI classified message: organization_id=%s '
                            'conversation_id=%s action=%s intent=%s language=%s answer_length=%s',
                            organization.pk,
                            conversation.pk,
                            action,
                            intent,
                            general_ai_result.get('language', 'sw'),
                            len(general_ai_result.get('answer') or ''),
                        )

                        if intent == 'human_support' and action == 'route_existing':
                            activate_human_handover(conversation)
                            reply = _human_handover_acknowledgement(
                                general_ai_result.get('language', 'sw'),
                                organization=organization,
                            )
                            detected_category = None
                            product_flow_handled = True

                        elif action == 'reply':
                            reply = general_ai_result['answer']
                            detected_category = None
                            product_flow_handled = True

                        elif intent in {'service_enquiry', 'business_request'} and action == 'route_existing':
                            ai_category_result = get_ai_request_category_reply(
                                text,
                                organization,
                                state,
                                incoming_message.id if incoming_message else None,
                            )
                            if ai_category_result:
                                if ai_category_result.get('clarification'):
                                    reply = ai_category_result['clarification']
                                    product_flow_handled = True
                                    detected_category = None
                                elif ai_category_result.get('category'):
                                    detected_category = ai_category_result['category']
                                    logger.info(
                                        'WhatsApp AI category matched: organization_id=%s '
                                        'category_id=%s category_name=%s',
                                        organization.pk,
                                        detected_category.pk,
                                        detected_category.name,
                                    )
                            else:
                                logger.info(
                                    'WhatsApp AI could not map service/business intent to an active '
                                    'organization category: organization_id=%s conversation_id=%s intent=%s',
                                    organization.pk,
                                    conversation.pk,
                                    intent,
                                )

                        elif intent == 'workflow_input' and action == 'route_existing':
                            logger.info(
                                'WhatsApp AI classified workflow input without an active workflow: '
                                'organization_id=%s conversation_id=%s',
                                organization.pk,
                                conversation.pk,
                            )

                        elif intent == 'product_enquiry' and action == 'route_existing':
                            logger.info(
                                'WhatsApp AI routed message to product discovery: '
                                'organization_id=%s conversation_id=%s',
                                organization.pk,
                                conversation.pk,
                            )
                        else:
                            logger.warning(
                                'WhatsApp general AI returned an unhandled route: '
                                'organization_id=%s conversation_id=%s action=%s intent=%s',
                                organization.pk,
                                conversation.pk,
                                action,
                                intent,
                            )
                    else:
                        logger.info(
                            'WhatsApp general AI returned no usable interpretation: '
                            'organization_id=%s conversation_id=%s',
                            organization.pk,
                            conversation.pk,
                        )

        current_field = None
        if not product_flow_handled and current_category and state.waiting_for:
            try:
                current_field = current_category.request_fields.get(name=state.waiting_for, is_active=True)
            except Exception:
                current_field = None
        new_request = False
        if not product_flow_handled and detected_category:
            new_request = is_new_request_message(
                text,
                current_category=current_category,
                current_field=current_field,
                organization=organization,
            )
        if not product_flow_handled and new_request:
            category = detected_category
            if category and (customer.organization_id != organization.id or category.organization_id != organization.id or (category.department_id and category.department.organization_id != organization.id)):
                category = None
            if not category:
                reply = get_whatsapp_message(
                    organization,
                    'request_not_understood',
                    getattr(organization, 'language', 'sw'),
                ) or get_whatsapp_message(
                    organization,
                    'general_fallback',
                    getattr(organization, 'language', 'sw'),
                )
            else:
                business_request = create_business_request(
                    customer,
                    text,
                    category,
                    conversation,
                )
                conversation.business_request = business_request
                conversation.save(update_fields=['business_request'])
                state_data = {'request_text': text, 'category': category.name, 'business_request_id': business_request.id}
                state.current_step = None
                state.waiting_for = None
                state.data = state_data
                state.save()
                if category:
                    is_new_business_request = business_request is not None and state_data.get('business_request_id') == business_request.id and (state_data.get('request_text') == text) and (not state_data.get('location')) and (state.waiting_for is None)
                    if is_new_business_request:
                        reply = process_request_fields(category, state, None)
                    else:
                        reply = process_request_fields(category, state, text)
                    if business_request:
                        update_business_request_details(business_request, state)
                        if state.current_step == 'details_collected':
                            create_request_workflow(business_request)
        elif not product_flow_handled and current_category:
            category = current_category
            business_request = conversation.business_request
            if not business_request:
                business_request = create_business_request(customer, text, category, conversation)
                if business_request:
                    conversation.business_request = business_request
                    conversation.save(update_fields=['business_request'])
            reply = process_request_fields(category, state, text)
            if business_request:
                update_business_request_details(business_request, state)
                if state.current_step == 'details_collected':
                    create_request_workflow(business_request)
        elif not product_flow_handled and detected_category:
            category = detected_category
            business_request = create_business_request(customer, text, category, conversation)
            state_data = {'request_text': text, 'category': category.name, 'business_request_id': business_request.id if business_request else None}
            state.current_step = None
            state.waiting_for = None
            state.data = state_data
            state.save()
            if business_request:
                conversation.business_request = business_request
                conversation.save(update_fields=['business_request'])
            if category:
                is_new_business_request = business_request is not None and state_data.get('business_request_id') == business_request.id and (state_data.get('request_text') == text) and (not state_data.get('location')) and (state.waiting_for is None)
                if is_new_business_request:
                    reply = process_request_fields(category, state, None)
                else:
                    reply = process_request_fields(category, state, text)
                if business_request:
                    update_business_request_details(business_request, state)
                    if state.current_step == 'details_collected':
                        create_request_workflow(business_request)
        elif not product_flow_handled:
            is_product_enquiry = general_ai_attempted and isinstance(general_ai_result, dict) and (general_ai_result.get('intent') == 'product_enquiry')
            if general_ai_attempted and (not is_product_enquiry):
                product_reply = None
                if not reply:
                    reply = _get_configured_whatsapp_message(organization, 'fallback', getattr(organization, 'language', 'sw'))
            else:
                discovery = get_ai_product_discovery_reply(
                    text,
                    organization,
                    state,
                    incoming_message.id if incoming_message else None,
                )

                if discovery:
                    reply = discovery['reply']
                    product_reply = discovery['product_reply']

                    logger.info(
                        'WhatsApp AI product discovery returned a customer reply: '
                        'organization_id=%s conversation_id=%s has_catalogue_products=%s',
                        organization.pk,
                        conversation.pk,
                        bool(product_reply),
                    )
                else:
                    # Keep direct catalogue search as a fallback when
                    # AI discovery is unavailable or returns no usable result.
                    product_reply = search_whatsapp_products(
                        text,
                        organization,
                        state,
                    )

                    if product_reply:
                        reply = product_reply
                    else:
                        logger.info(
                            'WhatsApp product discovery and direct catalogue search '
                            'returned no usable result: organization_id=%s conversation_id=%s',
                            organization.pk,
                            conversation.pk,
                        )
                        reply = _get_configured_whatsapp_message(
                            organization,
                            'fallback',
                            getattr(organization, 'language', 'sw'),
                        )
            should_send_product_marketing_template = bool(product_reply and customer and customer.whatsapp_marketing_opt_in and whatsapp_message_id)

            if product_reply and state is not None:
                displayed_product_ids = (state.data or {}).get('whatsapp_product_ids', [])
                products_by_id = Product.objects.filter(organization=organization, id__in=displayed_product_ids, is_active=True, deleted_at__isnull=True, show_on_whatsapp=True).in_bulk()
                product_images_to_send = [products_by_id[product_id] for product_id in displayed_product_ids if product_id in products_by_id]

        marketing_invitation_included = False
        if customer and customer.phone_status == 'active' and (customer.status == 'active') and (not customer.whatsapp_marketing_opt_in) and (not customer.whatsapp_marketing_invitation_sent_at) and (not customer.whatsapp_marketing_declined_at) and (not customer.whatsapp_marketing_opt_out_at):
            organization_language = (getattr(customer.organization, 'language', None) or '').strip().lower().replace('-', '_')
            marketing_invitation = _get_configured_whatsapp_message(customer.organization, 'marketing_invitation', organization_language or 'sw')
            if marketing_invitation:
                reply = (reply or '') + '\n\n' + marketing_invitation
                marketing_invitation_included = True
        response = send_whatsapp_message(whatsapp_phone, sender, reply) if reply else None
        if response is not None and response.status_code == 200:
            try:
                response_data = response.json()
            except ValueError:
                response_data = {'raw_response': response.text}
            outgoing_whatsapp_message_id = None
            try:
                outgoing_whatsapp_message_id = response_data.get('messages', [{}])[0].get('id')
            except (IndexError, AttributeError, TypeError):
                outgoing_whatsapp_message_id = None
            outgoing_message = Message.objects.create(organization=organization, conversation=conversation, direction='outgoing', sender_type='faltasi', message_type='text', content=reply, whatsapp_message_id=outgoing_whatsapp_message_id, delivery_status='sent', metadata=response_data)
            if marketing_invitation_included:
                customer.whatsapp_marketing_invitation_sent_at = timezone.now()
                customer.save(update_fields=['whatsapp_marketing_invitation_sent_at', 'updated_at'])
            conversation.save(update_fields=['last_message_at'])
            for product in product_images_to_send:
                send_and_log_whatsapp_product_image(whatsapp_phone=whatsapp_phone, phone_number=sender, product=product, conversation=conversation, organization=organization, request=request)
            if should_send_product_marketing_template:
                send_product_marketing_template(customer=customer, whatsapp_phone=whatsapp_phone, phone_number=sender, conversation=conversation, incoming_message_id=whatsapp_message_id)
        elif not reply:
            pass
        elif response is not None:
            pass
        return JsonResponse({'status': 'ok'})
    except json.JSONDecodeError as e:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)


def _format_product_builder_question(runtime):
    """Format the next question using the pinned published configuration."""
    if not runtime or runtime.get('status') != 'in_progress':
        return None
    snapshot = runtime.get('snapshot') or {}
    question = runtime.get('question')
    if not isinstance(question, dict):
        return None
    language = snapshot.get('default_language', 'auto')
    translations = question.get('translations') or {}
    question_text = (translations.get(language) if language in ('en', 'sw') else None) or question.get('question', '')
    if not question_text:
        return None
    parts = []
    welcome = snapshot.get('welcome_message')
    if welcome and (not runtime['namespace'].get('answers')) and (not runtime['namespace'].get('skipped')):
        parts.append(welcome)
    parts.append(question_text)
    help_text = question.get('help_text')
    if help_text:
        parts.append(help_text)
    options = [option for option in question.get('options', []) if isinstance(option, dict) and option.get('is_active', True)]
    if options:
        option_lines = []
        for index, option in enumerate(options, start=1):
            option_translations = option.get('translations') or {}
            label = (option_translations.get(language) if language in ('en', 'sw') else None) or option.get('label') or option.get('value')
            option_lines.append(f'{index}. {label}')
        parts.extend(option_lines)
    if question.get('allow_skip') and (not question.get('is_required')):
        skip_message = question.get('skip_message')
        if skip_message:
            parts.append(skip_message)
    return '\n\n'.join((str(part) for part in parts if part))

def _product_builder_completion_response(runtime):
    """Return configured completion text, if supplied."""
    snapshot = (runtime or {}).get('snapshot') or {}
    return snapshot.get('closing_message') or ''


def handle_whatsapp_product_conversation(
    text,
    organization,
    state,
    current_message_id=None,
):
    """Handle product selection and dashboard-configured product questions."""
    if not text or not organization or not state:
        return None

    step = state.current_step
    data = dict(state.data or {})

    # Product discovery yes/no responses and follow-up product selection are
    # configured and owned by the Products discovery service.
    from products.services.whatsapp_discovery import (
        handle_product_discovery_followup,
    )

    discovery_result = handle_product_discovery_followup(
        text,
        organization,
        state,
    )
    if discovery_result.get("handled"):
        return discovery_result.get("reply")

    if step not in {
        'whatsapp_product_selection',
        'whatsapp_product_builder',
    }:
        return None

    def save_state(new_step, waiting_for, updates=None):
        current_data = dict(state.data or {})

        if updates:
            current_data.update(updates)

        state.current_step = new_step
        state.waiting_for = waiting_for
        state.data = current_data
        state.save()

    def answer_builder_unrelated_question(separate_question):
        if not separate_question:
            return None

        try:
            result = get_ai_general_interpretation(
                separate_question,
                organization,
                state,
                current_message_id,
                allow_product_builder=True,
            )

            if not isinstance(result, dict):
                return None

            if result.get('action') != 'reply':
                return None

            answer = result.get('answer')

            if not isinstance(answer, str) or not answer.strip():
                return None

            return answer.strip()

        except Exception:
            logger.exception(
                'WhatsApp Builder separate-question response failed: '
                'organization_id=%s.',
                organization.pk,
            )
            return None

    # STEP 1: Customer selects one of the displayed products.
    if step == 'whatsapp_product_selection':
        product_ids = data.get('whatsapp_product_ids', [])
        normalized = text.strip().lower()
        selected_id = None

        if normalized.isdigit():
            choice = int(normalized)

            if 1 <= choice <= len(product_ids):
                selected_id = product_ids[choice - 1]

        if selected_id is None:
            for product in Product.objects.filter(
                organization=organization,
                id__in=product_ids,
                is_active=True,
                deleted_at__isnull=True,
                show_on_whatsapp=True,
            ):
                if normalized == product.name.lower():
                    selected_id = product.id
                    break

        if selected_id is None:
            return None

        product = Product.objects.filter(
            organization=organization,
            id=selected_id,
            is_active=True,
            deleted_at__isnull=True,
            show_on_whatsapp=True,
        ).first()

        if not product:
            save_state(
                None,
                None,
                {
                    'whatsapp_product_ids': [],
                    'selected_whatsapp_product_id': None,
                    'selected_whatsapp_product_name': None,
                },
            )
            return None

        save_state(
            'whatsapp_product_completed',
            None,
            {
                'selected_whatsapp_product_id': product.id,
                'selected_whatsapp_product_name': product.name,
            },
        )

        from conversation_builder.runtime import (
            get_runtime_status,
            start_product_conversation,
        )

        runtime = start_product_conversation(
            state,
            organization,
            product,
        )

        if runtime and runtime.get('status') == 'in_progress':
            try:
                if not _whatsapp_ai_is_enabled(organization):
                    raise RuntimeError(
                        'WhatsApp AI is disabled for this organization.'
                    )

                from whatsapp.ai_service import (
                    select_next_product_builder_question,
                )

                preferred_key = select_next_product_builder_question(
                    text,
                    organization,
                    state,
                    product,
                    runtime,
                )

                if preferred_key:
                    runtime = get_runtime_status(
                        state,
                        organization,
                        product,
                        preferred_question_key=preferred_key,
                    )

            except Exception:
                logger.exception(
                    'AI question selection failed at product conversation '
                    'start; using Builder order.'
                )

            prompt = _format_product_builder_question(runtime)

            if prompt:
                return prompt

            return (
                runtime.get('snapshot') or {}
            ).get('fallback_message') or None

        return None

    # STEP 2: Continue the selected product's configured Builder.
    from conversation_builder.runtime import (
        get_runtime_status,
        submit_product_question_answers,
    )

    product_id = data.get('selected_whatsapp_product_id')

    product = Product.objects.filter(
        organization=organization,
        id=product_id,
        is_active=True,
        deleted_at__isnull=True,
        show_on_whatsapp=True,
    ).first()

    if not product:
        save_state(
            None,
            None,
            {
                'selected_whatsapp_product_id': None,
                'selected_whatsapp_product_name': None,
            },
        )
        return None

    runtime = get_runtime_status(state, organization, product)

    if not runtime:
        return None

    if runtime.get('status') == 'completed':
        save_state('whatsapp_product_completed', None)
        return _product_builder_completion_response(runtime) or None

    question = runtime.get('question')

    if not isinstance(question, dict) or not question.get('key'):
        return (
            runtime.get('snapshot') or {}
        ).get('fallback_message') or None

    # STEP 3: Extract Builder answers and separate customer questions.
    answers = {}
    corrections = {}
    unrelated_question = ''

    try:
        if not _whatsapp_ai_is_enabled(organization):
            raise RuntimeError(
                'WhatsApp AI is disabled for this organization.'
            )

        from whatsapp.ai_service import interpret_product_builder_answers

        extraction = interpret_product_builder_answers(
            text,
            organization,
            state,
            product,
            runtime,
        )

        answers = extraction.get('answers') or {}
        corrections = extraction.get('corrections') or {}
        unrelated_question = extraction.get('unrelated_question') or ''

    except Exception:
        logger.exception(
            'Product Builder answer extraction failed; '
            'preserving current Builder question.'
        )

    # STEP 4: Obtain a separate answer while the Builder is still active.
    # This does not change the Builder state.
    unrelated_reply = answer_builder_unrelated_question(
        unrelated_question
    )

    # Do not assume the customer's entire message is an answer.
    # If AI cannot identify a valid Builder answer, keep the current
    # question active and allow the customer to clarify.
    # STEP 5: Submit only actual Builder answers or corrections.
    result = {
        'status': 'no_input',
        'rejected': [],
    }

    if answers or corrections:
        result = submit_product_question_answers(
            state,
            organization,
            product,
            answers,
            corrections=corrections,
        )

    runtime = get_runtime_status(state, organization, product)

    if not runtime:
        return unrelated_reply

    # STEP 6: Select the next eligible Builder question only when
    # the customer supplied Builder answers or corrections.
    if (
        (answers or corrections)
        and result.get('status') != 'completed'
        and runtime.get('status') == 'in_progress'
    ):
        try:
            if not _whatsapp_ai_is_enabled(organization):
                raise RuntimeError(
                    'WhatsApp AI is disabled for this organization.'
                )

            from whatsapp.ai_service import (
                select_next_product_builder_question,
            )

            preferred_key = select_next_product_builder_question(
                text,
                organization,
                state,
                product,
                runtime,
            )

            if preferred_key:
                runtime = get_runtime_status(
                    state,
                    organization,
                    product,
                    preferred_question_key=preferred_key,
                )

        except Exception:
            logger.exception(
                'AI question selection failed; using Builder question order.'
            )

    # STEP 7: Builder completion.
    if (
        result.get('status') == 'completed'
        or runtime.get('status') == 'completed'
    ):
        save_state('whatsapp_product_completed', None)

        completion_message = _product_builder_completion_response(runtime)

        return '\n\n'.join(
            part for part in (
                unrelated_reply,
                completion_message,
            ) if part
        ) or None

    # STEP 8: Handle rejected Builder answers.
    rejected = result.get('rejected') or []

    if rejected:
        current_question = runtime.get('question') or question

        retry_message = (
            current_question.get('retry_message')
            or (runtime.get('snapshot') or {}).get('fallback_message')
        )

        prompt = _format_product_builder_question(runtime)

        return '\n\n'.join(
            part for part in (
                unrelated_reply,
                retry_message,
                prompt,
            ) if part
        ) or None

    # STEP 9: Return the separate answer together with the next
    # Builder question, or simply repeat the current question.
    prompt = (
        _format_product_builder_question(runtime)
        or (runtime.get('snapshot') or {}).get('fallback_message')
    )

    return '\n\n'.join(
        part for part in (
            unrelated_reply,
            prompt,
        ) if part
    ) or None


def search_whatsapp_products(
    text,
    organization,
    state=None,
    *,
    price_preference="any",
    min_price=None,
    max_price=None,
    specification_requirements=None,
):
    """Delegate tenant catalogue discovery and presentation to Products."""
    from products.services.whatsapp_discovery import (
        search_and_prepare_whatsapp_product,
    )
    return search_and_prepare_whatsapp_product(
        text,
        organization,
        state,
        price_preference=price_preference,
        min_price=min_price,
        max_price=max_price,
        specification_requirements=specification_requirements,
    )


def update_conversation_state(state, current_step=None, waiting_for='__UNCHANGED__', data=None):
    """
    Update the conversation state and save it.

    waiting_for behavior:
    - "__UNCHANGED__" = keep the existing value
    - None = clear the value
    - any other value = set the value
    """
    if current_step is not None:
        state.current_step = current_step
    if waiting_for != '__UNCHANGED__':
        state.waiting_for = waiting_for
    if data is not None:
        existing_data = state.data or {}
        existing_data.update(data)
        state.data = existing_data
    state.save()
    return state

def get_required_request_fields(category):
    from business_requests.services.whatsapp import get_required_request_fields as service
    return service(category)

def validate_request_field_value(field, text):
    from business_requests.services.whatsapp import validate_request_field_value as service
    return service(field, text)

def get_next_missing_request_field(category, collected_data):
    from business_requests.services.whatsapp import get_next_missing_request_field as service
    return service(category, collected_data)

def get_next_request_question(category, collected_data):
    from business_requests.services.whatsapp import get_next_request_question as service
    return service(category, collected_data)

def get_ai_general_interpretation(
        text, 
        organization, 
        state, 
        current_message_id, 
        *, 
        allow_product_builder=False,
        ):
    """
    Interpret general customer messages in an idle conversation,
    including after a product has been displayed.

    Active Builder questions and business-request workflows remain
    under their existing Django handlers. Rejections are logged with
    metadata only; customer text and AI answer content are never logged.
    """
    if not text or not organization or not state:
        logger.info(
            'WhatsApp general AI skipped: missing message, organization or state.'
        )
        return None
    if not _whatsapp_ai_is_enabled(organization):
        logger.info(
            'WhatsApp general AI skipped: AI is disabled for organization_id=%s.',
            getattr(organization, 'pk', None),
        )
        return None

    state_data = state.data if isinstance(state.data, dict) else {}
    builder_data = state_data.get('product_conversation')
    is_active_product_builder = (
        allow_product_builder
        and getattr(state, 'current_step', None) == 'whatsapp_product_builder'
        and bool(state_data.get('selected_whatsapp_product_id'))
        and isinstance(builder_data, dict)
        and builder_data.get('status') == 'in_progress'
    )
    skip_reasons = []
        
    if state_data.get('category'):
        skip_reasons.append('active_category')
    if state_data.get('business_request_id'):
        skip_reasons.append('active_business_request')
    if state_data.get('selected_whatsapp_product_id')and not is_active_product_builder:
        skip_reasons.append('selected_product')

    # A displayed product list is not a blocking business workflow.
    # The exact selection handler runs before this interpreter; if the
    # message is not a selection, general AI may handle the conversation.
    is_pending_product_selection = (
        getattr(state, 'current_step', None) == 'whatsapp_product_selection'
        and getattr(state, 'waiting_for', None) == 'product_selection'
        and isinstance(state_data.get('whatsapp_product_ids'), list)
        and bool(state_data.get('whatsapp_product_ids'))
    )

    if (
        getattr(state, 'waiting_for', None)
        and not is_pending_product_selection
        and not is_active_product_builder
    ):
        skip_reasons.append('waiting_for_input')
    if skip_reasons:
        logger.info(
            'WhatsApp general AI skipped: organization_id=%s reasons=%s.',
            organization.pk,
            ','.join(skip_reasons),
        )
        return None

    conversation = getattr(state, 'conversation', None)
    if conversation is None:
        logger.info(
            'WhatsApp general AI skipped: conversation missing; organization_id=%s.',
            organization.pk,
        )
        return None
    if getattr(conversation, 'organization_id', None) != organization.pk:
        logger.warning(
            'WhatsApp general AI skipped: organization mismatch; organization_id=%s.',
            organization.pk,
        )
        return None
    if getattr(conversation, 'business_request_id', None) or getattr(conversation, 'business_request', None):
        logger.info(
            'WhatsApp general AI skipped: active business request; organization_id=%s.',
            organization.pk,
        )
        return None
    
    allowed_steps = {None, 'whatsapp_product_completed'}
    if is_pending_product_selection:
        allowed_steps.add('whatsapp_product_selection')
    if is_active_product_builder:
        allowed_steps.add('whatsapp_product_builder')


    if getattr(state, 'current_step', None) not in allowed_steps:
        logger.info(
            'WhatsApp general AI skipped: unsupported current_step=%s organization_id=%s.',
            getattr(state, 'current_step', None),
            organization.pk,
        )
        return None

    try:
        from .ai_service import interpret_general_message
        result = interpret_general_message(
            text,
            organization,
            state,
            current_message_id=current_message_id,
        )

        if not isinstance(result, dict):
            logger.warning(
                'WhatsApp general AI rejected result: expected dict, received %s; organization_id=%s.',
                type(result).__name__,
                organization.pk,
            )
            return None

        action = result.get('action')
        intent = result.get('intent')
        answer = result.get('answer')
        language = result.get('language', 'sw')

        # Log classification metadata before applying Django's allow-list.
        logger.info(
            'WhatsApp general AI raw classification: organization_id=%s '
            'action=%s intent=%s language=%s answer_type=%s answer_length=%s keys=%s.',
            organization.pk,
            action,
            intent,
            language,
            type(answer).__name__,
            len(answer) if isinstance(answer, str) else -1,
            ','.join(sorted(str(key) for key in result.keys())),
        )

        if action == 'reply':
            if intent not in {'greeting', 'general_enquiry', 'unclear'}:
                logger.warning(
                    'WhatsApp general AI rejected reply: unsupported reply intent=%s organization_id=%s.',
                    intent,
                    organization.pk,
                )
                return None
            if not isinstance(answer, str):
                logger.warning(
                    'WhatsApp general AI rejected reply: answer is not text; organization_id=%s.',
                    organization.pk,
                )
                return None
            answer = answer.strip()
            if not answer or len(answer) > 1000:
                logger.warning(
                    'WhatsApp general AI rejected reply: empty or oversized answer; '
                    'organization_id=%s answer_length=%s.',
                    organization.pk,
                    len(answer),
                )
                return None
        elif action == 'route_existing':
            if allow_product_builder:
                logger.info(
                    'WhatsApp Builder general AI rejected workflow routing: '
                    'organization_id=%s intent=%s.',
                    organization.pk,
                    intent,
                )
                return None


            if intent not in {'product_enquiry', 'service_enquiry', 'business_request', 'human_support', 'workflow_input'}:
                logger.warning(
                    'WhatsApp general AI rejected route: unsupported route intent=%s organization_id=%s.',
                    intent,
                    organization.pk,
                )
                return None
            if answer != '':
                logger.warning(
                    'WhatsApp general AI rejected route: route answer must be empty; '
                    'organization_id=%s answer_type=%s answer_length=%s.',
                    organization.pk,
                    type(answer).__name__,
                    len(answer) if isinstance(answer, str) else -1,
                )
                return None
        else:
            logger.warning(
                'WhatsApp general AI rejected result: unsupported action=%s intent=%s organization_id=%s.',
                action,
                intent,
                organization.pk,
            )
            return None

        return {
            'action': action,
            'intent': intent,
            'answer': answer,
            'language': language,
        }

    except Exception:
        logger.exception(
            'General WhatsApp AI interpretation failed: organization_id=%s.',
            getattr(organization, 'pk', None),
        )
        return None

def _human_handover_acknowledgement(language='sw', organization=None):
    """Return the organization's configured human-handover acknowledgement."""
    if not isinstance(language, str):
        organization, language = language, 'sw'
    language_key = 'mixed' if str(language or '').lower().startswith('mixed') else (
        'en' if str(language or '').lower().startswith('en') else 'sw'
    )
    return _get_configured_whatsapp_message(
        organization,
        'human_handover',
        language_key,
    )


def _detect_explicit_human_support_language(text, organization=None):
    """Detect configured explicit human-support phrases for the organization."""
    if not text or not organization:
        return None
    from business_requests.whatsapp_config import get_whatsapp_language_phrases
    configured = get_whatsapp_language_phrases(
        organization,
        'human_handover_phrases',
    )
    normalized = re.sub(r'[^\w\s]', ' ', str(text).casefold())
    normalized = ' '.join(normalized.split())
    for language in ('sw', 'en'):
        if any(phrase in normalized for phrase in configured.get(language, [])):
            return language
    return None

def get_ai_human_support_language(text, organization, state, current_message_id):
    """Detect human-support requests using rules first, then AI."""
    if not text or not organization or (not state):
        return None
    conversation = getattr(state, 'conversation', None)
    if conversation is None or getattr(conversation, 'organization_id', None) != organization.pk:
        return None
    detected_language = _detect_explicit_human_support_language(text, organization)
    if detected_language:
        return detected_language
    if not _whatsapp_ai_is_enabled(organization):
        return None
    try:
        from .ai_service import interpret_general_message
        result = interpret_general_message(text, organization, state, current_message_id=current_message_id)
        if not (isinstance(result, dict) and result.get('action') == 'route_existing' and (result.get('intent') == 'human_support') and (result.get('answer') == '')):
            return None
        language = result.get('language', 'sw')
        return language if language in {'sw', 'en', 'mixed'} else 'sw'
    except Exception:
        import logging
        logging.getLogger(__name__).exception('WhatsApp human-support intent interpretation failed.')
        return None

def get_ai_human_support_intent(text, organization, state, current_message_id):
    """Keep the existing Boolean helper interface for compatibility."""
    return get_ai_human_support_language(text, organization, state, current_message_id) is not None

def get_ai_general_reply(text, organization, state, current_message_id):
    """Backward-compatible helper for callers expecting a reply only."""
    result = get_ai_general_interpretation(text, organization, state, current_message_id)
    if result and result.get('action') == 'reply':
        return result['answer']
    return None


def get_ai_product_discovery_reply(text, organization, state, current_message_id):
    """
    Use AI to interpret a new product request or resume a pending
    product clarification. Django performs and validates the actual search.
    """
    if not text or not organization or not state:
        return None

    if not _whatsapp_ai_is_enabled(organization):
        return None

    state_data = state.data if isinstance(state.data, dict) else {}
    discovery_state = state_data.get('whatsapp_product_discovery')

    pending_discovery = (
        isinstance(discovery_state, dict)
        and discovery_state.get('status') == 'awaiting_clarification'
        and state.current_step == 'whatsapp_product_discovery'
        and state.waiting_for == 'product_discovery_clarification'
        and isinstance(discovery_state.get('original_request'), str)
        and bool(discovery_state.get('original_request').strip())
    )

    # Do not intercept an active product selection or another workflow.
    if (
        state_data.get('selected_whatsapp_product_id')
        or state_data.get('category')
        or state_data.get('business_request_id')
        or (
            getattr(state, 'waiting_for', None)
            and not pending_discovery
        )
    ):
        return None

    conversation = getattr(state, 'conversation', None)

    if conversation is None:
        return None

    if (
        getattr(conversation, 'business_request_id', None)
        or getattr(conversation, 'business_request', None)
    ):
        return None

    current_step = getattr(state, 'current_step', None)

    if current_step not in {
        None,
        'whatsapp_product_completed',
        'whatsapp_product_discovery',
    }:
        return None

    if (
        current_step == 'whatsapp_product_discovery'
        and not pending_discovery
    ):
        return None

    try:
        from .ai_service import interpret_product_discovery

        result = interpret_product_discovery(
            text,
            organization,
            state,
            current_message_id=current_message_id,
            discovery_context=(
                discovery_state if pending_discovery else None
            ),
        )

        if not isinstance(result, dict):
            return None

        action = result.get('action')

        if action == 'clarify':
            clarification = result.get('clarification')

            if (
                not isinstance(clarification, str)
                or not clarification.strip()
                or len(clarification.strip()) > 500
            ):
                return None

            state_data = dict(state.data or {})

            original_request = (
                discovery_state.get('original_request')
                if pending_discovery
                else text.strip()
            )

            previous_requirements = (
                discovery_state.get('requirements', {})
                if pending_discovery and isinstance(discovery_state.get('requirements'), dict)
                else {}
            )
            requirements = dict(previous_requirements)
            requirements.update({
                'price_preference': result.get('price_preference', requirements.get('price_preference', 'any')),
                'min_price': str(result['min_price']) if result.get('min_price') is not None else None,
                'max_price': str(result['max_price']) if result.get('max_price') is not None else None,
                'specification_requirements': result.get('specification_requirements', requirements.get('specification_requirements', [])),
            })
            state_data['whatsapp_product_discovery'] = {
                'status': 'awaiting_clarification',
                'original_request': original_request,
                'clarification_question': clarification.strip(),
                'requirements': requirements,
            }

            state.data = state_data
            state.current_step = 'whatsapp_product_discovery'
            state.waiting_for = 'product_discovery_clarification'

            state.save(
                update_fields=[
                    'data',
                    'current_step',
                    'waiting_for',
                    'updated_at',
                ]
            )

            return {
                'reply': clarification.strip(),
                'product_reply': None,
            }

        if action == 'search':
            search_query = result.get('search_query')

            if (
                not isinstance(search_query, str)
                or not search_query.strip()
                or len(search_query.strip()) > 300
            ):
                return None

            price_preference = result.get('price_preference', 'any')
            search_options = {
                'price_preference': price_preference,
                'min_price': result.get('min_price'),
                'max_price': result.get('max_price'),
                'specification_requirements': result.get('specification_requirements', []),
            }
            product_reply = search_whatsapp_products(
                search_query.strip(), organization, state, **search_options,
            )

            if product_reply:
                return {
                    'reply': product_reply,
                    'product_reply': product_reply,
                }

            return None

        return None

    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            'Product discovery AI failed; using existing fallback.'
        )
        return None

def get_ai_request_category_reply(text, organization, state, current_message_id=None):
    """
    Ask AI to interpret a new request only when the WhatsApp
    conversation is genuinely idle.

    Django validates the returned category against the current
    organization's active RequestCategory records.
    """
    if not text or not organization or (not state):
        return None
    if not _whatsapp_ai_is_enabled(organization):
        return None
    state_data = state.data if isinstance(state.data, dict) else {}
    if state_data.get('category'):
        return None
    if state_data.get('business_request_id'):
        return None
    if state_data.get('selected_whatsapp_product_id'):
        return None
    if state_data.get('whatsapp_product_ids'):
        return None
    if getattr(state, 'waiting_for', None):
        return None
    conversation = getattr(state, 'conversation', None)
    if conversation is None:
        return None
    if getattr(conversation, 'organization_id', None) != organization.pk:
        return None
    if getattr(conversation, 'business_request_id', None):
        return None
    if getattr(conversation, 'business_request', None):
        return None
    allowed_steps = {None, 'whatsapp_product_completed'}
    if getattr(state, 'current_step', None) not in allowed_steps:
        return None
    try:
        from .ai_service import interpret_request_category
        category_records = list(RequestCategory.objects.filter(organization=organization, is_active=True).order_by('name')[:31])
        if not category_records or len(category_records) > 30:
            return None
        candidates = [{'id': item.pk, 'name': item.name} for item in category_records]
        result = interpret_request_category(text, organization, state, candidates, current_message_id=current_message_id)
        if not isinstance(result, dict):
            return None
        action = result.get('action')
        if action == 'clarify':
            clarification = result.get('clarification')
            if isinstance(clarification, str) and clarification.strip() and (len(clarification.strip()) <= 500):
                return {'category': None, 'clarification': clarification.strip()}
            return None
        if action != 'match':
            return None
        category_id = result.get('category_id')
        if isinstance(category_id, bool) or not isinstance(category_id, int):
            return None
        category = RequestCategory.objects.filter(pk=category_id, organization=organization, is_active=True).first()
        if not category:
            return None
        if category.department_id and category.department.organization_id != organization.pk:
            return None
        return {'category': category, 'clarification': None}
    except Exception:
        import logging
        logging.getLogger(__name__).exception('WhatsApp AI category interpretation failed; using existing category routing.')
        return None

def _format_whatsapp_product_json(value, depth=0):
    """Compatibility wrapper for safe product-data formatting."""
    from products.services.public_data import (
        clean_public_product_data,
        format_public_product_json,
    )
    return format_public_product_json(
        clean_public_product_data(value),
        depth=depth,
    )
