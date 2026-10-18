import base64
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse
import httpx
from sqlalchemy.orm import Session

from app.models import OAuthToken
from app.settings_store import get_effective_settings, update_settings

YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def extract_code_from_input(raw_input: str) -> str:
    """
    Accepts either a raw Yahoo authorization code OR a full redirected callback URL
    (e.g. 'https://localhost:8000/?code=abc123' or 'https://localhost:8000/api/auth/yahoo/callback?code=abc123')
    and extracts the code parameter cleanly.
    """
    cleaned = raw_input.strip()
    if "code=" in cleaned:
        try:
            parsed = urlparse(cleaned)
            qs = parse_qs(parsed.query)
            if "code" in qs and qs["code"]:
                return qs["code"][0].strip()
        except Exception:
            pass
        after_code = cleaned.split("code=", 1)[1]
        return after_code.split("&", 1)[0].strip()
    return cleaned


def extract_cookie_from_input(raw_input: str) -> str:
    """
    Accepts either:
    1. A full 'Copy as cURL' command from Browser DevTools (-b '...' or -H 'cookie: ...')
    2. A 'Cookie: ...' header line
    3. A raw semicolon-separated cookie string ('B=...; A3=...; T=...')
    and returns the clean Cookie header value.
    """
    text = raw_input.strip()
    if not text:
        return ""

    # Match -b '...' or --cookie '...' in Copy as cURL
    m_b = re.search(r"""(?:-b|--cookie)\s+(['"])(.*?)\1""", text, re.DOTALL)
    if m_b:
        return m_b.group(2).strip()

    # Match -H 'cookie: ...' or -H "Cookie: ..." in Copy as cURL
    m_h = re.search(r"""-H\s+(['"])cookie:\s*(.*?)\1""", text, re.IGNORECASE | re.DOTALL)
    if m_h:
        return m_h.group(2).strip()

    # Match leading 'Cookie:' prefix
    if text.lower().startswith("cookie:"):
        return text.split(":", 1)[1].strip()

    return text


def get_oauth_status(db: Session) -> dict:
    eff = get_effective_settings(db)
    token = db.query(OAuthToken).filter(OAuthToken.provider == "yahoo").first()
    has_credentials = bool(eff.get("yahoo_client_id") and eff.get("yahoo_client_secret"))
    has_oauth_token = bool(token and token.refresh_token)
    has_cookie = bool((eff.get("yahoo_cookie") or "").strip())
    is_expired = bool(token and token.expires_at and token.expires_at < time.time())
    return {
        "configured": has_credentials or has_cookie,
        "connected": has_cookie or has_oauth_token,
        "auth_mode": "cookie" if has_cookie else ("oauth" if has_oauth_token else "none"),
        "has_cookie": has_cookie,
        "has_oauth_token": has_oauth_token,
        "token_expired": is_expired,
        "expires_at": token.expires_at if token else None,
        "yahoo_guid": token.yahoo_guid if token else "",
        "redirect_uri": eff.get("yahoo_redirect_uri"),
    }


def save_yahoo_cookie(db: Session, raw_cookie_or_curl: str) -> str:
    cookie_str = extract_cookie_from_input(raw_cookie_or_curl)
    if not cookie_str or "=" not in cookie_str:
        raise ValueError(
            "Could not find a valid Cookie string. Paste either 'Copy as cURL' of any request on football.fantasysports.yahoo.com or the raw Cookie header value."
        )
    update_settings(db, {"yahoo_cookie": cookie_str})
    return cookie_str


async def build_yahoo_authorize_url(db: Session) -> str:
    eff = get_effective_settings(db)
    client_id = (eff.get("yahoo_client_id") or "").strip()
    redirect_uri = (eff.get("yahoo_redirect_uri") or "https://localhost:8000").strip()

    if not client_id:
        raise ValueError(
            "Yahoo Client ID is empty. Please enter your Yahoo Client ID and Client Secret first."
        )

    chosen_scope = "fspt-r"
    try:
        test_params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "fspt-w",
        }
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as client:
            resp = await client.get(f"{YAHOO_AUTH_URL}?{urlencode(test_params)}")
            loc = resp.headers.get("location", "")
            if "invalid_scope" not in loc:
                chosen_scope = "fspt-w"
    except Exception:
        chosen_scope = "fspt-r"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": chosen_scope,
        "prompt": "consent",
        "language": "en-us",
    }
    return f"{YAHOO_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_token(db: Session, code_or_url: str) -> OAuthToken:
    eff = get_effective_settings(db)
    client_id = (eff.get("yahoo_client_id") or "").strip()
    client_secret = (eff.get("yahoo_client_secret") or "").strip()
    redirect_uri = (eff.get("yahoo_redirect_uri") or "https://localhost:8000").strip()

    if not client_id or not client_secret:
        raise ValueError("Yahoo Client ID and Client Secret must be configured first.")

    code = extract_code_from_input(code_or_url)
    if not code:
        raise ValueError("No authorization code found in input.")

    basic_token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(YAHOO_TOKEN_URL, headers=headers, data=data)
        if resp.status_code >= 400:
            detail = resp.text
            raise ValueError(
                f"Yahoo token exchange failed ({resp.status_code}): {detail}. "
                f"Verify that your Redirect URI ('{redirect_uri}') matches your Yahoo App exactly."
            )
        payload = resp.json()

    return _save_token_payload(db, payload)


async def get_valid_access_token(db: Session) -> str:
    token = db.query(OAuthToken).filter(OAuthToken.provider == "yahoo").first()
    if not token or not token.refresh_token:
        raise RuntimeError("Yahoo OAuth is not connected yet.")

    if token.access_token and token.expires_at > time.time() + 120:
        return token.access_token

    eff = get_effective_settings(db)
    client_id = (eff.get("yahoo_client_id") or "").strip()
    client_secret = (eff.get("yahoo_client_secret") or "").strip()
    redirect_uri = (eff.get("yahoo_redirect_uri") or "https://localhost:8000").strip()

    basic_token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "redirect_uri": redirect_uri,
        "refresh_token": token.refresh_token,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(YAHOO_TOKEN_URL, headers=headers, data=data)
        resp.raise_for_status()
        payload = resp.json()

    updated = _save_token_payload(db, payload)
    return updated.access_token


def _save_token_payload(db: Session, payload: dict) -> OAuthToken:
    token = db.query(OAuthToken).filter(OAuthToken.provider == "yahoo").first()
    if not token:
        token = OAuthToken(provider="yahoo")
        db.add(token)

    token.access_token = payload.get("access_token", "")
    if payload.get("refresh_token"):
        token.refresh_token = payload["refresh_token"]
    token.token_type = payload.get("token_type", "bearer")
    expires_in = float(payload.get("expires_in", 3600))
    token.expires_at = time.time() + expires_in
    token.yahoo_guid = payload.get("xoauth_yahoo_guid", token.yahoo_guid or "")
    db.commit()
    db.refresh(token)
    return token
