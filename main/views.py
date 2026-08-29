from django.shortcuts import render

# Create your views here.
from django.shortcuts import render


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

        print("NAME:", name)
        print("EMAIL:", email)
        print("PHONE:", phone)
        print("MESSAGE:", message)

    return render(request, "main/contact.html")