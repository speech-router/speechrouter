import pytest

from speechrouter_gateway.config import Settings
from speechrouter_gateway.protocol.events import Code
from speechrouter_gateway.router import Catalog, ResolveError, StreamRequest, resolve_stream

CATALOG = Catalog.load()


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, deepgram_api_key="dg_test", **kw)


def test_resolves_known_model():
    attempt = resolve_stream("deepgram/nova-3", StreamRequest(), _settings(), CATALOG)
    assert attempt.slug == "deepgram/nova-3"
    assert attempt.config.model == "nova-3"
    adapter = attempt.build()
    assert adapter.name == "deepgram"


@pytest.mark.parametrize("slug", ["nova-3", "nosuch/model-x", "deepgram/nova-99"])
def test_unknown_slugs_rejected(slug):
    with pytest.raises(ResolveError) as err:
        resolve_stream(slug, StreamRequest(), _settings(), CATALOG)
    assert err.value.code == Code.model_not_found


def test_unsupported_encoding_rejected():
    with pytest.raises(ResolveError) as err:
        resolve_stream(
            "deepgram/nova-3", StreamRequest(encoding="speex-nb"), _settings(), CATALOG
        )
    assert err.value.code == Code.unsupported_encoding


def test_missing_credentials_rejected():
    plain = Settings(_env_file=None)  # no deepgram key
    with pytest.raises(ResolveError) as err:
        resolve_stream("deepgram/nova-3", StreamRequest(), plain, CATALOG)
    assert err.value.code == Code.invalid_request
    assert "deepgram" in err.value.message
