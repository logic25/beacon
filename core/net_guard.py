"""Egress guard against SSRF for URLs harvested from untrusted email/document content.

Beacon's email link-harvester follows arbitrary <a href> links from inbound mail and
downloads linked PDFs. Without a guard, a crafted link (http://169.254.169.254/latest/...,
http://127.0.0.1:6379/..., http://10.x/...) makes the server fetch cloud-metadata or
internal services — an unauthenticated SSRF once the ingest endpoints are reachable.

Control: block any URL whose host resolves to a private / loopback / link-local /
reserved IP, and re-validate EVERY redirect hop the same way (redirects are followed
manually so an allowed public host can't 302 into an internal one). We deliberately do
NOT host-allowlist: legitimate DOB links go through public redirect trackers
(GovDelivery lnks.gd → nyc.gov), so the IP-based block is the right control.

Residual: a determined DNS-rebinding attacker could resolve public at check time and
internal at connect time. That's a far more sophisticated attack than the literal
internal-URL SSRF this closes; pinning the connect IP is a possible future hardening.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5


class UnsafeURLError(Exception):
    """Raised when a URL targets a non-public / disallowed address."""


def _host_is_public(host: str) -> bool:
    """True only if EVERY IP the host resolves to is a normal public address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    return True


def _assert_safe(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    if not _host_is_public(host):
        raise UnsafeURLError(f"host resolves to a non-public address: {host!r}")


def safe_get(url: str, *, session: "requests.Session | None" = None,
             timeout: int = 15, headers: "dict | None" = None, **kw) -> requests.Response:
    """SSRF-guarded requests.get: every hop's host must resolve to a public IP.

    Redirects are followed manually (allow_redirects=False) so an allowed public host
    can't redirect into an internal one. Raises UnsafeURLError on a disallowed target.
    """
    getter = (session or requests).get
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _assert_safe(current)
        resp = getter(current, timeout=timeout, headers=headers,
                      allow_redirects=False, **kw)
        if resp.is_redirect or resp.is_permanent_redirect:
            loc = resp.headers.get("location")
            resp.close()
            if not loc:
                return resp
            current = requests.compat.urljoin(current, loc)
            continue
        return resp
    raise UnsafeURLError(f"too many redirects following {url!r}")
