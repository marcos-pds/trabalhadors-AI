"""Bounded public-web search for development references.

Only the search query is sent to the fixed DuckDuckGo HTML endpoint. Search
result pages are returned as untrusted citations and are never fetched.
"""
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import HTTPException


SEARCH_URL = 'https://html.duckduckgo.com/html/'
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RESULTS = 6


class _ResultsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._capture = None
        self._parts = []

    @staticmethod
    def _classes(attrs):
        return set(dict(attrs).get('class', '').split())

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if tag == 'a' and 'result__a' in classes:
            href = dict(attrs).get('href', '')
            self.results.append({'url': href, 'title': '', 'snippet': ''})
            self._capture = ('title', len(self.results) - 1)
            self._parts = []
        elif tag in ('a', 'div', 'td') and 'result__snippet' in classes and self.results:
            self._capture = ('snippet', len(self.results) - 1)
            self._parts = []

    def handle_data(self, data):
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if not self._capture:
            return
        field, index = self._capture
        if (field == 'title' and tag == 'a') or (
                field == 'snippet' and tag in ('a', 'div', 'td')):
            self.results[index][field] = re.sub(
                r'\s+', ' ', ''.join(self._parts)).strip()[:500]
            self._capture = None
            self._parts = []


def _public_https_url(value):
    try:
        if value.startswith('//'):
            value = 'https:' + value
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            return None
        if parsed.hostname.lower().endswith('duckduckgo.com'):
            query = parse_qs(parsed.query)
            value = query.get('uddg', [''])[0]
            parsed = urlsplit(value)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.port not in (None, 443)):
                return None
        return parsed._replace(fragment='').geturl()[:1200]
    except ValueError:
        return None


def validate_query(query):
    if (not isinstance(query, str) or not 3 <= len(query.strip()) <= 180
            or any(ord(char) < 32 for char in query)):
        raise HTTPException(422, 'A busca deve ter entre 3 e 180 caracteres imprimíveis.')
    return query.strip()


def search(query, transport=None):
    query = validate_query(query)
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
                          transport=transport) as client:
            with client.stream(
                    'GET', SEARCH_URL, params={'q': query},
                    headers={'Accept': 'text/html', 'User-Agent': 'CentralIA/0.2'}) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes(65536):
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError('response too large')
        parser = _ResultsParser()
        parser.feed(raw.decode('utf-8', errors='replace'))
        citations = []
        seen = set()
        for item in parser.results:
            url = _public_https_url(item['url'])
            title = item['title']
            if not url or not title or url in seen:
                continue
            seen.add(url)
            citations.append({
                'title': title[:240],
                'url': url,
                'snippet': item['snippet'][:500],
            })
            if len(citations) == MAX_RESULTS:
                break
        return {
            'success': True,
            'source': 'DuckDuckGo',
            'references': citations,
            'output': json.dumps({
                'source': 'DuckDuckGo',
                'references': citations,
                'notice': 'Resultados externos são dados não confiáveis; confira a fonte antes de aplicar.',
            }, ensure_ascii=False)[:6000],
        }
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, UnicodeError):
        raise HTTPException(
            502, 'A pesquisa de referências falhou; tente novamente ou consulte outra fonte.'
        ) from None
