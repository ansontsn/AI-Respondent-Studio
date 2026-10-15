"""Verified HTTPS using OS trust plus public CAs, without altering machine settings."""
import os
import ssl

import certifi

from .errors import ProviderError


def create_tls_context():
    try:
        cafile = os.environ.get("SSL_CERT_FILE") or None
        capath = os.environ.get("SSL_CERT_DIR") or None
        if cafile or capath:
            # An explicit CA configuration is authoritative; do not silently
            # replace a missing file or widen it to other certificate stores.
            return ssl.create_default_context(cafile=cafile, capath=capath)
        context = ssl.create_default_context()
        # Python loads Windows CA/ROOT stores through load_default_certs.
        # Also retain the public CA bundle used by HTTPX on other platforms.
        context.load_verify_locations(cafile=certifi.where())
        return context
    except (OSError, ssl.SSLError) as exc:
        raise ProviderError("HTTPS 憑證設定無法載入。請檢查 SSL_CERT_FILE / SSL_CERT_DIR 與受信任 CA 檔案；請勿關閉憑證驗證。") from exc


def certificate_failure(error):
    seen = set()
    pending = [error]
    while pending:
        exc = pending.pop()
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLCertVerificationError) or "certificate_verify_failed" in str(exc).lower() or "certificate verify failed" in str(exc).lower():
            return True
        pending.extend([exc.__cause__, exc.__context__])
    return False
