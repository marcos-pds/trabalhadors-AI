import json
import httpx
import pytest
from fastapi import HTTPException
from central.database import Database
from central.security import Security
from central.git_integrations import connect, reviews
from central import git_change_plans as plans
from test_memory import user


@pytest.fixture
def setup(tmp_path):
    db = Database(':memory:'); user(db, 'alice'); user(db, 'bob')
    security = Security(db, tmp_path)
    yield db, security
    db.close()


def remote(service='github', moved=False, timeout=False):
    requests = []
    def respond(request):
        requests.append(request)
        if request.method == 'GET':
            branch = request.url.path.rsplit('/', 1)[-1]
            sha = ('b' if branch == 'main' else 'c' if moved else 'a') * 40
            return httpx.Response(200, json={'commit': {'sha': sha, 'id': sha}})
        if timeout:
            raise httpx.ReadTimeout('response unavailable', request=request)
        payload = json.loads(request.content)
        assert payload.get('draft') is True if service == 'github' else payload['title'].startswith('Draft: ')
        assert '<!-- central-plan:' in payload.get('body', payload.get('description'))
        assert request.url.path.endswith('/pulls' if service == 'github' else '/merge_requests')
        return httpx.Response(201, json={'number': 7, 'iid': 7, 'draft': True, 'sha': 'a' * 40,
                                        'head': {'sha': 'a' * 40}, 'base': {'sha': 'b' * 40},
                                        'diff_refs': {'start_sha': 'b' * 40}})
    return requests, httpx.MockTransport(respond)


@pytest.mark.parametrize('service', ['github', 'gitlab'])
def test_planning_only_reads_then_single_approval_creates_one_draft(setup, service):
    db, security = setup
    connection = connect(db, security, 'alice', service, 'owner/repo', 'private-token')
    requests, transport = remote(service)
    plan = plans.create(db, security, 'alice', connection['id'], 'feature', 'main', 'Fix', 'Description', transport)
    assert all(req.method == 'GET' for req in requests)
    assert 'private-token' not in json.dumps(plan) and 'connection_fingerprint' not in plan
    result = plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], transport)
    assert result['state'] == 'completed' and result['result']['draft']
    assert result['result']['requires_review'] is False
    with pytest.raises(HTTPException) as error:
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], transport)
    assert error.value.status_code == 409
    assert len([req for req in requests if req.method == 'POST']) == 1


def test_other_user_wrong_confirmation_expiry_and_rotated_token_cannot_publish(setup):
    db, security = setup
    connection = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    requests, transport = remote()
    plan = plans.create(db, security, 'alice', connection['id'], 'feature', 'main', 'Fix', transport=transport)
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'bob', plan['id'], plan['confirmation'], transport)
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], '0' * 64, transport)
    db.execute("UPDATE git_change_plans SET expires_at='2000-01-01' WHERE id=?", (plan['id'],))
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], transport)
    plan = plans.create(db, security, 'alice', connection['id'], 'feature', 'main', 'Fix', transport=transport)
    connect(db, security, 'alice', 'github', 'owner/repo', 'new-token')
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], transport)
    assert not any(req.method == 'POST' for req in requests)


def test_branch_drift_blocks_write_and_requires_new_approval(setup):
    db, security = setup
    connection = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    _, original = remote()
    plan = plans.create(db, security, 'alice', connection['id'], 'feature', 'main', 'Fix', transport=original)
    requests, changed = remote(moved=True)
    with pytest.raises(HTTPException) as error:
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], changed)
    assert error.value.status_code == 409
    assert plans.status(db, 'alice', plan['id'])['state'] == 'failed'
    assert not any(req.method == 'POST' for req in requests)


def test_post_timeout_is_uncertain_and_is_never_automatically_retried(setup):
    db, security = setup
    connection = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    requests, transport = remote(timeout=True)
    plan = plans.create(db, security, 'alice', connection['id'], 'feature', 'main', 'Fix', transport=transport)
    for _ in range(2):
        with pytest.raises(HTTPException):
            plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], transport)
    assert plans.status(db, 'alice', plan['id'])['state'] == 'uncertain'
    assert len([req for req in requests if req.method == 'POST']) == 1


def test_pagination_never_follows_external_link_or_forwards_credentials(setup):
    db, security = setup
    connection = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    requested = []
    def respond(request):
        requested.append(request)
        assert request.url.host == 'api.github.com'
        return httpx.Response(200, json=[], headers={'Link': '<https://evil.example>; rel="next"'})
    result = reviews(db, security, 'alice', connection['id'], transport=httpx.MockTransport(respond), page=2)
    assert result['next_page'] == 3 and result['previous_page'] == 1
    assert len(requested) == 1 and requested[0].url.params['page'] == '2'
    with pytest.raises(HTTPException):
        reviews(db, security, 'alice', connection['id'], page=101)


@pytest.mark.parametrize('branch', ['../main', 'feature?x=y', 'feature@{1}', 'feature.lock', 'feature//a'])
def test_invalid_branch_is_rejected_before_any_network_request(branch):
    with pytest.raises(HTTPException):
        plans.validate_branch(branch)


def test_two_approvals_cannot_create_two_remote_drafts(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    db, security = setup
    connection = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    requests, transport = remote()
    plan = plans.create(db, security, 'alice', connection['id'], 'feature', 'main', 'Fix', transport=transport)
    barrier = threading.Barrier(2)
    original = db.execute
    def execute(query, args=()):
        if query.startswith("UPDATE git_change_plans SET state='executing'"):
            barrier.wait(timeout=3)
        return original(query, args)
    monkeypatch.setattr(db, 'execute', execute)
    def approve(_):
        try:
            return plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], transport)['state']
        except HTTPException as exc:
            assert exc.status_code == 409
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, [1, 2])) == ['completed', 'conflict']
    assert len([request for request in requests if request.method == 'POST']) == 1



@pytest.mark.parametrize('service', ['github', 'gitlab'])
def test_read_only_reconciliation_finds_exact_remote_draft_without_post(setup, service):
    db, security = setup
    row = connect(db, security, 'alice', service, 'owner/repo', 'private-token')
    _, initial = remote(service, timeout=True)
    plan = plans.create(db, security, 'alice', row['id'], 'feature', 'main',
                        'Reconciliar', 'Descrição', initial)
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], initial)
    assert plans.status(db, 'alice', plan['id'])['state'] == 'uncertain'
    seen = []

    def respond(request):
        seen.append(request)
        assert request.method == 'GET'
        assert request.url.host == ('api.github.com' if service == 'github' else 'gitlab.com')
        assert request.url.params['state'] == 'all'
        assert request.url.params['per_page'] == '100'
        marker = '<!-- central-plan:' + plan['id'] + ' -->'
        if service == 'github':
            return httpx.Response(200, json=[
                {'number': 19, 'body': 'Descrição\n' + marker, 'draft': True,
                 'head': {'ref': 'feature', 'sha': 'a' * 40},
                 'base': {'ref': 'main', 'sha': 'b' * 40}},
            ])
        return httpx.Response(200, json=[
            {'iid': 27, 'description': 'Descrição\n' + marker,
             'source_branch': 'feature', 'target_branch': 'main',
             'sha': 'a' * 40, 'diff_refs': {'start_sha': 'b' * 40},
             'work_in_progress': True},
        ])
    outcome = plans.reconcile(db, security, 'alice', plan['id'],
                              httpx.MockTransport(respond))
    assert outcome['state'] == 'completed'
    assert outcome['reconciliation'] == 'unique_remote_match'
    assert outcome['result']['draft'] is True
    assert outcome['result']['requires_review'] is False
    assert len(seen) == 1
    assert plans.reconcile(db, security, 'alice', plan['id'],
                           httpx.MockTransport(respond))['reconciliation'] == 'already_confirmed'
    assert len(seen) == 1


def test_reconcile_never_interprets_absence_as_proof_and_never_writes(setup):
    db, security = setup
    conn = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    _, initial = remote(timeout=True)
    plan = plans.create(db, security, 'alice', conn['id'], 'feature', 'main',
                        'Feature', transport=initial)
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], initial)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[{'number': 3, 'body': 'Outro PR'}])
    outcome = plans.reconcile(db, security, 'alice', plan['id'],
                              httpx.MockTransport(respond))
    assert outcome['state'] == 'uncertain'
    assert outcome['reconciliation'] == 'not_found'
    assert len(requests) == 1
    assert requests[0].method == 'GET'
    assert plans.status(db, 'alice', plan['id'])['state'] == 'uncertain'


def test_reconcile_duplicate_markers_remain_uncertain(setup):
    db, security = setup
    conn = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    _, initial = remote(timeout=True)
    plan = plans.create(db, security, 'alice', conn['id'], 'feature', 'main',
                        'Feature', transport=initial)
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], initial)
    marker = '<!-- central-plan:' + plan['id'] + ' -->'
    def respond(request):
        return httpx.Response(200, json=[
            {'number': number, 'body': marker, 'head': {'ref':'feature','sha':'a'*40},
             'base': {'ref':'main','sha':'b'*40}, 'draft':True}
            for number in (15,16)])
    outcome=plans.reconcile(db,security,'alice',plan['id'],httpx.MockTransport(respond))
    assert outcome['reconciliation'] == 'ambiguous'
    assert outcome['state'] == 'uncertain'


def test_reconcile_incomplete_pagination_does_not_claim_unique_match(setup):
    db, security = setup
    conn = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    _, initial = remote(timeout=True)
    plan = plans.create(db, security, 'alice', conn['id'], 'feature', 'main',
                        'Feature', transport=initial)
    with pytest.raises(HTTPException):
        plans.execute(db, security, 'alice', plan['id'], plan['confirmation'], initial)
    pages=[]
    marker = '<!-- central-plan:' + plan['id'] + ' -->'
    def respond(request):
        page=int(request.url.params['page'])
        pages.append(page)
        return httpx.Response(200, json=[
            {'number': 7, 'body':marker,'draft':True,
             'head':{'ref':'feature','sha':'a'*40},
             'base':{'ref':'main','sha':'b'*40}}] if page==1 else [],
            headers={'Link':'<https://untrusted.example>; rel="next"'})
    outcome=plans.reconcile(db,security,'alice',plan['id'],httpx.MockTransport(respond))
    # Empty page is treated as an end marker, not as a blind link follow.
    assert outcome['state']=='completed'
    assert pages==[1,2]


def test_reconcile_truncated_results_never_certify_unique_match(setup):
    db, security = setup
    conn = connect(db, security, 'alice', 'github', 'owner/repo', 'private-token')
    _, initial = remote(timeout=True)
    plan=plans.create(db,security,'alice',conn['id'],'feature','main',
                      'Feature',transport=initial)
    with pytest.raises(HTTPException):
        plans.execute(db,security,'alice',plan['id'],plan['confirmation'],initial)
    pages=[]
    marker='<!-- central-plan:'+plan['id']+' -->'
    def respond(request):
        page=int(request.url.params['page'])
        pages.append(page)
        return httpx.Response(200,json=[
            {'number':7,'body':marker,'draft':True,
             'head':{'ref':'feature','sha':'a'*40},
             'base':{'ref':'main','sha':'b'*40}}] if page==1 else
            [{'number':99,'body':'unrelated'}],
            headers={'Link':'<https://untrusted.example/page>; rel="next"'})
    outcome=plans.reconcile(db,security,'alice',plan['id'],httpx.MockTransport(respond))
    assert outcome['reconciliation']=='incomplete'
    assert outcome['state']=='uncertain'
    assert pages == [1,2,3,4,5]


def test_reconcile_changed_branches_requires_human_review(setup):
    db, security=setup
    conn=connect(db,security,'alice','github','owner/repo','private-token')
    _, initial = remote(timeout=True)
    plan=plans.create(db,security,'alice',conn['id'],'feature','main','Feature',
                      transport=initial)
    with pytest.raises(HTTPException):
        plans.execute(db,security,'alice',plan['id'],plan['confirmation'],initial)
    marker='<!-- central-plan:'+plan['id']+' -->'
    def respond(request):
        return httpx.Response(200,json=[
            {'number':7,'body':marker,'draft':False,
             'head':{'ref':'other','sha':'c'*40},
             'base':{'ref':'main','sha':'b'*40}}])
    result=plans.reconcile(db,security,'alice',plan['id'],httpx.MockTransport(respond))
    assert result['state']=='completed'
    assert result['result']['requires_review'] is True
    assert result['result']['branch_matches_plan'] is False
    assert result['result']['draft'] is False


def test_git_plan_history_is_scoped_and_contains_no_confirmation(setup):
    db,security=setup
    conn=connect(db,security,'alice','github','owner/repo','private-token')
    _, transport=remote()
    plan=plans.create(db,security,'alice',conn['id'],'feature','main','Feature',
                      transport=transport)
    found=plans.history(db,'alice',conn['id'])
    assert found[0]['id']==plan['id']
    assert 'confirmation' not in json.dumps(found)
    assert 'connection_fingerprint' not in json.dumps(found)
    assert plans.history(db,'alice',conn['id'],1) == found
    with pytest.raises(HTTPException) as denied:
        plans.history(db,'bob',conn['id'])
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        plans.reconcile(db,security,'bob',plan['id'])
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        plans.reconcile(db,security,'alice',plan['id'])
    assert denied.value.status_code == 409


def test_reconciliation_read_errors_do_not_destroy_uncertain_result(setup):
    db,security=setup
    conn=connect(db,security,'alice','gitlab','owner/repo','private-token')
    _, initial=remote('gitlab',timeout=True)
    plan=plans.create(db,security,'alice',conn['id'],'feature','main','Feature',
                      transport=initial)
    with pytest.raises(HTTPException):
        plans.execute(db,security,'alice',plan['id'],plan['confirmation'],initial)
    def respond(request):
        raise httpx.ReadTimeout('unavailable',request=request)
    with pytest.raises(HTTPException) as error:
        plans.reconcile(db,security,'alice',plan['id'],httpx.MockTransport(respond))
    assert error.value.status_code==502
    assert plans.status(db,'alice',plan['id'])['state']=='uncertain'



def test_reconciliation_routes_require_owner_and_csrf(monkeypatch):
    """Exercise HTTP authorization, not only the direct service functions."""
    import uuid
    from fastapi.testclient import TestClient
    from central.main import app, DB, SEC
    from central.git_gateway import Gateway as OriginalGateway

    headers = {'X-Central-Request': '1'}
    with TestClient(app) as owner, TestClient(app) as stranger:
        users = []
        for client in (owner, stranger):
            email = uuid.uuid4().hex + '@example.org'
            registered = client.post('/api/register',headers=headers,
                                     json={'email': email, 'password':'test-password-123'})
            assert registered.status_code == 200, registered.text
            users.append(registered.json()['id'])
        connection = connect(DB,SEC,users[0],'github','owner/repo','private-token')
        _, transport = remote()
        plan = plans.create(DB,SEC,users[0],connection['id'],'feature','main',
                            'Recover this draft',transport=transport)
        DB.execute("UPDATE git_change_plans SET state='uncertain' WHERE id=?",
                   (plan['id'],))
        marker = '<!-- central-plan:' + plan['id'] + ' -->'
        def respond(request):
            assert request.method == 'GET'
            return httpx.Response(200,json=[
                {'number':42,'body':marker,'draft':True,
                 'head':{'ref':'feature','sha':'a'*40},
                 'base':{'ref':'main','sha':'b'*40}}])
        api_transport = httpx.MockTransport(respond)
        monkeypatch.setattr(plans, 'Gateway',
                            lambda row,security,transport=None:
                                OriginalGateway(row,security,api_transport))
        uri = '/api/git/draft-plans/' + plan['id'] + '/reconcile'
        history_uri = ('/api/git/connections/' + connection['id'] + '/draft-plans')
        assert stranger.get(history_uri).status_code == 404
        assert stranger.post(uri,headers=headers,json={}).status_code == 404
        assert owner.post(uri,json={}).status_code == 403
        result=owner.post(uri,headers=headers,json={})
        assert result.status_code == 200,result.text
        assert result.json()['result']['number'] == 42
        listing=owner.get(history_uri)
        assert listing.status_code == 200
        assert listing.json()[0]['state'] == 'completed'
        assert 'confirmation' not in listing.text
