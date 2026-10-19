from django.conf import settings

from django.shortcuts import render



# Create your views here.

from django.shortcuts import render

from django.core.mail import send_mail

from django.http import HttpResponse

from products.models import Product, ProductCategory

from customers.models import Customer

from business_requests.models import BusinessRequest

from organizations.models import Organization

import os


import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


def _validate_website_request(name, email, phone, message):
    """Validate public contact and quotation form submissions."""

    if not name:
        return "Please provide your name."

    if len(name) > 100:
        return "Your name must be 100 characters or fewer."

    if not message:
        return "Please provide a message."

    if len(message) > 5000:
        return "Your message must be 5,000 characters or fewer."

    if len(email) > 254:
        return "Please enter a valid email address."

    if email:
        try:
            validate_email(email)
        except ValidationError:
            return "Please enter a valid email address."
    if phone:
        cleaned_phone = re.sub(r"[\s().-]", "", phone)

        if not re.fullmatch(r"\+?[0-9]{7,15}", cleaned_phone):
            return "Please enter a valid phone number."


def home(request):

    return render(request, "main/home.html")

def about(request):

    return render(request, "main/about.html")


def services(request):

    return render(request, "main/services.html")

def _save_website_request(

    name,

    email,

    phone,

    message,

    organization,

    product=None,

):

    """

    Save a website inquiry or product quote request.

    """



    # Find a customer belonging to this organization only.
    customer = Customer.objects.filter(
        phone=phone,
        organization=organization,
    ).first()

    # Create a new customer if this organization has no match.
    if not customer:
        customer = Customer.objects.create(
            organization=organization,
            phone=phone,
            name=name,
            email=email,
            preferred_contact_method="email",
            country="Tanzania",
        )
    else:
        # Update only the customer belonging to this organization.
        customer.name = name
        customer.email = email
        customer.preferred_contact_method = "email"
        customer.save(
            update_fields=[
                "name",
                "email",
                "preferred_contact_method",
            ]
        )

    # Create the BusinessRequest.

    business_request = BusinessRequest.objects.create(

        customer=customer,

        product=product,

        category=product.request_category if product else None,

        request_text=message,

        subject=product.name if product else "General Website Inquiry",

        status="new",

        priority="normal",

        source="website",

    )



    print("CUSTOMER SAVED:", customer)

    print("BUSINESS REQUEST SAVED:", business_request)

    print("PRODUCT:", product)

    print(

        "CATEGORY:",

        product.request_category if product else None,

    )



    # Notify Faltasi.

    send_mail(

        subject=(

            f"New Website Quote Request - {product.name}"

            if product

            else "New General Website Inquiry"

        ),

        message=(

            f"Customer Name: {name}\n"

            f"Email: {email}\n"

            f"Phone: {phone}\n\n"

            f"Product: {product.name if product else 'Not specified'}\n\n"

            f"Message:\n{message}\n"

            f"Business Request ID: {business_request.id}\n"

        ),

        from_email=settings.DEFAULT_FROM_EMAIL,

        recipient_list=["faltasiinnovationsltd@gmail.com"],

        fail_silently=True,

    )



    # Send confirmation to the customer.

    if email:

        send_mail(

            subject="We Received Your Request - Faltasi Innovations Limited",

            message=(

                f"Dear {name},\n\n"

                "Thank you for contacting Faltasi Innovations Limited.\n\n"

                "We have received your request"

                f"{' regarding ' + product.name if product else ''}.\n\n"

                "Our team will review your request and contact you shortly.\n\n"

                "Regards,\n"

                "Faltasi Innovations Limited\n"

                "Dar es Salaam, Tanzania\n"

                "+255 653 397 942"

            ),

            from_email=settings.DEFAULT_FROM_EMAIL,

            recipient_list=[email],

            fail_silently=True,

        )



    return business_request



def contact(request):
    """
    General Contact Us page.
    This page does not require a product selection.
    Includes a honeypot check to reduce automated spam.
    """

    organization = Organization.objects.filter(
        name="Faltasi Innovations Limited",
        organization_type="platform_owner",
        status="active",
    ).first()

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        message = request.POST.get("message", "").strip()

        # Silently reject bots that fill in the hidden honeypot field.
        if request.POST.get("website", "").strip():
            return render(
                request,
                "main/contact.html",
                {"success": True},
            )

        if not organization:
            return render(
                request,
                "main/contact.html",
                {"organization_error": True},
            )

        # Validate submitted contact details.
        validation_error = _validate_website_request(
            name=name,
            email=email,
            phone=phone,
            message=message,
        )

        if validation_error:
            return render(
                request,
                "main/contact.html",
                {"error": validation_error},
            )

        _save_website_request(
            name=name,
            email=email,
            phone=phone,
            message=message,
            organization=organization,
        )

        return render(
            request,
            "main/contact.html",
            {"success": True},
        )

    return render(
        request,
        "main/contact.html",
    )






def request_quote(request):
    """
    Product-specific quote request.
    The product is loaded from the database and cannot be
    changed to a different product through the submitted form.
    Includes a honeypot check to reduce automated spam.
    """

    product_id = (
        request.GET.get("product_id")
        or request.POST.get("product_id", "")
    )

    organization = Organization.objects.filter(
        name="Faltasi Innovations Limited",
        organization_type="platform_owner",
        status="active",
    ).first()

    product = None

    if organization and product_id:
        product = Product.objects.filter(
            id=product_id,
            organization=organization,
            is_active=True,
            allow_quote_request=True,
        ).select_related(
            "request_category",
        ).first()

    # Do not accept a quote without a valid product.
    if not organization or not product:
        return render(
            request,
            "main/request_quote.html",
            {
                "product_error": (
                    "This product is unavailable for quote requests. "
                    "Please return to the Products page and select "
                    "an available product."
                ),
                "product": None,
            },
        )

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        message = request.POST.get("message", "").strip()

        # Silently reject bots that fill in the hidden honeypot field.
        if request.POST.get("website", "").strip():
            return render(
                request,
                "main/request_quote.html",
                {
                    "product": product,
                    "product_id": product.id,
                    "success": True,
                },
            )

        # Validate submitted contact details.
        validation_error = _validate_website_request(
            name=name,
            email=email,
            phone=phone,
            message=message,
        )

        if validation_error:
            return render(
                request,
                "main/request_quote.html",
                {
                    "product": product,
                    "product_id": product.id,
                    "error": validation_error,
                },
            )

        _save_website_request(
            name=name,
            email=email,
            phone=phone,
            message=message,
            organization=organization,
            product=product,
        )

        return render(
            request,
            "main/request_quote.html",
            {
                "product": product,
                "product_id": product.id,
                "success": True,
            },
        )

    return render(
        request,
        "main/request_quote.html",
        {
            "product": product,
            "product_id": product.id,
        },
    )



def team(request):

    return render(request, 'main/team.html')

def partners(request):

    return render(request, "main/partners.html")





def products(request):



    organization = Organization.objects.filter(

        name="Faltasi Innovations Limited",

        organization_type="platform_owner",

        status="active",

    ).first()



    if not organization:

        return render(

            request,

            "main/products.html",

            {

                "products": Product.objects.none(),

                "categories": ProductCategory.objects.none(),

                "selected_category": None,

            }

        )



    categories = ProductCategory.objects.filter(

        organization=organization,

        is_active=True,

    )



    products = Product.objects.filter(

        organization=organization,

        is_active=True,

    ).select_related(

        "category"

    )



    category_id = request.GET.get("category")



    if category_id:

        products = products.filter(

            category_id=category_id,

            category__organization=organization,

        )



    selected_category = None



    if category_id:

        try:

            selected_category = int(category_id)

        except ValueError:

            selected_category = None



    return render(

        request,

        "main/products.html",

        {

            "products": products,

            "categories": categories,

            "selected_category": selected_category,

        }

    )

def sitemap(request):

    xml = """<?xml version="1.0" encoding="UTF-8"?>

<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">



    <url>

        <loc>https://www.faltasi.com/</loc>

    </url>



    <url>

        <loc>https://www.faltasi.com/about/</loc>

    </url>



    <url>

        <loc>https://www.faltasi.com/services/</loc>

    </url>



    <url>

        <loc>https://www.faltasi.com/products/</loc>

    </url>



    <url>

        <loc>https://www.faltasi.com/team/</loc>

    </url>



    <url>

        <loc>https://www.faltasi.com/contact/</loc>

    </url>



</urlset>"""



    return HttpResponse(xml, content_type="application/xml")



def privacy_policy(request):

    return render(request, "main/privacy_policy.html")
