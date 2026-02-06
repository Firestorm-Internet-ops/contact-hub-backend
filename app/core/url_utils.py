def normalize_site_url(url: str) -> str:
    return url.strip().lower().strip("/")