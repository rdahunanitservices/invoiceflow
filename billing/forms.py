from django import forms

from core.validators import normalize_abn

from .models import Client, Payment


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "email", "abn", "payment_terms_days"]
        labels = {"payment_terms_days": "Payment terms (days)"}

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        self.org = org

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        # organization isn't a form field, so the model's unique check can't see it.
        if Client.objects.for_org(self.org).filter(name__iexact=name).exists():
            raise forms.ValidationError("You already have a client with this name.")
        return name

    def clean_abn(self):
        return normalize_abn(self.cleaned_data["abn"])

    def save(self, commit=True):
        self.instance.organization = self.org
        return super().save(commit)


class InvoiceForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.none(), empty_label="Choose a client")
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Leave empty to use the client's payment terms.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        # Only this organisation's clients are valid choices; any other id fails validation.
        self.fields["client"].queryset = Client.objects.for_org(org)


class LineForm(forms.Form):
    description = forms.CharField(max_length=300)
    quantity = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01, initial=1)
    unit_price = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    taxable = forms.BooleanField(required=False, initial=True, label="GST")


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "method", "reference"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}
