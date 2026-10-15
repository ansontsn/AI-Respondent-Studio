import ssl

import certifi
import httpx
import pytest

from survey_sim.errors import ProviderError
from survey_sim.models import ProviderConfig
from survey_sim.providers import HTTPProvider
from survey_sim.tls import create_tls_context


def test_system_trust_keeps_certificate_and_hostname_verification(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    context = create_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.cert_store_stats()["x509_ca"] > 0


def test_explicit_ca_is_respected_and_invalid_ca_fails_closed(monkeypatch,tmp_path):
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    context = create_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    with pytest.raises(ProviderError,match="憑證設定無法載入"):
        create_tls_context()


def test_certificate_error_is_not_retried_or_reported_as_timeout():
    calls, records = [], []
    def fail(request):
        calls.append(request)
        # Some HTTPX backends retain only the OpenSSL message.
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",request=request)
    provider = HTTPProvider(ProviderConfig(provider="deepseek",model="test",retries=2,request_interval=0),
        "unit-test-secret",records.append,httpx.MockTransport(fail))
    with pytest.raises(ProviderError,match="HTTPS 憑證驗證失敗") as error:
        provider.generate("connection",{},"JSON")
    assert len(calls)==1 and [r["status"] for r in records]==["tls_error"]
    assert "unit-test-secret" not in str(error.value)


@pytest.mark.parametrize("error_type,word",[(httpx.ReadTimeout,"請求逾時"),(httpx.ConnectError,"無法建立或維持")])
def test_other_connection_errors_remain_distinct(error_type,word,monkeypatch):
    monkeypatch.setattr("survey_sim.providers.time.sleep",lambda _:None)
    calls,records=[],[]
    def fail(request):
        calls.append(request)
        raise error_type("test transport failure",request=request)
    provider=HTTPProvider(ProviderConfig(provider="deepseek",model="test",retries=1,request_interval=0),
        "test-secret",records.append,httpx.MockTransport(fail))
    with pytest.raises(ProviderError,match=word):
        provider.generate("connection",{},"JSON")
    assert len(calls)==2 and len(records)==2
