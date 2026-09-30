"""Support forms — contact form for merchants.

See docs/09-ui-screens.md (GET /app/support/).
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class ContactForm(forms.Form):
    """Contact form — sends email to support."""

    subject = forms.CharField(
        label=_("Onderwerp / Subject"),
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Onderwerp / Subject"),
            }
        ),
    )
    message = forms.CharField(
        label=_("Bericht / Message"),
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": _("Beschrijf uw vraag / Describe your question"),
            }
        ),
    )
    shop_domain = forms.CharField(
        label=_("Winkel / Shop"),
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "uw-winkel.myshopify.com",
            }
        ),
    )

    def clean_message(self):
        message = self.cleaned_data.get("message", "")
        if len(message) < 10:
            raise ValidationError(_("Bericht te kort / Message too short"))
        return message
