from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from core.permissions import bidder_required
from winners.models import Winner
from .forms import PaymentForm
from .models import Payment


@bidder_required
def submit_payment(request, winner_id):
    winner = get_object_or_404(Winner, pk=winner_id, bidder=request.user)
    if request.method == "POST":
        form = PaymentForm(request.POST, request.FILES)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.winner = winner
            payment.payer = request.user
            payment.status = Payment.Status.PENDING
            payment.save()
            messages.success(request, "Payment submitted. An admin will verify it shortly.")
            return redirect("winners:detail", pk=winner.pk)
    else:
        form = PaymentForm(initial={"amount": winner.winning_price})
    return render(request, "payments/submit_payment.html", {"form": form, "winner": winner})
