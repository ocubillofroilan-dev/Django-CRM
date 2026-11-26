import re

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_domains(value):
    """
    '@Everbest.com, everbest.ph' -> ['everbest.com', 'everbest.ph'].
    Raises ValueError (with the offending entry) if something is not a domain name.
    """
    result = []
    for part in re.split(r"[,\s;]+", value or ""):
        part = part.strip().lstrip("@").lower()
        if not part:
            continue
        if not _DOMAIN_RE.match(part):
            raise ValueError(part)
        if part not in result:
            result.append(part)
    return result


def email_domain(email):
    email = (email or "").strip().lower()
    return email.rsplit("@", 1)[-1] if "@" in email else ""