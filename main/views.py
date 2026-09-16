from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from django.core.mail import send_mail
from django.http import HttpResponse
from products.models import Product, ProductCategory
from customers.models import Customer
from business_requests.models import BusinessRequest
import os

def home(request):
    return render(request, "main/home.html")


def about(request):
    return render(request, "main/about.html")


def services(request):
    return render(request, "main/services.html")



def contact(request):

    product = request.GET.get("product", "")

    if request.method == "POST":

        name = request.POST.get("name")
        email = request.POST.get("email")
        phone = request.POST.get("phone")
        product = request.POST.get("product")
        message = request.POST.get("message")

        # Send inquiry to Faltasi
        send_mail(
            subject=f"New Contact Message from {name}",
            message=f"""
Name: {name}
Email: {email}
Phone: {phone}

Product / Service Interested In:
{product}

Message:
{message}
""",
            from_email=os.getenv("EMAIL_HOST_USER"),
            recipient_list=["faltasiinnovationsltd@gmail.com"],
            fail_silently=False,
        )

        # Automatic reply to the customer
        send_mail(
            subject="Thank You for Contacting Faltasi Innovations",
            message=f"""
Dear {name},

Thank you for contacting Faltasi Innovations Limited.

We have received your inquiry regarding:

{product}

Our team will review your request and get back to you shortly.

If you have any additional information that may help us assist you, please feel free to reply to this email.

Best regards,

Faltasi Innovations Limited
ICT Products & Services

www.faltasi.com
""",
            from_email=os.getenv("EMAIL_HOST_USER"),
            recipient_list=[email],
            fail_silently=False,
        )

    return render(
        request,
        "main/contact.html",
        {
            "selected_product": product,
        }
    )


def contact2(request):

    product = request.GET.get("product", "")

    if request.method == "POST":

        name = request.POST.get("name")
        email = request.POST.get("email")
        phone = request.POST.get("phone")
        product = request.POST.get("product")
        message = request.POST.get("message")

        # ==========================================
        # 1. CREATE OR UPDATE CUSTOMER
        # ==========================================

        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={
                "name": name,
                "email": email,
                "preferred_contact_method": "email",
                "country": "Tanzania",
            }
        )

        # Update existing customer information
        if not created:
            customer.name = name
            customer.email = email
            customer.preferred_contact_method = "email"
            customer.save()

        print("CUSTOMER SAVED:", customer)

        # ==========================================
        # 2. CREATE BUSINESS REQUEST
        # ==========================================

        business_request = BusinessRequest.objects.create(
            customer=customer,
            request_text=message,
            subject=product if product else "Website Inquiry",
            status="new",
            priority="normal",
            source="website",
        )

        print("BUSINESS REQUEST SAVED:", business_request)

        # ==========================================
        # 3. SEND INQUIRY TO FALTASI
        # ==========================================

        send_mail(
            subject=f"New Contact Message from {name}",
            message=f"""
Name: {name}
Email: {email}
Phone: {phone}

Product / Service Interested In:
{product}

Message:
{message}

Business Request ID:
{business_request.id}
""",
            from_email=os.getenv("EMAIL_HOST_USER"),
            recipient_list=["faltasiinnovationsltd@gmail.com"],
            fail_silently=False,
        )

        # ==========================================
        # 4. SEND AUTOMATIC REPLY TO CUSTOMER
        # ==========================================

        send_mail(
            subject="Thank You for Contacting Faltasi Innovations",
            message=f"""
Dear {name},

Thank you for contacting Faltasi Innovations Limited.

We have received your inquiry regarding:

{product}

Our team will review your request and get back to you shortly.

If you have any additional information that may help us assist you, please feel free to reply to this email.

Best regards,

Faltasi Innovations Limited
ICT Products & Services

www.faltasi.com
""",
            from_email=os.getenv("EMAIL_HOST_USER"),
            recipient_list=[email],
            fail_silently=False,
        )

    # ==========================================
    # 5. DISPLAY CONTACT2 PAGE
    # ==========================================

    return render(
        request,
        "main/contact2.html",
        {
            "selected_product": product,
        }
    )



def products(request):
    return render(request, "main/products.html")

def team(request):
    return render(request, 'main/team.html')
def partners(request):
    return render(request, "main/partners.html")


def products2(request):

    categories = ProductCategory.objects.filter(
        is_active=True
    )

    products = Product.objects.filter(
        is_active=True
    ).select_related("category")

    category_id = request.GET.get("category")

    if category_id:
        products = products.filter(
            category_id=category_id
        )

    selected_category = None

    if category_id:
        try:
            selected_category = int(category_id)
        except ValueError:
            selected_category = None

    return render(
        request,
        "main/products2.html",
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