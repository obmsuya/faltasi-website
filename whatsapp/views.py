from unicodedata import category

from django.db.migrations import state
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import text, timezone

import json
import requests
import re

from .models import (
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    WhatsAppConnection,
    Conversation,
    ConversationState,
    Message,
)
from customers.models import Customer
from business_requests.models import (
    BusinessRequest,
    RequestCategory,
    RequestAssignment,
    WorkflowStep,
)

def find_request_category(text):
    """
    Identify a RequestCategory using keywords stored
    in the Django database.

    Categories and keywords are managed through
    Django Admin.
    """
    if not text:
        return None
    message = text.lower().strip()
    categories = RequestCategory.objects.filter(is_active=True).order_by('name')
    best_category = None
    best_score = 0
    for category in categories:
        if not category.keywords:
            continue
        keywords = [keyword.strip().lower() for keyword in category.keywords.split(',') if keyword.strip()]
        score = 0
        for keyword in keywords:
            if keyword in message:
                score += 1
        if score > best_score:
            best_score = score
            best_category = category
    if best_category:
        print('CATEGORY IDENTIFIED:', best_category.name, '| SCORE:', best_score)
    else:
        print('NO REQUEST CATEGORY IDENTIFIED')
    return best_category

def send_whatsapp_message(whatsapp_phone, phone_number, message):
    """
    Send a WhatsApp text message.

    Multi-tenant routing:
    - The WhatsApp phone number determines the organization.
    - If that organization's connection has a token, use it.
    - During development, fall back to the platform .env token.
    """

    try:
        # Find the connection belonging to this WhatsApp phone
        connection = (
            WhatsAppConnection.objects
            .select_related(
                "whatsapp_business_account",
                "organization",
            )
            .filter(
                whatsapp_business_account=whatsapp_phone.whatsapp_business_account,
                organization=whatsapp_phone.organization,
                status="connected",
            )
            .first()
        )

        if not connection:
            print("========== WHATSAPP SEND ERROR ==========")
            print("NO ACTIVE WHATSAPP CONNECTION FOUND")
            print("ORGANIZATION:", whatsapp_phone.organization.name)
            print("PHONE NUMBER:", whatsapp_phone.phone_number)
            return None

        # First try the business connection token.
        # If it is not available, temporarily use the platform
        # environment token for development.
        access_token = connection.access_token

        if not access_token:
            print("BUSINESS ACCESS TOKEN NOT STORED")
            print("USING PLATFORM DEVELOPMENT TOKEN")

            access_token = settings.WHATSAPP_ACCESS_TOKEN

        if not access_token:
            print("========== WHATSAPP SEND ERROR ==========")
            print("NO WHATSAPP ACCESS TOKEN AVAILABLE")
            return None

        # The phone number ID always comes from the
        # WhatsApp phone record belonging to this organization.
        phone_number_id = whatsapp_phone.phone_number_id

        if not phone_number_id:
            print("========== WHATSAPP SEND ERROR ==========")
            print("WHATSAPP PHONE NUMBER ID NOT AVAILABLE")
            print("ORGANIZATION:", whatsapp_phone.organization.name)
            return None

        # Meta WhatsApp Cloud API endpoint
        url = (
            f"https://graph.facebook.com/v26.0/"
            f"{phone_number_id}/messages"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {
                "body": message
            },
        }

        print("========== WHATSAPP SEND ==========")
        print("ORGANIZATION:", whatsapp_phone.organization.name)
        print("WHATSAPP PHONE:", whatsapp_phone.phone_number)
        print("PHONE NUMBER ID:", phone_number_id)
        print("RECIPIENT:", phone_number)
        print("TOKEN AVAILABLE:", bool(access_token))
        print("API URL:", url)
        print("MESSAGE:", message)

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        print("WHATSAPP SEND STATUS:", response.status_code)
        print("WHATSAPP SEND RESPONSE:", response.text)

        if response.status_code == 200:
            return response

        return None

    except requests.RequestException as e:
        print("========== WHATSAPP SEND REQUEST ERROR ==========")
        print("ERROR:", str(e))
        return None

    except Exception as e:
        print("========== WHATSAPP SEND ERROR ==========")
        print("ERROR:", str(e))
        return None
def get_or_create_customer(phone_number):
    """
    Find an existing customer by WhatsApp phone number.
    If none exists, create a basic customer record.
    """

    customer = Customer.objects.filter(
        phone=phone_number
    ).first()

    if customer:
        return customer

    customer = Customer.objects.create(
        phone=phone_number,
        name="WhatsApp Customer",
        customer_type="individual",
        preferred_contact_method="whatsapp",
        status="active",
    )

    print("NEW CUSTOMER CREATED:", customer)

    return customer

def get_or_create_conversation_state(conversation):
    """
    Get the ConversationState for a conversation.
    Create it if it does not exist.
    """
    state, created = ConversationState.objects.get_or_create(conversation=conversation)
    if created:
        print('CONVERSATION STATE CREATED:', state)
    else:
        print('CONVERSATION STATE FOUND:', state)
    return state

def create_business_request(customer, text, category, conversation=None):
    """
    Create or reuse a BusinessRequest for a WhatsApp conversation.

    A conversation should have one active BusinessRequest.
    """
    if not category:
        print('NO REQUEST CATEGORY IDENTIFIED')
        return None
    if conversation and conversation.business_request:
        business_request = conversation.business_request
        print('EXISTING CONVERSATION REQUEST FOUND:', business_request)
        return business_request
    business_request = BusinessRequest.objects.create(customer=customer, request_text=text, subject=category.name, category=category, department=category.department, status='new', priority='normal', source='whatsapp')
    print('BUSINESS REQUEST CREATED:', business_request)
    return business_request

def get_whatsapp_phone_number(phone_number_id):
    """
    Find the WhatsApp phone number configuration from
    Meta's phone_number_id.
    """

    if not phone_number_id:
        print("NO WHATSAPP PHONE NUMBER ID FOUND")
        return None

    try:
        whatsapp_phone = (
            WhatsAppPhoneNumber.objects
            .select_related(
                "organization",
                "whatsapp_business_account",
            )
            .get(
                phone_number_id=phone_number_id,
                is_active=True,
            )
        )

        print("WHATSAPP PHONE FOUND:", whatsapp_phone)
        print("ORGANIZATION:", whatsapp_phone.organization)
        print(
            "WABA:",
            whatsapp_phone.whatsapp_business_account,
        )

        return whatsapp_phone

    except WhatsAppPhoneNumber.DoesNotExist:

        print(
            "NO WHATSAPP PHONE CONFIGURED FOR PHONE NUMBER ID:",
            phone_number_id,
        )

        return None

    except WhatsAppPhoneNumber.MultipleObjectsReturned:

        print(
            "ERROR: MULTIPLE WHATSAPP PHONES FOUND FOR PHONE NUMBER ID:",
            phone_number_id,
        )

        return None

def is_new_request_message(
    text,
    current_category=None,
    current_field=None
):
    """
    Determine whether an incoming message appears to start
    a new business request instead of answering the current question.

    The function is intentionally conservative.

    Important behavior:
    - If there is no active request, a detected category starts a new request.
    - If the detected category is the same as the current category,
      continue the current request.
    - If the customer is answering a text field, continue the current request.
    - Location, address, name, email, phone, and other field answers
      should not easily be interpreted as new requests.
    - A new request requires stronger evidence.
    """

    if not text or not text.strip():
        return False

    normalized = text.lower().strip()

    detected_category = find_request_category(text)

    # -----------------------------------------------------
    # No detected category
    #
    # Without a category, we normally cannot confidently say
    # that the customer is starting a new request.
    # -----------------------------------------------------

    if not detected_category:
        return False

    # -----------------------------------------------------
    # No active category
    #
    # If there is no current request and we detected a
    # category, this is a new request.
    # -----------------------------------------------------

    if not current_category:
        return True

    # -----------------------------------------------------
    # Same category
    #
    # The customer is most likely continuing the current
    # request.
    # -----------------------------------------------------

    if detected_category.id == current_category.id:
        return False

    # -----------------------------------------------------
    # If we are currently collecting a field, be conservative.
    #
    # A customer can mention another product/service while
    # answering a field. We should not immediately create
    # another request unless there is strong evidence.
    # -----------------------------------------------------

    if current_field:

        # -------------------------------------------------
        # Text fields
        # -------------------------------------------------

        if current_field.field_type == "text":
            return False

        # -------------------------------------------------
        # Location/address fields
        #
        # Location answers can contain many words and may
        # accidentally contain category keywords.
        # -------------------------------------------------

        field_name = (
            getattr(current_field, "name", None)
            or getattr(current_field, "field_name", None)
            or getattr(current_field, "key", None)
            or ""
        )

        field_name_normalized = field_name.lower().strip()

        location_keywords = [
            "location",
            "address",
            "area",
            "city",
            "region",
            "place",
            "where",
        ]

        if any(
            keyword in field_name_normalized
            for keyword in location_keywords
        ):
            return False

        # -------------------------------------------------
        # Validate the current field.
        # -------------------------------------------------

        valid, cleaned_value = (
            validate_request_field_value(
                current_field,
                text
            )
        )

        print(
            "NEW REQUEST FIELD VALIDATION:",
            valid,
            cleaned_value
        )

        # If the customer provided a valid answer to the
        # current field, it is NOT a new request.
        if valid:
            return False

    # -----------------------------------------------------
    # Strong phrases indicating a NEW request
    # -----------------------------------------------------

    explicit_new_request_phrases = [
        "i also need",
        "i also want",
        "i also would like",
        "i'd also like",
        "i would also like",

        "i need another",
        "i want another",

        "another request",
        "another service",
        "another product",

        "different request",
        "different service",
        "different product",

        "actually i need",
        "actually i want",
        "actually i would like",
        "actually i'd like",

        "by the way i need",
        "by the way i want",
        "by the way i'd like",

        "can you also provide",
        "can you also help",

        "i need a separate",
        "i want a separate",
    ]

    if any(
        phrase in normalized
        for phrase in explicit_new_request_phrases
    ):
        return True

    # -----------------------------------------------------
    # Strong request language
    #
    # Only use this when the customer has NOT successfully
    # answered the current field.
    # -----------------------------------------------------

    request_phrases = [
        "i need",
        "i want",
        "i would like",
        "i'd like",
        "looking for",
        "can you provide",
        "can you help",
        "quotation for",
        "quote for",
    ]

    if any(
        phrase in normalized
        for phrase in request_phrases
    ):
        return True

    # -----------------------------------------------------
    # Default
    #
    # Continue the current request unless there is strong
    # evidence that the customer started another request.
    # -----------------------------------------------------

    return False
def process_request_fields(category, state, text):
    """
    Handle category-specific questions using RequestField
    and ConversationState.
    """
    collected_data = state.data or {}
    waiting_for = state.waiting_for
    if waiting_for:
        try:
            field = category.request_fields.get(name=waiting_for, is_active=True)
        except Exception:
            field = None
        if field:
            if not field.is_required:
                normalized = text.lower().strip()
                skip_values = ['no', 'no budget', "i don't know", 'i dont know', 'not sure', 'not certain', 'no idea', 'i have no idea', "don't have a budget", 'dont have a budget', "i don't have a budget", 'i dont have a budget', 'not decided', 'not decided yet']
                if normalized in skip_values:
                    collected_data[waiting_for] = None
                    update_conversation_state(state, data=collected_data)
                else:
                    valid, cleaned_value = validate_request_field_value(field, text)
                    if valid:
                        collected_data[waiting_for] = cleaned_value
                        update_conversation_state(state, data=collected_data)
                    else:
                        return f'I’m sorry, I didn’t quite understand that.\n\n{field.question}'
            else:
                valid, cleaned_value = validate_request_field_value(field, text)
                if not valid:
                    return f'I’m sorry, I didn’t quite understand that answer.\n\n{field.question}'
                collected_data[waiting_for] = cleaned_value
                update_conversation_state(state, data=collected_data)
    next_field = get_next_missing_request_field(category, collected_data)
    if next_field:
        update_conversation_state(state, current_step='collecting_details', waiting_for=next_field.name, data=collected_data)
        return next_field.question
    update_conversation_state(state, current_step='details_collected', waiting_for=None, data=collected_data)
    return 'Thank you. We now have the information we need. Our team will review your request and get back to you shortly.'

def update_business_request_details(business_request, state):
    """
    Add the customer's collected conversation details
    to the BusinessRequest.
    """

    if not business_request or not state:
        return business_request

    collected_data = state.data or {}

    if not collected_data:
        return business_request

    # Keep the original customer request
    original_request = collected_data.get("request_text")

    if not original_request:
        original_request = business_request.request_text

    # Build a readable summary
    details = []

    for field_name, value in collected_data.items():

        # Don't display internal conversation values
        if field_name in [
            "request_text",
            "category",
            "business_request_id",
        ]:
            continue

        # Convert internal values into human-readable values
        display_value = value

        if value is True:
            display_value = "Yes"
        elif value is False:
            display_value = "No"
        elif value is None:
            display_value = "Not provided"

        details.append(
            f"{field_name.replace('_', ' ').title()}: {display_value}"
        )

    if details:
        business_request.request_text = (
            f"{original_request}\n\n"
            "Collected Details:\n"
            + "\n".join(details)
        )

        business_request.save(
            update_fields=["request_text", "updated_at"]
        )

    print(
        "BUSINESS REQUEST UPDATED WITH DETAILS:",
        business_request
    )

    return business_request

def create_request_workflow(business_request):
    """
    Create the initial internal workflow for a completed
    WhatsApp business request.

    The request is assigned to its department first.
    An individual staff member is NOT automatically selected.

    This function is safe to call multiple times because it
    checks for existing current assignments and workflow steps.
    """

    if not business_request:
        print("NO BUSINESS REQUEST FOR WORKFLOW")
        return business_request

    department = business_request.department

    if not department:
        print(
            "NO DEPARTMENT ASSIGNED TO BUSINESS REQUEST:",
            business_request.id
        )
        return business_request

    print("========== CREATE REQUEST WORKFLOW ==========")
    print("BUSINESS REQUEST:", business_request.id)
    print("DEPARTMENT:", department)

    # =========================================================
    # CREATE DEPARTMENT ASSIGNMENT
    # =========================================================

    assignment = (
        RequestAssignment.objects
        .filter(
            request=business_request,
            is_current=True,
        )
        .first()
    )

    if assignment:
        print(
            "EXISTING CURRENT ASSIGNMENT:",
            assignment.id
        )
    else:
        assignment = RequestAssignment.objects.create(
            request=business_request,
            assigned_to=None,
            department=department,
            is_current=True,
            notes="Automatically routed to department after WhatsApp details were collected.",
        )

        print(
            "REQUEST ASSIGNMENT CREATED:",
            assignment.id
        )

    # =========================================================
    # CREATE INITIAL WORKFLOW STEP
    # =========================================================

    workflow_step = (
        WorkflowStep.objects
        .filter(
            request=business_request,
            name="Department Review",
        )
        .first()
    )

    if workflow_step:
        print(
            "EXISTING WORKFLOW STEP:",
            workflow_step.id
        )
    else:
        workflow_step = WorkflowStep.objects.create(
            request=business_request,
            name="Department Review",
            description=(
                "Review the customer's request, verify the collected "
                "information, and assign the request to an appropriate "
                "staff member."
            ),
            step_order=1,
            status="active",
            assigned_to=None,
        )

        print(
            "WORKFLOW STEP CREATED:",
            workflow_step.id
        )

    # =========================================================
    # KEEP REQUEST NEW UNTIL A STAFF MEMBER IS ASSIGNED
    # =========================================================

    if business_request.status != "new":
        business_request.status = "new"
        business_request.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    print(
        "REQUEST WORKFLOW READY:",
        business_request.id
    )

    return business_request
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

    # =====================================================
    # META WEBHOOK VERIFICATION
    # =====================================================

    if request.method == "GET":

        verify_token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        print("VERIFY TOKEN RECEIVED")
        print("CHALLENGE:", challenge)

        if verify_token and challenge:

            if verify_token == settings.WHATSAPP_VERIFY_TOKEN:

                print("VERIFICATION SUCCESS")

                return HttpResponse(challenge)

            print("VERIFICATION FAILED")

            return HttpResponse(
                "Invalid verify token",
                status=403,
            )

        return HttpResponse("OK", status=200)

    # =====================================================
    # ONLY POST REQUESTS ARE ACCEPTED
    # =====================================================

    if request.method != "POST":
        return HttpResponse(status=405)

    print("========== WHATSAPP POST RECEIVED ==========")

    try:

        # =================================================
        # READ REQUEST BODY
        # =================================================

        body = request.body.decode(
            "utf-8",
            errors="replace",
        )

        print("WEBHOOK BODY RECEIVED")

        data = json.loads(body)

        print(
            "WEBHOOK JSON:",
            json.dumps(
                data,
                indent=2,
            ),
        )

        # =================================================
        # READ WEBHOOK STRUCTURE
        # =================================================

        entry = data.get("entry", [])

        if not entry:

            print("NO WEBHOOK ENTRY FOUND")

            return JsonResponse({
                "status": "ok",
            })

        changes = entry[0].get("changes", [])

        if not changes:

            print("NO WEBHOOK CHANGES FOUND")

            return JsonResponse({
                "status": "ok",
            })

        value = changes[0].get("value", {})

        # =================================================
        # IDENTIFY THE WHATSAPP PHONE NUMBER
        # =================================================
        #
        # Meta tells us which business phone number
        # received the message.
        #
        # This is the key to multi-business routing.
        # =================================================

        metadata = value.get("metadata", {})

        phone_number_id = metadata.get(
            "phone_number_id"
        )

        print(
            "META PHONE NUMBER ID:",
            phone_number_id,
        )

        if not phone_number_id:

            print(
                "NO PHONE NUMBER ID FOUND IN WEBHOOK"
            )

            return JsonResponse({
                "status": "ok",
                "message": "No phone number ID found",
            })

        # =================================================
        # FIND THE WHATSAPP PHONE NUMBER IN OUR DATABASE
        # =================================================

        try:

            whatsapp_phone = (
                WhatsAppPhoneNumber.objects
                .select_related(
                    "organization",
                    "whatsapp_business_account",
                )
                .get(
                    phone_number_id=phone_number_id,
                    is_active=True,
                )
            )

        except WhatsAppPhoneNumber.DoesNotExist:

            print(
                "UNKNOWN WHATSAPP PHONE NUMBER:",
                phone_number_id,
            )

            return JsonResponse({
                "status": "ok",
                "message": "Unknown WhatsApp phone number",
            })

        except WhatsAppPhoneNumber.MultipleObjectsReturned:

            print(
                "MULTIPLE WHATSAPP PHONE NUMBERS FOUND:",
                phone_number_id,
            )

            return JsonResponse({
                "status": "ok",
                "message": "Multiple WhatsApp phone numbers found",
            })

        # =================================================
        # IDENTIFY ORGANIZATION
        # =================================================

        organization = whatsapp_phone.organization

        whatsapp_business_account = (
            whatsapp_phone.whatsapp_business_account
        )

        print(
            "WHATSAPP PHONE:",
            whatsapp_phone,
        )

        print(
            "ORGANIZATION:",
            organization,
        )

        print(
            "WHATSAPP BUSINESS ACCOUNT:",
            whatsapp_business_account,
        )

        # =================================================
        # GET MESSAGES
        # =================================================

        messages = value.get("messages", [])

        if not messages:

            print(
                "NO WHATSAPP MESSAGE FOUND"
            )

            # This can happen for status updates.
            # We will build status processing later.

            return JsonResponse({
                "status": "ok",
            })

        # =================================================
        # PROCESS FIRST MESSAGE
        # =================================================

        message = messages[0]

        whatsapp_message_id = message.get("id")

        print(
            "WHATSAPP MESSAGE ID:",
            whatsapp_message_id,
        )

        # =================================================
        # DUPLICATE MESSAGE PROTECTION
        # =================================================

        if whatsapp_message_id:

            existing_message = (
                Message.objects.filter(
                    whatsapp_message_id=whatsapp_message_id
                ).first()
            )

            if existing_message:

                print(
                    "DUPLICATE MESSAGE IGNORED:",
                    whatsapp_message_id,
                )

                return JsonResponse({
                    "status": "ok",
                    "duplicate": True,
                })

        # =================================================
        # MESSAGE INFORMATION
        # =================================================

        sender = message.get("from")

        message_type = message.get("type")

        print(
            "SENDER:",
            sender,
        )

        print(
            "MESSAGE TYPE:",
            message_type,
        )

        # =================================================
        # CURRENT SYSTEM SUPPORTS TEXT MESSAGES
        # =================================================

        if message_type != "text":

            print(
                "NON-TEXT MESSAGE RECEIVED:",
                message_type,
            )

            return JsonResponse({
                "status": "ok",
                "message": "Non-text message received",
            })

        # =================================================
        # GET TEXT
        # =================================================

        text = (
            message
            .get("text", {})
            .get("body", "")
            .strip()
        )

        print(
            "MESSAGE TEXT:",
            text,
        )

        if not sender:

            print(
                "NO SENDER FOUND"
            )

            return JsonResponse({
                "status": "ok",
            })

        if not text:

            print(
                "EMPTY TEXT MESSAGE"
            )

            return JsonResponse({
                "status": "ok",
            })

        # =================================================
        # FIND OR CREATE CUSTOMER
        # =================================================
        #
        # IMPORTANT:
        # Customer is now scoped to the organization.
        #
        # The same phone number can therefore exist as a
        # customer for different businesses without mixing
        # their records.
        # =================================================

        customer = (
            Customer.objects
            .filter(
                organization=organization,
                phone=sender,
            )
            .first()
        )

        if customer:

            print(
                "EXISTING CUSTOMER:",
                customer,
            )

        else:

            customer = Customer.objects.create(
                organization=organization,
                phone=sender,
                name="WhatsApp Customer",
                customer_type="individual",
                preferred_contact_method="whatsapp",
                status="active",
            )

            print(
                "NEW CUSTOMER CREATED:",
                customer,
            )

        # =================================================
        # FIND ACTIVE CONVERSATION
        # =================================================

        conversation = (
            Conversation.objects
            .filter(
                organization=organization,
                whatsapp_phone_number=whatsapp_phone,
                customer=customer,
                phone_number=sender,
                status="active",
            )
            .first()
        )

        # =================================================
        # CREATE CONVERSATION IF NEEDED
        # =================================================

        if not conversation:

            conversation = Conversation.objects.create(
                organization=organization,
                whatsapp_phone_number=whatsapp_phone,
                customer=customer,
                phone_number=sender,
                whatsapp_user_id=sender,
                status="active",
            )

            print(
                "NEW CONVERSATION CREATED:",
                conversation,
            )

        else:

            print(
                "EXISTING CONVERSATION:",
                conversation,
            )

        # =================================================
        # GET OR CREATE CONVERSATION STATE
        # =================================================

        state = get_or_create_conversation_state(
            conversation
        )

        print(
            "CURRENT STEP:",
            state.current_step,
        )

        print(
            "WAITING FOR:",
            state.waiting_for,
        )

        print(
            "STATE DATA:",
            state.data,
        )

        # =================================================
        # SAVE INCOMING MESSAGE
        # =================================================

        incoming_message = Message.objects.create(
            organization=organization,
            conversation=conversation,
            direction="incoming",
            sender_type="customer",
            message_type=message_type,
            content=text,
            delivery_status="delivered",
            whatsapp_message_id=whatsapp_message_id,
            metadata=message,
        )

        print(
            "INCOMING MESSAGE SAVED:",
            incoming_message,
        )

        # Update conversation activity timestamp
        conversation.save(
            update_fields=[
                "last_message_at",
            ]
        )

        # =================================================
        # GET CURRENT STATE DATA
        # =================================================

        state_data = state.data or {}

        stored_category_name = (
            state_data.get("category")
        )

        current_category = None

        # =================================================
        # RESTORE CURRENT CATEGORY
        # =================================================

        if stored_category_name:

            try:

                current_category = (
                    RequestCategory.objects.get(
                        name=stored_category_name,
                        is_active=True,
                    )
                )

                print(
                    "CURRENT CATEGORY RESTORED:",
                    current_category,
                )

            except RequestCategory.DoesNotExist:

                current_category = None

                print(
                    "STORED CATEGORY NO LONGER EXISTS"
                )

        # =================================================
        # DETECT CATEGORY FROM NEW MESSAGE
        # =================================================

        detected_category = find_request_category(
            text
        )

        print(
            "DETECTED CATEGORY:",
            detected_category,
        )

        # =================================================
        # IDENTIFY CURRENT REQUEST FIELD
        # =================================================

        current_field = None

        if current_category and state.waiting_for:

            try:

                current_field = (
                    current_category
                    .request_fields
                    .get(
                        name=state.waiting_for,
                        is_active=True,
                    )
                )

                print(
                    "CURRENT FIELD:",
                    current_field,
                )

            except Exception:

                current_field = None

                print(
                    "CURRENT FIELD NOT FOUND:",
                    state.waiting_for,
                )

        # =================================================
        # DETERMINE WHETHER MESSAGE STARTS NEW REQUEST
        # =================================================

        new_request = False

        # -------------------------------------------------
        # CASE 1:
        # No current category.
        # -------------------------------------------------

        if not current_category:

            if detected_category:

                new_request = True

                print(
                    "NEW REQUEST DETECTED - "
                    "NO CURRENT CATEGORY"
                )

        # -------------------------------------------------
        # CASE 2:
        # Existing active request.
        # -------------------------------------------------

        else:

            # ---------------------------------------------
            # DIFFERENT CATEGORY
            # ---------------------------------------------

            if (
                detected_category
                and detected_category.id
                != current_category.id
            ):

                new_request = (
                    is_new_request_message(
                        text,
                        current_category=current_category,
                        current_field=current_field,
                    )
                )

                print(
                    "DIFFERENT CATEGORY DETECTED"
                )

                print(
                    "NEW REQUEST DECISION:",
                    new_request,
                )

            # ---------------------------------------------
            # SAME CATEGORY
            # ---------------------------------------------

            elif (
                detected_category
                and detected_category.id
                == current_category.id
                and state.waiting_for
            ):

                normalized_text = (
                    text.lower().strip()
                )

                request_phrases = [
                    "i need",
                    "i want",
                    "i would like",
                    "i'd like",
                    "looking for",
                    "i am looking for",
                    "i'm looking for",
                    "can you provide",
                    "can you help",
                    "i need a quote",
                    "i need quotation",
                    "quotation for",
                    "quote for",
                ]

                has_request_phrase = any(
                    phrase in normalized_text
                    for phrase in request_phrases
                )

                explicit_new_request_phrases = [
                    "i also need",
                    "i also want",
                    "i also would like",
                    "i'd also like",
                    "i would also like",
                    "actually i need",
                    "actually i want",
                    "actually i would like",
                    "another request",
                    "another service",
                    "another product",
                    "different request",
                    "different service",
                    "different product",
                    "by the way i need",
                    "by the way i want",
                    "can you also provide",
                    "can you also help",
                ]

                has_explicit_new_request_phrase = any(
                    phrase in normalized_text
                    for phrase in explicit_new_request_phrases
                )

                if current_field:

                    # ---------------------------------
                    # TEXT FIELD
                    # ---------------------------------

                    if current_field.field_type == "text":

                        if has_explicit_new_request_phrase:

                            new_request = True

                            print(
                                "EXPLICIT NEW REQUEST "
                                "DETECTED WHILE ANSWERING "
                                "TEXT FIELD"
                            )

                        elif (
                            state.waiting_for
                            == "location"
                            and detected_category
                            and has_request_phrase
                        ):

                            new_request = True

                            print(
                                "REQUEST STATEMENT DETECTED "
                                "INSTEAD OF LOCATION ANSWER"
                            )

                    # ---------------------------------
                    # NUMBER / YES-NO / OTHER FIELD
                    # ---------------------------------

                    else:

                        valid, cleaned_value = (
                            validate_request_field_value(
                                current_field,
                                text,
                            )
                        )

                        print(
                            "CURRENT FIELD VALIDATION:",
                            valid,
                            cleaned_value,
                        )

                        if (
                            not valid
                            and has_request_phrase
                        ):

                            new_request = True

                            print(
                                "INVALID FIELD ANSWER WITH "
                                "REQUEST LANGUAGE - "
                                "NEW REQUEST"
                            )

        print(
            "CURRENT CATEGORY:",
            current_category,
        )

        print(
            "CURRENT FIELD:",
            current_field,
        )

        print(
            "DETECTED CATEGORY:",
            detected_category,
        )

        print(
            "NEW REQUEST:",
            new_request,
        )

        # =================================================
        # HANDLE NEW REQUEST
        # =================================================

        if new_request:

            print(
                "STARTING NEW BUSINESS REQUEST"
            )

            category = detected_category

            if not category:

                print(
                    "NEW REQUEST FLAGGED BUT "
                    "NO CATEGORY FOUND"
                )

                reply = process_customer_message(
                    text
                )

            else:

                # -----------------------------------------
                # CREATE NEW BUSINESS REQUEST
                # -----------------------------------------

                business_request = (
                    BusinessRequest.objects.create(
                        customer=customer,
                        request_text=text,
                        subject=category.name,
                        category=category,
                        department=category.department,
                        status="new",
                        priority="normal",
                        source="whatsapp",
                    )
                )

                print(
                    "NEW BUSINESS REQUEST CREATED:",
                    business_request,
                )

                # -----------------------------------------
                # LINK CONVERSATION TO REQUEST
                # -----------------------------------------

                conversation.business_request = (
                    business_request
                )

                conversation.save(
                    update_fields=[
                        "business_request",
                    ]
                )

                # -----------------------------------------
                # RESET CONVERSATION STATE
                # -----------------------------------------

                state.data = {
                    "request_text": text,
                    "category": category.name,
                    "business_request_id": (
                        business_request.id
                    ),
                }

                state.current_step = None
                state.waiting_for = None

                state.save()

                print(
                    "CONVERSATION STATE RESET "
                    "FOR NEW REQUEST"
                )

                # -----------------------------------------
                # START FIELD COLLECTION
                # -----------------------------------------

                reply = process_request_fields(
                    category,
                    state,
                    text,
                )

                # -----------------------------------------
                # UPDATE BUSINESS REQUEST
                # -----------------------------------------

                update_business_request_details(
                    business_request,
                    state,
                ) 
                if state.current_step == "details_collected":
                    create_request_workflow(
                        business_request
                    )

        # =================================================
        # CONTINUE CURRENT REQUEST
        # =================================================

        elif current_category:

            category = current_category

            print(
                "CONTINUING CURRENT REQUEST:",
                category,
            )

            # ---------------------------------------------
            # GET CURRENT BUSINESS REQUEST
            # ---------------------------------------------

            business_request = (
                conversation.business_request
            )

            # ---------------------------------------------
            # RECOVER BUSINESS REQUEST IF MISSING
            # ---------------------------------------------

            if not business_request:

                business_request = (
                    create_business_request(
                        customer,
                        text,
                        category,
                        conversation,
                    )
                )

                if business_request:

                    conversation.business_request = (
                        business_request
                    )

                    conversation.save(
                        update_fields=[
                            "business_request",
                        ]
                    )

            # ---------------------------------------------
            # PROCESS CURRENT FIELD
            # ---------------------------------------------

            reply = process_request_fields(
                category,
                state,
                text,
            )

            # ---------------------------------------------
            # UPDATE BUSINESS REQUEST
            # ---------------------------------------------

            if business_request:

                update_business_request_details(
                    business_request,
                    state,
                )
                if state.current_step == "details_collected":
                    create_request_workflow(
                        business_request
            )


        # =================================================
        # FIRST MESSAGE / CATEGORY DETECTED
        # =================================================

        elif detected_category:

            category = detected_category

            print(
                "FIRST REQUEST CATEGORY DETECTED:",
                category,
            )

            business_request = (
                create_business_request(
                    customer,
                    text,
                    category,
                    conversation,
                )
            )

            # ---------------------------------------------
            # SAVE INITIAL STATE
            # ---------------------------------------------

            state_data = {
                "request_text": text,
                "category": category.name,
                "business_request_id": (
                    business_request.id
                    if business_request
                    else None
                ),
            }

            update_conversation_state(
                state,
                data=state_data,
            )

            # ---------------------------------------------
            # LINK BUSINESS REQUEST
            # ---------------------------------------------

            if business_request:

                conversation.business_request = (
                    business_request
                )

                conversation.save(
                    update_fields=[
                        "business_request",
                    ]
                )

                print(
                    "CONVERSATION LINKED TO REQUEST:",
                    business_request,
                )

            # ---------------------------------------------
            # START FIELD COLLECTION
            # ---------------------------------------------

            reply = process_request_fields(
                category,
                state,
                text,
            )

            # ---------------------------------------------
            # UPDATE BUSINESS REQUEST
            # ---------------------------------------------

            if business_request:

                update_business_request_details(
                    business_request,
                    state,
                )
                if state.current_step == "details_collected":
                    create_request_workflow(
                        business_request
                )

        # =================================================
        # NO CATEGORY IDENTIFIED
        # =================================================

        else:

            print(
                "NO CATEGORY IDENTIFIED - "
                "USING FALLBACK"
            )

            reply = process_customer_message(
                text
            )

        # =================================================
        # SEND AUTOMATIC WHATSAPP REPLY
        # =================================================

        print(
            "SENDING AUTOMATIC REPLY..."
        )

        print(
            "REPLY:",
            reply,
        )

        # -------------------------------------------------
        # TEMPORARY:
        # send_whatsapp_message() still uses the existing
        # global WHATSAPP_PHONE_NUMBER_ID and token.
        #
        # We will replace this with the business-specific
        # WhatsApp connection in the next step.
        # -------------------------------------------------

        response = send_whatsapp_message( 
            whatsapp_phone, 
            sender, 
            reply,
        )

        # =================================================
        # SAVE OUTGOING MESSAGE
        # =================================================

        if (
            response is not None
            and response.status_code == 200
        ):

            try:

                response_data = response.json()

            except ValueError:

                response_data = {
                    "raw_response": response.text,
                }

            outgoing_whatsapp_message_id = None

            try:

                outgoing_whatsapp_message_id = (
                    response_data
                    .get("messages", [{}])[0]
                    .get("id")
                )

            except (
                IndexError,
                AttributeError,
                TypeError,
            ):

                outgoing_whatsapp_message_id = None

            outgoing_message = Message.objects.create(
                organization=organization,
                conversation=conversation,
                direction="outgoing",
                sender_type="faltasi",
                message_type="text",
                content=reply,
                whatsapp_message_id=(
                    outgoing_whatsapp_message_id
                ),
                delivery_status="sent",
                metadata=response_data,
            )

            print(
                "OUTGOING MESSAGE SAVED:",
                outgoing_message,
            )

            # Update conversation activity timestamp
            conversation.save(
                update_fields=[
                    "last_message_at",
                ]
            )

        else:

            print(
                "OUTGOING MESSAGE WAS NOT SAVED "
                "BECAUSE WHATSAPP SEND FAILED"
            )

        # =================================================
        # RESPOND TO META
        # =================================================

        return JsonResponse({
            "status": "ok",
        })

    # =====================================================
    # INVALID JSON
    # =====================================================

    except json.JSONDecodeError as e:

        print(
            "JSON ERROR:",
            str(e),
        )

        return JsonResponse(
            {
                "error": "Invalid JSON",
            },
            status=400,
        )

    # =====================================================
    # GENERAL WEBHOOK ERROR
    # =====================================================

    except Exception as e:

        print(
            "WEBHOOK ERROR:",
            str(e),
        )

        return JsonResponse(
            {
                "error": "Webhook processing failed",
            },
            status=500,
        )
def process_customer_message(text):
    """Return a simple fallback when no request category is identified."""
    if not text or not text.strip():
        return 'Thank you for contacting Faltasi Innovations Limited. Please tell us what you need and we will be happy to help.'
    return 'Thank you for contacting Faltasi Innovations Limited. We have received your request.\n\nPlease tell us a little more about what you need so we can assist you properly.'

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
    print('CONVERSATION STATE UPDATED:', state)
    print('CURRENT STEP:', state.current_step)
    print('WAITING FOR:', state.waiting_for)
    print('STATE DATA:', state.data)
    return state

def get_required_request_fields(category):
    """
    Get the active required fields for a request category
    from Django Admin, in the configured order.
    """
    if not category:
        return []
    return list(category.request_fields.filter(is_active=True, is_required=True).order_by('order', 'id'))

def validate_request_field_value(field, text):
    """
    Validate a customer's answer according to the RequestField type.

    Returns:
        (True, cleaned_value) -> valid answer
        (False, None) -> invalid answer
    """
    if not field or text is None:
        return (False, None)
    value = text.strip()
    if not value:
        return (False, None)
    if field.field_type == 'text':
        return (True, value)
    if field.field_type == 'number':
        number_words = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20}
        number_match = re.search('\\d+(?:\\.\\d+)?', value)
        if number_match:
            number = float(number_match.group())
            if number.is_integer():
                number = int(number)
            return (True, number)
        normalized = value.lower()
        for word, number in number_words.items():
            if re.search(f'\\b{word}\\b', normalized):
                return (True, number)
        return (False, None)
    if field.field_type == 'yes_no':
        normalized = value.lower().strip()
        yes_values = ['yes', 'y', 'yeah', 'yep', 'sure', 'correct', 'of course', 'please do', 'i do', 'i need it', 'i need installation', 'needed', 'required']
        no_values = ['no', 'n', 'nope', 'not needed', 'not required', "i don't", 'dont', "don't", 'not necessary']
        if normalized in yes_values:
            return (True, True)
        if normalized in no_values:
            return (True, False)
        yes_phrases = ['yes, please', 'yes please', 'i need', 'i want', 'please do', 'go ahead', 'install it', 'install', 'installation required', 'i need installation']
        for phrase in yes_phrases:
            if phrase in normalized:
                return (True, True)
        no_phrases = ['no, thanks', 'no thanks', "i don't need", 'i dont need', 'i do not need', 'not necessary', 'not required', 'without installation', 'installation not required']
        for phrase in no_phrases:
            if phrase in normalized:
                return (True, False)
        return (False, None)
    if field.field_type == 'choice':
        return (True, value)
    return (True, value)

def get_next_missing_request_field(category, collected_data):
    """
    Find the next required RequestField that has not
    yet been answered by the customer.
    """
    if not category:
        return None
    fields = get_required_request_fields(category)
    for field in fields:
        if field.name not in collected_data:
            return field
    return None

def get_next_request_question(category, collected_data):
    """
    Return the next required question that has not
    yet been answered.
    """
    field = get_next_missing_request_field(category, collected_data)
    if field:
        return field.question
    return None