from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException

from central.reference_search import search, validate_query


def test_search_returns_only_valid_public_https_citations():
    html = """
    <a class="result__a" href="https://docs.example.dev/start">Official docs</a>
    <a class="result__snippet">Read the official guide.</a>
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2Fdocs">
      Python docs
    </a>
    <a class="result__snippet">Python documentation.</a>
    <a class="result__a" href="http://insecure.example/">Insecure</a>
    <a class="result__a" href="javascript:alert(1)">Unsafe</a>
    <a class="result__a" href="https://user:pass@private.example/">Private</a>
    """
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=html, request=request)

    result = search(
        'Python official documentation',
        transport=httpx.MockTransport(respond))

    assert len(requests) == 1
    assert requests[0].url.host == 'html.duckduckgo.com'
    assert parse_qs(urlsplit(str(requests[0].url)).query)['q'] == [
        'Python official documentation']
    assert [item['url'] for item in result['references']] == [
        'https://docs.example.dev/start', 'https://python.org/docs']
    assert result['references'][0]['title'] == 'Official docs'
    assert result['references'][0]['snippet'] == 'Read the official guide.'


@pytest.mark.parametrize('query', ['', 'ab', 'x' * 181, 'unsafe\nquery'])
def test_search_rejects_invalid_queries(query):
    with pytest.raises(HTTPException):
        validate_query(query)


def test_search_fails_explicitly_on_http_error():
    def respond(request):
        return httpx.Response(503, request=request)

    with pytest.raises(HTTPException) as error:
        search('React official docs', transport=httpx.MockTransport(respond))
    assert error.value.status_code == 502
