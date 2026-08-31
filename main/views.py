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