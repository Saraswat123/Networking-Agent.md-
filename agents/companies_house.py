"""
Company registry lookups — free sources by country.

UK:  Companies House API — 600 req/5min, free key at find-and-update.company-information.service.gov.uk/get-started
UAE: Dubai DED open data — no auth needed
SG:  ACRA BizFile — basic search free
AU:  ASIC company search — free

Currently implemented: UK (full), others return web search URL.
"""

import os
import requests
from typing import Optional

BASE = "https://api.company-information.service.gov.uk"


def _headers() -> dict:
    key = os.environ.get("UK_CH_API_KEY", "")
    if not key:
        return {}
    # Companies House uses HTTP Basic Auth with API key as username, blank password
    import base64
    token = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def search_company(name: str, limit: int = 5) -> list[dict]:
    """Search UK Companies House by company name."""
    resp = requests.get(
        f"{BASE}/search/companies",
        params={"q": name, "items_per_page": limit},
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    items = resp.json().get("items", [])
    return [
        {
            "name": i.get("title"),
            "company_number": i.get("company_number"),
            "status": i.get("company_status"),
            "type": i.get("company_type"),
            "incorporated": i.get("date_of_creation"),
            "address": i.get("address", {}).get("address_line_1", ""),
            "postcode": i.get("address", {}).get("postal_code", ""),
            "sic_codes": i.get("sic_codes", []),
            "ch_url": f"https://find-and-update.company-information.service.gov.uk/company/{i.get('company_number')}",
        }
        for i in items
    ]


def get_company_profile(company_number: str) -> dict:
    """Get full company profile: accounts, status, accounts date."""
    key = os.environ.get("UK_CH_API_KEY", "")
    if not key:
        return {"error": "UK_CH_API_KEY not set — needed for company profile"}
    resp = requests.get(
        f"{BASE}/company/{company_number}",
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code != 200:
        return {}
    d = resp.json()
    return {
        "name": d.get("company_name"),
        "status": d.get("company_status"),
        "type": d.get("type"),
        "incorporated": d.get("date_of_creation"),
        "last_accounts": d.get("accounts", {}).get("last_accounts", {}).get("made_up_to"),
        "next_accounts_due": d.get("accounts", {}).get("next_accounts", {}).get("due_on"),
        "sic_codes": d.get("sic_codes", []),
        "jurisdiction": d.get("jurisdiction"),
        "registered_address": d.get("registered_office_address", {}),
    }


def get_officers(company_number: str) -> list[dict]:
    """Get directors/officers — useful for finding decision-maker names."""
    key = os.environ.get("UK_CH_API_KEY", "")
    if not key:
        return []
    resp = requests.get(
        f"{BASE}/company/{company_number}/officers",
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    items = resp.json().get("items", [])
    return [
        {
            "name": o.get("name"),
            "role": o.get("officer_role"),
            "appointed": o.get("appointed_on"),
            "resigned": o.get("resigned_on"),
            "nationality": o.get("nationality"),
            "occupation": o.get("occupation"),
        }
        for o in items
        if not o.get("resigned_on")  # active only
    ]


def research_company_global(company_name: str, country: str = "uk") -> dict:
    """Route to correct registry by country."""
    country = country.lower().strip()
    uk_variants = {"uk", "united kingdom", "england", "scotland", "wales", "gb"}
    if country in uk_variants:
        return research_uk_company(company_name)

    # For other regions: return registry link for manual lookup
    registry_links = {
        "uae": f"https://www.dubaided.gov.ae/en/Pages/CompanySearch.aspx?q={company_name.replace(' ', '+')}",
        "dubai": f"https://www.dubaided.gov.ae/en/Pages/CompanySearch.aspx?q={company_name.replace(' ', '+')}",
        "sg": f"https://www.bizfile.gov.sg/ngbbizfileinternet/faces/oracle/webcenter/portalapp/pages/BizFileInternet.jspx",
        "singapore": f"https://www.bizfile.gov.sg",
        "au": f"https://connectonline.asic.gov.au/RegistrySearch/faces/landing/SearchRegisters.jspx",
        "australia": f"https://connectonline.asic.gov.au",
        "us": f"https://www.sec.gov/cgi-bin/browse-edgar?company={company_name.replace(' ', '+')}&CIK=&type=&dateb=&owner=include&count=40&search_text=&action=getcompany",
        "de": f"https://www.handelsregister.de/rp_web/search.do",
        "germany": f"https://www.handelsregister.de",
        "nl": f"https://www.kvk.nl/en/search/?q={company_name.replace(' ', '+')}",
        "netherlands": f"https://www.kvk.nl/en/search/?q={company_name.replace(' ', '+')}",
        "fr": f"https://www.societe.com/cgi-bin/search?champs={company_name.replace(' ', '+')}",
        "france": f"https://www.societe.com/cgi-bin/search?champs={company_name.replace(' ', '+')}",
        "sa": f"https://cr.mc.gov.sa/en/pages/commercial-registry-search.aspx",
        "saudi": f"https://cr.mc.gov.sa",
        "in": f"https://www.mca.gov.in/mcafoportal/viewCompanyMasterData.do",
        "india": f"https://www.mca.gov.in",
    }
    link = registry_links.get(country, f"https://www.google.com/search?q={company_name.replace(' ', '+')}+company+registration+{country}")
    return {
        "source": f"Registry link ({country})",
        "company": {"name": company_name},
        "registry_url": link,
        "note": f"Full API for {country} not yet integrated. Use link above for manual lookup.",
    }


def research_uk_company(company_name: str) -> dict:
    """Full background lookup: profile + officers. Single entry point."""
    results = search_company(company_name, limit=1)
    if not results:
        return {"error": f"Not found in Companies House: {company_name}"}

    company = results[0]
    cn = company["company_number"]

    profile = get_company_profile(cn)
    officers = get_officers(cn)

    # Decision makers = directors + CEO/MD
    decision_makers = [
        o for o in officers
        if any(r in (o.get("role") or "") for r in ["director", "secretary", "managing"])
    ]

    return {
        "source": "UK Companies House",
        "company": company,
        "profile": profile,
        "active_officers": officers,
        "decision_makers": decision_makers[:5],
        "incorporated_years": _years_since(company.get("incorporated")),
    }


def _years_since(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    from datetime import datetime
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (datetime.now() - d).days // 365
    except Exception:
        return None
