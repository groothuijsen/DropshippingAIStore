from django.conf import settings


def marketing_company(request):
    """Company details for footer + legal pages (env-driven, T-156)."""
    keys = (
        ("legal_name", "MARKETING_LEGAL_NAME"),
        ("address", "MARKETING_ADDRESS"),
        ("reg_no", "MARKETING_REG_NO"),
        ("vat_id", "MARKETING_VAT_ID"),
        ("email", "MARKETING_CONTACT_EMAIL"),
        ("hosting_provider", "MARKETING_HOSTING_PROVIDER"),
        ("email_provider", "MARKETING_EMAIL_PROVIDER"),
        ("breach_hours", "MARKETING_BREACH_HOURS"),
    )
    company = {name: getattr(settings, attr, '') for name, attr in keys}
    line = " · ".join(v for v in (
        company["legal_name"], company["address"],
        (f"KvK {company['reg_no']}" if company["reg_no"] else ""),
        (f"VAT {company['vat_id']}" if company["vat_id"] else ""),
        company["email"],
    ) if v)
    return {"marketing_company": company, "company_line": line}
