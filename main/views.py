from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from django.core.mail import send_mail
from django.http import HttpResponse


def home(request):
    return render(request, "main/home.html")


def about(request):
    return render(request, "main/about.html")


def services(request):
    return render(request, "main/services.html")



def contact(request):

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
            from_email=None,
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
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )

    return render(request, "main/contact.html")






def products(request):
    return render(request, "main/products.html")

def team(request):
    return render(request, 'main/team.html')




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