from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import render, redirect


def register(request):

    if request.user.is_authenticated:
        return redirect("business_requests:business_dashboard")

    if request.method == "POST":

        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password_confirm = request.POST.get(
            "password_confirm",
            ""
        )

        # -----------------------------
        # Required fields
        # -----------------------------

        if not username:
            messages.error(request, "Username is required.")
            return redirect("accounts:register")

        if not email:
            messages.error(request, "Email address is required.")
            return redirect("accounts:register")

        if not password:
            messages.error(request, "Password is required.")
            return redirect("accounts:register")

        # -----------------------------
        # Password confirmation
        # -----------------------------

        if password != password_confirm:
            messages.error(
                request,
                "Passwords do not match."
            )
            return redirect("accounts:register")

        # -----------------------------
        # Username check
        # -----------------------------

        if User.objects.filter(
            username__iexact=username
        ).exists():

            messages.error(
                request,
                "This username is already in use."
            )
            return redirect("accounts:register")

        # -----------------------------
        # Email check
        # -----------------------------

        if User.objects.filter(
            email__iexact=email
        ).exists():

            messages.error(
                request,
                "An account with this email already exists."
            )
            return redirect("accounts:register")

        # -----------------------------
        # Create user
        # -----------------------------

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        user.is_active = True
        user.is_staff = False
        user.is_superuser = False

        user.save()

        messages.success(
            request,
            "Your account has been created successfully."
        )

        login(request, user)

        return redirect(
            "business_requests:business_dashboard"
        )

    return render(
        request,
        "accounts/register.html"
    )
