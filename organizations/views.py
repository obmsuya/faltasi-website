from datetime import datetime, time
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from billing.models import Subscription, Payment
from customers.models import Customer
from business_requests.models import Department
from products.models import Product
from whatsapp.models import WhatsAppBusinessAccount
from .forms import OrganizationForm
from .models import Organization, OrganizationMember

User = get_user_model()

def platform_admin(view):
    return login_required(user_passes_test(lambda u: u.is_active and u.is_superuser)(view))

@platform_admin
def organization_list(request):
    qs = Organization.objects.all().annotate(member_count=Count("members", distinct=True), department_count=Count("departments", distinct=True))
    q = request.GET.get("q","").strip()
    status = request.GET.get("status","")
    if q: qs = qs.filter(Q(name__icontains=q)|Q(legal_name__icontains=q)|Q(email__icontains=q)|Q(phone__icontains=q)|Q(city__icontains=q))
    if status in dict(Organization.STATUS_CHOICES): qs = qs.filter(status=status)
    summary = Organization.objects.aggregate(total=Count("id"), active=Count("id",filter=Q(status="active")), pending=Count("id",filter=Q(status="pending")), inactive=Count("id",filter=Q(status="inactive")), suspended=Count("id",filter=Q(status="suspended")))
    rows=[]
    now=timezone.now()
    for org in qs.prefetch_related("subscriptions__plan"):
        sub=org.subscriptions.select_related("plan").order_by("-created_at").first()
        total=org.payments.filter(status="confirmed").aggregate(total=Sum("amount"))["total"] or Decimal("0")
        if org.payments.filter(status="pending").exists(): pay="pending"
        elif sub and sub.end_date and sub.end_date < now: pay="overdue"
        elif sub and sub.status=="trial": pay="trial"
        elif total: pay="paid"
        else: pay="unpaid"
        rows.append({"org":org,"subscription":sub,"payment_status":pay,"paid_total":total})
    page=Paginator(rows,15).get_page(request.GET.get("page"))
    return render(request,"organizations/organization_list.html",{"page_obj":page,"rows":page.object_list,"summary":summary,"q":q,"selected_status":status,"statuses":Organization.STATUS_CHOICES})

@platform_admin
def organization_create(request):
    form=OrganizationForm(request.POST or None,request.FILES or None)
    if request.method=="POST" and form.is_valid():
        with transaction.atomic():
            org=form.save()
            owner=form.cleaned_data.get("owner")
            username=(form.cleaned_data.get("new_owner_username") or "").strip()
            if username:
                owner=User.objects.create_user(username=username,email=form.cleaned_data.get("new_owner_email") or "",password=form.cleaned_data["new_owner_password"])
            if owner: OrganizationMember.objects.update_or_create(organization=org,user=owner,defaults={"role":"owner","is_active":True})
            plan=form.cleaned_data.get("plan")
            if plan:
                end=form.cleaned_data.get("trial_end_date")
                end_dt=timezone.make_aware(datetime.combine(end,time.max)) if end else None
                Subscription.objects.create(organization=org,plan=plan,status="trial",start_date=timezone.now(),trial_end_date=end_dt,end_date=end_dt)
        messages.success(request,f"{org.name} created successfully.")
        return redirect("organizations:detail",pk=org.pk)
    return render(request,"organizations/organization_form.html",{"form":form,"creating":True,"title":"Add organization"})

@platform_admin
def organization_edit(request,pk):
    org=get_object_or_404(Organization,pk=pk)
    form=OrganizationForm(request.POST or None,request.FILES or None,instance=org)
    if request.method=="POST" and form.is_valid():
        with transaction.atomic():
            org=form.save()
            owner=form.cleaned_data.get("owner")
            if owner:
                OrganizationMember.objects.filter(organization=org,role="owner").exclude(user=owner).update(role="admin")
                OrganizationMember.objects.update_or_create(organization=org,user=owner,defaults={"role":"owner","is_active":True})
        messages.success(request,"Organization updated.")
        return redirect("organizations:detail",pk=org.pk)
    return render(request,"organizations/organization_form.html",{"form":form,"organization":org,"creating":False,"title":"Edit organization"})

@platform_admin
def organization_detail(request,pk):
    org=get_object_or_404(Organization,pk=pk)
    payments=org.payments.select_related("recorded_by").order_by("-payment_date")
    return render(request,"organizations/organization_detail.html",{
        "org":org,"members":org.members.select_related("user").order_by("role","user__username"),
        "departments":Department.objects.filter(organization=org),"customers_count":org.customers.count(),
        "request_count":org.customers.aggregate(n=Count("business_requests"))["n"],
        "subscriptions":org.subscriptions.select_related("plan").order_by("-created_at"),
        "payments":payments[:20],"paid_total":payments.filter(status="confirmed").aggregate(n=Sum("amount"))["n"] or Decimal("0"),
        "wa_accounts":WhatsAppBusinessAccount.objects.filter(organization=org),
    })

@platform_admin
@require_POST
def organization_status(request,pk,status):
    org=get_object_or_404(Organization,pk=pk)
    allowed=dict(Organization.STATUS_CHOICES)
    if status not in allowed: messages.error(request,"Invalid status.")
    elif org.organization_type=="platform_owner" and status!="active": messages.error(request,"Platform owner cannot be deactivated here.")
    else:
        org.status=status
        if status=="suspended": org.suspended_at=timezone.now(); org.suspension_reason=request.POST.get("reason","").strip()
        elif status=="active": org.suspended_at=None; org.suspension_reason=""
        org.save(update_fields=["status","suspended_at","suspension_reason","updated_at"])
        messages.success(request,f"Organization status changed to {allowed[status]}.")
    return redirect("organizations:detail",pk=pk)

@platform_admin
@require_POST
def member_action(request,pk,member_id):
    org=get_object_or_404(Organization,pk=pk)
    member=get_object_or_404(OrganizationMember,pk=member_id,organization=org)
    action=request.POST.get("action")
    if member.user.is_superuser: messages.error(request,"Platform superuser membership is protected.")
    elif action=="toggle":
        member.is_active=not member.is_active; member.save(update_fields=["is_active","updated_at"])
    elif action=="remove": member.delete()
    elif action=="role":
        role=request.POST.get("role")
        if role not in dict(OrganizationMember.ROLE_CHOICES): messages.error(request,"Invalid role.")
        else:
            if role=="owner": OrganizationMember.objects.filter(organization=org,role="owner").exclude(pk=member.pk).update(role="admin")
            member.role=role; member.save(update_fields=["role","updated_at"])
    return redirect("organizations:detail",pk=pk)

@platform_admin
def organization_delete_confirm(request,pk):
    org=get_object_or_404(Organization,pk=pk)
    if org.organization_type=="platform_owner":
        messages.error(request,"The platform owner organization cannot be deleted."); return redirect("organizations:detail",pk=pk)
    return render(request,"organizations/organization_delete_confirm.html",{"org":org,"counts":{
        "memberships":org.members.count(),"departments":org.departments.count(),"customers":org.customers.count(),
        "subscriptions":org.subscriptions.count(),"payments":org.payments.count(),
        "WhatsApp accounts":org.whatsapp_business_accounts.count(),"WhatsApp numbers":org.whatsapp_phone_numbers.count(),
        "WhatsApp conversations":org.whatsapp_conversations.count(),
        "products":Product.objects.filter(category__organization=org).count(),
    }})

@platform_admin
@require_POST
def organization_delete(request,pk):
    org=get_object_or_404(Organization,pk=pk)
    if org.organization_type=="platform_owner":
        messages.error(request,"The platform owner organization cannot be deleted."); return redirect("organizations:detail",pk=pk)
    if request.POST.get("confirm_name","").strip()!=org.name:
        messages.error(request,"The name did not match. Nothing was deleted."); return redirect("organizations:detail",pk=pk)
    name=org.name
    try:
        with transaction.atomic(): org.delete()
        messages.success(request,f"{name} and its cascading organization-linked records were deleted.")
        return redirect("organizations:list")
    except Exception as exc:
        messages.error(request,f"Deletion rolled back. A protected relationship may need review. Details: {exc}")
        return redirect("organizations:detail",pk=pk)
