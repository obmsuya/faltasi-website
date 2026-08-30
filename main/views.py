from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from django.core.mail import send_mail


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
        message = request.POST.get("message")

        send_mail(
            subject=f"New Contact Message from {name}",
            message=f"""
Name: {name}
Email: {email}
Phone: {phone}

Message:
{message}
""",
            from_email=None,
            recipient_list=["faltasiinnovationsltd@gmail.com"],
            fail_silently=False,
        )

    return render(request, "main/contact.html")