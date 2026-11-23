from django.conf import settings

from django.shortcuts import render



# Create your views here.

from django.shortcuts import render


from django.http import HttpResponse


from business_requests.services.website import (
    create_website_request,
    get_website_organization,
    validate_website_request,
)






def home(request):

    return render(request, "main/home.html")

def about(request):

    return render(request, "main/about.html")


def services(request):

    return render(request, "main/services.html")

def contact(request):
    """
    General Contact Us page.
    This page does not require a product selection.
    Includes a honeypot check to reduce automated spam.
    """

    organization = get_website_organization()

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
        validation_error = validate_website_request(
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

        create_website_request(
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


def team(request):

    return render(request, 'main/team.html')

def partners(request):

    return render(request, "main/partners.html")



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
