import httpx
import pytest
from fastapi import HTTPException
from central.database import Database
from central.security import Security
from central.git_integrations import connect, connections, reviews
from test_memory import user


@pytest.mark.parametrize('service,repository,expected', [
    ('github', 'owner/repository', 'api.github.com'),
    ('gitlab', 'group/nested/repository', 'gitlab.com'),
])
def test_read_only_review_requests_never_return_credentials(tmp_path, service, repository, expected):
    db = Database(':memory:'); user(db, 'one'); user(db, 'two')
    security = Security(db, tmp_path)
    saved = connect(db, security, 'one', service, repository, 'private-token')
    assert 'private-token' not in str(connections(db, 'one'))
    assert connections(db, 'two') == []
    def respond(request):
        assert request.method == 'GET' and request.url.host == expected
        return httpx.Response(200, json=[{'number': 1, 'iid': 1, 'title': 'Fix', 'state': 'open'}])
    result = reviews(db, security, 'one', saved['id'], transport=httpx.MockTransport(respond))
    assert result['items'][0]['title'] == 'Fix' and result['read_only']
    with pytest.raises(HTTPException):
        reviews(db, security, 'two', saved['id'], transport=httpx.MockTransport(respond))
    db.close()


def test_remote_url_and_redirect_cannot_redirect_token(tmp_path):
    db = Database(':memory:'); user(db, 'one')
    security = Security(db, tmp_path)
    for repository in ('https://evil.example/o/r', '../private', 'owner/../repo'):
        with pytest.raises(HTTPException):
            connect(db, security, 'one', 'github', repository, 'token')
    saved = connect(db, security, 'one', 'github', 'owner/repo', 'token')
    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={'Location': 'https://evil.example'})
    with pytest.raises(HTTPException):
        reviews(db, security, 'one', saved['id'], transport=httpx.MockTransport(redirect))
    assert len(requests) == 1
    db.close()
