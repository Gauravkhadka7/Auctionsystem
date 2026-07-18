from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404

from accounts.forms import VerificationDocumentForm
from accounts.models import Profile
from core.permissions import bidder_required
from .models import Winner


def winners_public_list(request):
    winners = Winner.objects.select_related("product", "bidder").filter(is_delivered=True) | \
        Winner.objects.select_related("product", "bidder").filter(is_payment_verified=True)
    winners = winners.distinct().order_by("-created_at")
    paginator = Paginator(winners, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "winners/winners_list.html", {"page_obj": page_obj})


@bidder_required
def my_wins(request):
    wins = Winner.objects.filter(bidder=request.user).select_related("product")
    return render(request, "winners/my_wins.html", {"wins": wins})


@login_required
def winner_detail(request, pk):
    winner = get_object_or_404(Winner, pk=pk)
    if request.user != winner.bidder and not request.user.is_admin_role:
        messages.error(request, "You don't have access to that record.")
        return redirect("core:dashboard_redirect")
    return render(request, "winners/winner_detail.html", {"winner": winner})


@bidder_required
def submit_verification(request, pk):
    winner = get_object_or_404(Winner, pk=pk, bidder=request.user)
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = VerificationDocumentForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            winner.is_verification_submitted = True
            winner.save(update_fields=["is_verification_submitted"])
            messages.success(request, "Verification documents submitted for admin review.")
            return redirect("winners:detail", pk=winner.pk)
    else:
        form = VerificationDocumentForm(instance=profile)
    return render(request, "winners/submit_verification.html", {"form": form, "winner": winner})
