from django.shortcuts import render

from products.models import OrganizationCategoryAssignment, Product, ProductCategory
from business_requests.services.website import (
    create_website_request,
    get_website_organization,
    validate_website_request,
)


def _platform_organization():
    return get_website_organization()


def public_product_list(request):
    organization = _platform_organization()
    selected_category_id = None
    if organization is None:
        products = Product.objects.none()
        categories = ProductCategory.objects.none()
    else:
        assigned_category_ids = OrganizationCategoryAssignment.objects.filter(
            organization=organization,
            category__organization__isnull=True,
            category__is_active=True,
        ).values_list("category_id", flat=True)

        categories = ProductCategory.objects.filter(
            pk__in=assigned_category_ids,
            is_active=True,
        ).order_by("name")

        products = Product.objects.filter(
            organization=organization,
            is_active=True,
            deleted_at__isnull=True,
            show_on_website=True,
            is_publicly_visible=True,
            category_id__in=assigned_category_ids,
        ).select_related("category").order_by("display_order", "name")

        category_id = request.GET.get("category")
        if category_id:
            try:
                selected_category_id = int(category_id)
            except (TypeError, ValueError):
                selected_category_id = None
            if selected_category_id and categories.filter(pk=selected_category_id).exists():
                products = products.filter(category_id=selected_category_id)

    return render(
        request,
        "products/public_product_list.html",
        {
            "products": products,
            "categories": categories,
            "selected_category": (
                selected_category_id
                if selected_category_id and categories.filter(pk=selected_category_id).exists()
                else None
            ),
        },
    )


def request_quote(request):
    organization = _platform_organization()
    product_id = request.GET.get("product_id") or request.POST.get("product_id", "")
    product = None

    if organization and product_id:
        product = Product.objects.filter(
            pk=product_id,
            organization=organization,
            is_active=True,
            allow_quote_request=True,
            is_publicly_visible=True,
            show_on_website=True,
            deleted_at__isnull=True,
        ).select_related("request_category").first()

    context = {"product": product, "product_id": product.pk if product else None}
    if not organization or not product:
        context["product_error"] = (
            "This product is unavailable for quote requests. "
            "Please return to the Products page and select an available product."
        )
        return render(request, "products/request_quote.html", context)

    if request.method == "POST":
        if request.POST.get("website", "").strip():
            context["success"] = True
            return render(request, "products/request_quote.html", context)

        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        message = request.POST.get("message", "").strip()
        error = validate_website_request(name, email, phone, message)
        if error:
            context["error"] = error
        else:
            create_website_request(
                organization=organization,
                name=name,
                email=email,
                phone=phone,
                message=message,
                product=product,
            )
            context["success"] = True

    return render(request, "products/request_quote.html", context)
