from django import forms
from django.core.exceptions import ValidationError

from .models import Payment


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["method", "transaction_id", "amount", "receipt"]

    def __init__(self, *args, winner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.winner = winner

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None:
            return amount
        if amount <= 0:
            raise ValidationError("The payment amount must be greater than zero.")
        if self.winner is not None and amount > self.winner.winning_price:
            raise ValidationError(
                "The payment amount can't exceed the winning price of "
                f"{self.winner.winning_price}."
            )
        return amount
