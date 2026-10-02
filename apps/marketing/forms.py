from django import forms


class EarlyAccessForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Email")
    shop_domain = forms.CharField(max_length=200, required=False, label="Shop domain (optional)")
    lang = forms.ChoiceField(choices=[("en", "English"), ("nl", "Nederlands")], initial="en")
    consent = forms.BooleanField(required=True, label="Yes, email me about Mosaiq's early access and launch. I can unsubscribe at any time.")
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot
