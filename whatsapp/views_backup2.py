from unicodedata import category

from django.db.migrations import state
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import text, timezone

import json
import requests
import re

from .models import Conversation, ConversationState, Message
from customers.models import Customer
from business_requests.models import BusinessRequest, RequestCategory


# -----------------------------------------
# FIND REQUEST CATEGORY
# -----------------------------------------
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

    categories = RequestCategory.objects.filter(
        is_active=True
    ).order_by("name")

    best_category = None
    best_score = 0

    for category in categories:

        if not category.keywords:
            continue

        keywords = [
            keyword.strip().lower()
            for keyword in category.keywords.split(",")
            if keyword.strip()
        ]

        score = 0

        for keyword in keywords:

            if keyword in message:
                score += 1

        if score > best_score:
            best_score = score
            best_category = category

    if best_category:
        print(
            "CATEGORY IDENTIFIED:",
            best_category.name,
            "| SCORE:",
            best_score
        )
    else:
        print("NO REQUEST CATEGORY IDENTIFIED")

    return best_category


# -----------------------------------------
# SEND WHATSAPP MESSAGE
# -----------------------------------------
def send_whatsapp_message(phone_number, message):

    url = (
        f"https://graph.facebook.com/v26.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {
            "body": message
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        print(
            "WHATSAPP SEND STATUS:",
            response.status_code
        )

        print(
            "WHATSAPP SEND RESPONSE:",
            response.text
        )

        return response

    except requests.RequestException as e:

        print(
            "WHATSAPP SEND ERROR:",
            str(e)
        )

        return None


# -----------------------------------------
# FIND OR CREATE CUSTOMER
# -----------------------------------------
def get_or_create_customer(phone_number):

    customer = Customer.objects.filter(
        phone=phone_number
    ).first()

    if customer:
        return customer

    customer = Customer.objects.create(
        phone=phone_number,
        name="WhatsApp Customer",
        country="Tanzania",
    )

    return customer


# -----------------------------------------
# GET OR CREATE CONVERSATION STATE
# -----------------------------------------
def get_or_create_conversation_state(conversation):
    """
    Get the ConversationState for a conversation.
    Create it if it does not exist.
    """

    state, created = ConversationState.objects.get_or_create(
        conversation=conversation
    )

    if created:
        print(
            "CONVERSATION STATE CREATED:",
            state
        )
    else:
        print(
            "CONVERSATION STATE FOUND:",
            state
        )

    return state


# -----------------------------------------
# CREATE BUSINESS REQUEST
# -----------------------------------------
# -----------------------------------------
# CREATE BUSINESS REQUEST
# -----------------------------------------
def create_business_request(customer, text, category, conversation=None):
    """
    Create or reuse a BusinessRequest for a WhatsApp conversation.

    A conversation should have one active BusinessRequest.
    """

    if not category:
        print("NO REQUEST CATEGORY IDENTIFIED")
        return None

    # -----------------------------------------
    # CHECK REQUEST ALREADY LINKED TO CONVERSATION
    # -----------------------------------------
    if conversation and conversation.business_request:
        business_request = conversation.business_request

        print(
            "EXISTING CONVERSATION REQUEST FOUND:",
            business_request
        )

        return business_request

    # -----------------------------------------
    # CREATE NEW BUSINESS REQUEST
    # -----------------------------------------
    business_request = BusinessRequest.objects.create(
        customer=customer,
        request_text=text,
        subject=category.name,
        category=category,
        department=category.department,
        status="new",
        priority="normal",
        source="whatsapp",
    )

    print(
        "BUSINESS REQUEST CREATED:",
        business_request
    )

    return business_request

def process_request_fields(category, state, text):
    """
    Handle category-specific questions using RequestField
    and ConversationState.
    """

    collected_data = state.data or {}
    waiting_for = state.waiting_for

    # -----------------------------------------
    # HANDLE CURRENT QUESTION
    # -----------------------------------------
    if waiting_for:

        try:
            field = category.request_fields.get(
                name=waiting_for,
                is_active=True
            )
        except Exception:
            field = None

        if field:

            # -----------------------------------------
            # OPTIONAL FIELD
            # -----------------------------------------
            if not field.is_required:

                normalized = text.lower().strip()

                skip_values = [
                    "no",
                    "no budget",
                    "i don't know",
                    "i dont know",
                    "not sure",
                    "not certain",
                    "no idea",
                    "i have no idea",
                    "don't have a budget",
                    "dont have a budget",
                    "i don't have a budget",
                    "i dont have a budget",
                    "not decided",
                    "not decided yet",
                ]

                # Customer does not want or cannot provide
                # the optional information.
                if normalized in skip_values:

                    collected_data[waiting_for] = None

                    update_conversation_state(
                        state,
                        data=collected_data
                    )

                else:

                    valid, cleaned_value = validate_request_field_value(
                        field,
                        text
                    )

                    if valid:

                        collected_data[waiting_for] = cleaned_value

                        update_conversation_state(
                            state,
                            data=collected_data
                        )

                    else:

                        return (
                            "I’m sorry, I didn’t quite understand that.\n\n"
                            f"{field.question}"
                        )

            # -----------------------------------------
            # REQUIRED FIELD
            # -----------------------------------------
            else:

                valid, cleaned_value = validate_request_field_value(
                    field,
                    text
                )

                if not valid:

                    return (
                        "I’m sorry, I didn’t quite understand that answer.\n\n"
                        f"{field.question}"
                    )

                collected_data[waiting_for] = cleaned_value

                update_conversation_state(
                    state,
                    data=collected_data
                )

    # -----------------------------------------
    # FIND NEXT REQUIRED FIELD
    # -----------------------------------------
    next_field = get_next_missing_request_field(
        category,
        collected_data
    )

    if next_field:

        update_conversation_state(
            state,
            current_step="collecting_details",
            waiting_for=next_field.name,
            data=collected_data
        )

        return next_field.question

    # -----------------------------------------
    # ALL REQUIRED INFORMATION COLLECTED
    # -----------------------------------------
    update_conversation_state(
        state,
        current_step="details_collected",
        waiting_for=None,
        data=collected_data
    )

    return (
        "Thank you. We now have the information we need. "
        "Our team will review your request and get back to you shortly."
    )
# -----------------------------------------
# UPDATE BUSINESS REQUEST WITH COLLECTED DETAILS
# -----------------------------------------
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
    original_request = state_data = collected_data.get(
        "request_text"
    )

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

        details.append(
            f"{field_name.replace('_', ' ').title()}: {value}"
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
# -----------------------------------------
# WHATSAPP WEBHOOK
# -----------------------------------------
# -----------------------------------------
# WHATSAPP WEBHOOK
# -----------------------------------------
@csrf_exempt
def webhook(request):

    # -----------------------------------------
    # META WEBHOOK VERIFICATION
    # -----------------------------------------
    if request.method == "GET":

        verify_token = request.GET.get(
            "hub.verify_token"
        )

        challenge = request.GET.get(
            "hub.challenge"
        )

        print(
            "VERIFY TOKEN:",
            verify_token
        )

        print(
            "CHALLENGE:",
            challenge
        )

        # Meta verification request
        if verify_token and challenge:

            if (
                verify_token
                == settings.WHATSAPP_VERIFY_TOKEN
            ):

                print(
                    "VERIFICATION SUCCESS"
                )

                return HttpResponse(
                    challenge
                )

            print(
                "VERIFICATION FAILED"
            )

            return HttpResponse(
                "Invalid verify token",
                status=403
            )

        # Other GET requests from Meta
        print(
            "GET request received without "
            "verification parameters"
        )

        return HttpResponse(
            "OK",
            status=200
        )

    # -----------------------------------------
    # WHATSAPP WEBHOOK EVENTS
    # -----------------------------------------
    if request.method == "POST":

        print(
            "========== POST RECEIVED =========="
        )

        body = request.body.decode(
            "utf-8",
            errors="replace"
        )

        print(
            "BODY:",
            body
        )

        try:

            data = json.loads(body)

            print("JSON:")

            print(
                json.dumps(
                    data,
                    indent=2
                )
            )

            # -----------------------------------------
            # READ STANDARD WHATSAPP WEBHOOK
            # -----------------------------------------

            entry = data.get(
                "entry",
                []
            )

            if entry:

                changes = entry[0].get(
                    "changes",
                    []
                )

                if changes:

                    value = changes[0].get(
                        "value",
                        {}
                    )

                    # -----------------------------------------
                    # GET MESSAGES
                    # -----------------------------------------

                    messages = value.get(
                        "messages",
                        []
                    )

                    if messages:





                        message = messages[0]

                        # -----------------------------------------
                        # DUPLICATE MESSAGE PROTECTION
                        # -----------------------------------------
                        whatsapp_message_id = message.get("id")

                        print(
                            "WHATSAPP MESSAGE ID:",
                            whatsapp_message_id
                        )

                        if whatsapp_message_id:
                            existing_message = Message.objects.filter(
                                whatsapp_message_id=whatsapp_message_id
                            ).first()

                            if existing_message:
                                print(
                                    "DUPLICATE MESSAGE IGNORED:",
                                    whatsapp_message_id
                                )

                                return JsonResponse(
                                    {
                                        "status": "ok",
                                        "duplicate": True
                                    }
                                )

                        sender = message.get(
                            "from"
                        )

                        message_type = message.get(
                            "type"
                        )






                        print(
                            "SENDER:",
                            sender
                        )

                        print(
                            "MESSAGE TYPE:",
                            message_type
                        )

                        # -----------------------------------------
                        # TEXT MESSAGE
                        # -----------------------------------------

                        if message_type == "text":

                            text = (
                                message
                                .get("text", {})
                                .get("body", "")
                            )

                            print(
                                "MESSAGE:",
                                text
                            )

                            # -----------------------------------------
                            # CUSTOMER + CONVERSATION
                            # -----------------------------------------

                            if sender:

                                # Find or create customer
                                customer = get_or_create_customer(
                                    sender
                                )

                                print(
                                    "CUSTOMER:",
                                    customer
                                )

                                # Find active conversation
                                conversation = (
                                    Conversation.objects.filter(
                                        customer=customer,
                                        phone_number=sender,
                                        status="active"
                                    ).first()
                                )

                                # -----------------------------------------
                                # CREATE CONVERSATION IF NEEDED
                                # -----------------------------------------

                                if not conversation:

                                    conversation = (
                                        Conversation.objects.create(
                                            customer=customer,
                                            phone_number=sender
                                        )
                                    )

                                    print(
                                        "NEW CONVERSATION CREATED:",
                                        conversation
                                    )

                                # -----------------------------------------
                                # GET OR CREATE CONVERSATION STATE
                                # -----------------------------------------

                                state = (
                                    get_or_create_conversation_state(
                                        conversation
                                    )
                                )

                                print(
                                    "CURRENT STEP:",
                                    state.current_step
                                )

                                print(
                                    "WAITING FOR:",
                                    state.waiting_for
                                )

                                print(
                                    "STATE DATA:",
                                    state.data
                                )

                                print(
                                    "CONVERSATION:",
                                    conversation
                                )

                                # -----------------------------------------
                                # SAVE INCOMING MESSAGE
                                # -----------------------------------------

                                incoming_message = (
                                    Message.objects.create(
                                        conversation=conversation,
                                        direction="incoming",
                                        sender_type="customer",
                                        message_type=message_type,
                                        content=text,
                                        delivery_status="delivered",
                                        metadata=message
                                    )
                                )

                                print(
                                    "MESSAGE SAVED:",
                                    incoming_message
                                )

                                # -----------------------------------------
                                # IDENTIFY CATEGORY
                                # -----------------------------------------

                                category = (
                                    find_request_category(
                                        text
                                    )
                                )

                                # -----------------------------------------
                                # CHECK EXISTING CATEGORY IN STATE
                                # -----------------------------------------

                                state_data = state.data or {}

                                stored_category_name = (
                                    state_data.get(
                                        "category"
                                    )
                                )

                                if not category and stored_category_name:

                                    try:

                                        category = (
                                            RequestCategory.objects.get(
                                                name=stored_category_name
                                            )
                                        )

                                        print(
                                            "CATEGORY RESTORED FROM STATE:",
                                            category
                                        )

                                    except RequestCategory.DoesNotExist:

                                        category = None

                                # -----------------------------------------
                                # CREATE BUSINESS REQUEST
                                # -----------------------------------------

                                business_request = (
                                    create_business_request(
                                        customer,
                                        text,
                                        category,
                                        conversation,
                                    )
                                )

                                # -----------------------------------------
                                # SAVE INITIAL REQUEST DATA
                                # -----------------------------------------

                                if "request_text" not in state_data:

                                    state_data[
                                        "request_text"
                                    ] = text

                                if category:

                                    state_data[
                                        "category"
                                    ] = category.name

                                if business_request:

                                    state_data[
                                        "business_request_id"
                                    ] = business_request.id

                                # -----------------------------------------
                                # UPDATE STATE DATA
                                # -----------------------------------------

                                update_conversation_state(
                                    state,
                                    data=state_data
                                )

                                # -----------------------------------------
                                # LINK BUSINESS REQUEST TO CONVERSATION
                                # -----------------------------------------

                                if business_request:

                                    conversation.business_request = (
                                        business_request
                                    )

                                    conversation.save(
                                        update_fields=[
                                            "business_request"
                                        ]
                                    )

                                    print(
                                        "CONVERSATION LINKED TO REQUEST:",
                                        business_request,
                                    )

                                # -----------------------------------------
                                # AUTOMATIC REPLY
                                # -----------------------------------------


                                if category:
                                    reply = process_request_fields(
                                        category,
                                        state,
                                        text
                                    )

                                    # Update the BusinessRequest with collected details
                                    if business_request:
                                        update_business_request_details(
                                            business_request,
                                            state
                                        )

                                else:
                                    reply = process_customer_message(
                                        text
                                    )


                                print(
                                    "SENDING AUTOMATIC REPLY..."
                                )

                                response = (
                                    send_whatsapp_message(
                                        sender,
                                        reply
                                    )
                                )

                                # -----------------------------------------
                                # SAVE OUTGOING MESSAGE
                                # -----------------------------------------

                                if (
                                    response is not None
                                    and response.status_code == 200
                                ):

                                    response_data = (
                                        response.json()
                                    )

                                    whatsapp_message_id = None

                                    try:

                                        whatsapp_message_id = (
                                            response_data
                                            .get(
                                                "messages",
                                                [{}]
                                            )[0]
                                            .get("id")
                                        )

                                    except (
                                        IndexError,
                                        AttributeError
                                    ):

                                        pass

                                    outgoing_message = (
                                        Message.objects.create(
                                            conversation=conversation,
                                            direction="outgoing",
                                            sender_type="faltasi",
                                            message_type="text",
                                            content=reply,
                                            whatsapp_message_id=(
                                                whatsapp_message_id
                                            ),
                                            delivery_status="sent",
                                            metadata=response_data
                                        )
                                    )

                                    print(
                                        "OUTGOING MESSAGE SAVED:",
                                        outgoing_message
                                    )

                        # -----------------------------------------
                        # OTHER MESSAGE TYPES
                        # -----------------------------------------

                        else:

                            print(
                                "NON-TEXT MESSAGE RECEIVED"
                            )

                    else:

                        print(
                            "NO WHATSAPP MESSAGE FOUND"
                        )

            else:

                print(
                    "NO WEBHOOK ENTRY FOUND"
                )

            # -----------------------------------------
            # RESPOND TO META
            # -----------------------------------------

            return JsonResponse(
                {
                    "status": "ok"
                }
            )

        except json.JSONDecodeError as e:

            print(
                "JSON ERROR:",
                e
            )

            return JsonResponse(
                {
                    "error": "Invalid JSON"
                },
                status=400
            )

        except Exception as e:

            print(
                "WEBHOOK ERROR:",
                str(e)
            )

            return JsonResponse(
                {
                    "error": "Webhook processing failed"
                },
                status=500
            )

    # -----------------------------------------
    # METHOD NOT ALLOWED
    # -----------------------------------------

    return HttpResponse(
        status=405
    )
# -----------------------------------------
# CUSTOMER MESSAGE PROCESSING
# -----------------------------------------
def process_customer_message(text):
    """
    Generate a response based on what
    the customer writes.
    """

    text = text.strip()

    if not text:

        return (
            "Thank you for contacting Faltasi Innovations Limited. "
            "Please tell us what you need and we will be happy to help."
        )

    # Convert to lowercase for easier matching
    message = text.lower()

    # -----------------------------------------
    # WAPANGAJI KIGANJANI
    # -----------------------------------------
    if any(word in message for word in [
        "wapangaji",
        "tenant",
        "tenants",
        "rent",
        "rental property",
        "property management",
        "landlord"
    ]):

        return (
            "Thank you for your interest in Wapangaji Kiganjani. "
            "It is Faltasi Innovations' property management platform "
            "designed to help landlords manage tenants, rent, properties "
            "and related services.\n\n"
            "Please tell us a little more about your property and what "
            "you would like to manage."
        )

    # -----------------------------------------
    # CCTV / SECURITY
    # -----------------------------------------
    if any(word in message for word in [
        "cctv",
        "camera",
        "security camera",
        "surveillance"
    ]):

        return (
            "Thank you. We can assist with CCTV and security solutions.\n\n"
            "Please tell us the location of the property and "
            "what you would like to secure."
        )

    # -----------------------------------------
    # POS
    # -----------------------------------------
    if any(word in message for word in [
        "pos",
        "point of sale",
        "cashier system"
    ]):

        return (
            "Thank you for your interest in POS solutions.\n\n"
            "Please tell us what type of business you operate "
            "and what you would like the POS system to help you manage."
        )

    # -----------------------------------------
    # COMPUTERS / LAPTOPS
    # -----------------------------------------
    if any(word in message for word in [
        "laptop",
        "laptops",
        "computer",
        "computers",
        "desktop"
    ]):

        return (
            "Certainly. We can assist with computers and laptops.\n\n"
            "Please tell us how many you need and, if you have one, "
            "your preferred budget or specifications."
        )

    # -----------------------------------------
    # NETWORKING
    # -----------------------------------------
    if any(word in message for word in [
        "network",
        "networking",
        "wifi",
        "wi-fi",
        "internet installation"
    ]):

        return (
            "Thank you. We provide networking and ICT solutions.\n\n"
            "Please tell us the location and briefly describe "
            "what you need for your network."
        )

    # -----------------------------------------
    # PARTNERSHIP
    # -----------------------------------------
    if any(word in message for word in [
        "partner",
        "partnership",
        "become a partner"
    ]):

        return (
            "Thank you for your interest in partnering with "
            "Faltasi Innovations Limited.\n\n"
            "Please tell us a little about yourself or your organization "
            "and the type of partnership you are interested in."
        )

    # -----------------------------------------
    # GENERAL QUOTATION REQUEST
    # -----------------------------------------
    if any(word in message for word in [
        "quotation",
        "quote",
        "price",
        "cost",
        "how much"
    ]):

        return (
            "We would be happy to prepare a quotation for you.\n\n"
            "Please describe the product or service you need, "
            "including the quantity or requirements if applicable."
        )

    # -----------------------------------------
    # DEFAULT RESPONSE
    # -----------------------------------------
    return (
        "Thank you for contacting Faltasi Innovations Limited. "
        "We have received your request.\n\n"
        "Please provide a little more information about what you need "
        "so we can assist you properly."
    )

# -----------------------------------------
# UPDATE CONVERSATION STATE
# -----------------------------------------
# -----------------------------------------
# UPDATE CONVERSATION STATE
# -----------------------------------------
def update_conversation_state(
    state,
    current_step=None,
    waiting_for="__UNCHANGED__",
    data=None
):
    """
    Update the conversation state and save it.

    waiting_for behavior:
    - "__UNCHANGED__" = keep the existing value
    - None = clear the value
    - any other value = set the value
    """

    if current_step is not None:
        state.current_step = current_step

    if waiting_for != "__UNCHANGED__":
        state.waiting_for = waiting_for

    if data is not None:
        existing_data = state.data or {}
        existing_data.update(data)
        state.data = existing_data

    state.save()

    print(
        "CONVERSATION STATE UPDATED:",
        state
    )

    print(
        "CURRENT STEP:",
        state.current_step
    )

    print(
        "WAITING FOR:",
        state.waiting_for
    )

    print(
        "STATE DATA:",
        state.data
    )

    return state

def get_required_request_fields(category):
    """
    Get the active required fields for a request category
    from Django Admin, in the configured order.
    """
    if not category:
        return []

    return list(
        category.request_fields.filter(
            is_active=True,
            is_required=True
        ).order_by("order", "id")
    )


def validate_request_field_value(field, text):
    """
    Validate a customer's answer according to the RequestField type.

    Returns:
        (True, cleaned_value) -> valid answer
        (False, None) -> invalid answer
    """

    if not field or text is None:
        return False, None

    value = text.strip()

    if not value:
        return False, None

    # -----------------------------------------
    # TEXT
    # -----------------------------------------
    if field.field_type == "text":
        return True, value

    # -----------------------------------------
    # NUMBER
    # -----------------------------------------
# -----------------------------------------
# NUMBER
# -----------------------------------------
    if field.field_type == "number":

        number_words = {
            "zero": 0,
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }

        # -----------------------------------------
        # CHECK DIGITS
        # -----------------------------------------
        number_match = re.search(
            r"\d+(?:\.\d+)?",
            value
        )

        if number_match:

            number = float(
                number_match.group()
            )

            if number.is_integer():
                number = int(number)

            return True, number

        # -----------------------------------------
        # CHECK WRITTEN NUMBERS
        # -----------------------------------------
        normalized = value.lower()

        for word, number in number_words.items():

            if re.search(
                rf"\b{word}\b",
                normalized
            ):
                return True, number

        # -----------------------------------------
        # NO NUMBER FOUND
        # -----------------------------------------
        return False, None

    # -----------------------------------------
    # YES / NO
    # -----------------------------------------
    # -----------------------------------------
# YES / NO
# -----------------------------------------
    if field.field_type == "yes_no":

        normalized = value.lower().strip()

        yes_values = [
            "yes",
            "y",
            "yeah",
            "yep",
            "sure",
            "correct",
            "of course",
            "please do",
            "i do",
            "i need it",
            "i need installation",
            "needed",
            "required",
        ]

        no_values = [
            "no",
            "n",
            "nope",
            "not needed",
            "not required",
            "i don't",
            "dont",
            "don't",
            "not necessary",
        ]

        # -----------------------------------------
        # EXACT YES
        # -----------------------------------------
        if normalized in yes_values:
            return True, True

        # -----------------------------------------
        # EXACT NO
        # -----------------------------------------
        if normalized in no_values:
            return True, False

        # -----------------------------------------
        # NATURAL YES RESPONSES
        # -----------------------------------------
        yes_phrases = [
            "yes, please",
            "yes please",
            "i need",
            "i want",
            "please do",
            "go ahead",
            "install it",
            "install",
            "installation required",
            "i need installation",
        ]

        for phrase in yes_phrases:
            if phrase in normalized:
                return True, True

        # -----------------------------------------
        # NATURAL NO RESPONSES
        # -----------------------------------------
        no_phrases = [
            "no, thanks",
            "no thanks",
            "i don't need",
            "i dont need",
            "i do not need",
            "not necessary",
            "not required",
            "without installation",
            "installation not required",
        ]

        for phrase in no_phrases:
            if phrase in normalized:
                return True, False

        # -----------------------------------------
        # UNKNOWN ANSWER
        # -----------------------------------------
        return False, None
    # -----------------------------------------
    # CHOICE
    # -----------------------------------------
    if field.field_type == "choice":
        return True, value

    # -----------------------------------------
    # UNKNOWN TYPE
    # -----------------------------------------
    return True, value

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


