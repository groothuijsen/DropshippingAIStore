"""Marketing forms (T-155 early-access, T-159 uninstall feedback)."""

from django import forms

from .models import UninstallFeedback


class EarlyAccessForm(forms.Form):
    email = forms.EmailField(
        label='E-mail',
        widget=forms.EmailInput(attrs={'placeholder': 'jouw@bedrijf.nl', 'required': True}),
    )
    shop_domain = forms.CharField(
        required=False,
        label='Shop-domein (optioneel)',
        widget=forms.TextInput(attrs={'placeholder': 'jouwshop.nl'}),
    )
    lang = forms.ChoiceField(choices=[('en', 'English'), ('nl', 'Nederlands')], initial='en')
    consent = forms.BooleanField(
        required=True,
        label='Ik ga akkoord met het privacybeleid en ontvang graag updates over Mosaiq.',
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot


class UninstallFeedbackForm(forms.ModelForm):
    class Meta:
        model = UninstallFeedback
        fields = ['email', 'shop_domain', 'reason', 'comment', 'lang']
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'jouw@bedrijf.nl'}),
            'shop_domain': forms.TextInput(attrs={'placeholder': 'jouwshop.nl'}),
            'comment': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Vertel ons meer (optioneel)'}),
            'lang': forms.HiddenInput,
        }
