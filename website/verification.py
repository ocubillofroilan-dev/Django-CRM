"""
Is this email address from one of our clients?

  verified    - a registered contact of an active client who may make requests
  known       - a registered contact, but not (yet) cleared: no company, the
                company is not an active client, or they cannot make requests
  domain      - not a registered contact, but the domain belongs to a client
  unverified  - nobody we know
  invalid     - not an email address
"""
from dataclasses import dataclass
from typing import Optional

from .models import Company, Contact
from .utils import email_domain

_TEXT = {
    "verified": (
        "Verified client contact",
        "A registered contact of an active client. Still confirm the details below before sharing anything sensitive.",
        "success",
    ),
    "known": (
        "Known contact, not cleared",
        "We know this person, but they have no active client company or are not authorized to make requests.",
        "warning",
    ),
    "domain": (
        "Client domain, unknown person",
        "The email domain belongs to a client, but this person is not a registered contact. Verify them before helping.",
        "warning",
    ),
    "unverified": (
        "Unknown sender",
        "No contact or client uses this address. Do not share account details until they are verified.",
        "danger",
    ),
    "invalid": ("Not a valid email address", "Check the address and try again.", "secondary"),
}


@dataclass
class Verification:
    email: str
    level: str
    contact: Optional[Contact] = None
    company: Optional[Company] = None

    @property
    def headline(self):
        return _TEXT[self.level][0]

    @property
    def advice(self):
        return _TEXT[self.level][1]

    @property
    def tone(self):
        return _TEXT[self.level][2]

    @property
    def is_trusted(self):
        return self.level == "verified"


def verify_sender(email):
    email = (email or "").strip().lower()
    domain = email_domain(email)
    if not domain or "." not in domain:
        return Verification(email=email, level="invalid")

    contact = Contact.objects.select_related("company").filter(email__iexact=email).first()
    if contact:
        company = contact.company
        cleared = bool(company and company.status == Company.Status.CLIENT and contact.can_request)
        return Verification(email, "verified" if cleared else "known", contact, company)

    matches = [c for c in Company.objects.filter(email_domains__icontains=domain) if domain in c.domains]
    if matches:
        matches.sort(key=lambda c: (c.status != Company.Status.CLIENT, c.name))
        return Verification(email, "domain", None, matches[0])

    return Verification(email=email, level="unverified")