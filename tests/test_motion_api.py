import uuid
from fastapi.testclient import TestClient
from central.computer_access import set_policy
from test_motion_contracts import manifest


def test_motion_api_requires_auth_scope_csrf_and_keeps_artifacts_private(tmp_path,monkeypatch):
    from central.main import app,DB,MOTION
    root=tmp_path/'media';root.mkdir();(root/'clip.mp4').write_bytes(b'input fixture')
    program=tmp_path/'ffmpeg.exe';program.write_bytes(b'inert runtime fixture')
    headers={'X-Central-Request':'1'}
    with TestClient(app) as owner,TestClient(app) as other,TestClient(app) as anonymous:
        assert anonymous.get('/api/motion/runs').status_code==401
        def register(client):
            response=client.post('/api/register',headers=headers,json={'email':uuid.uuid4().hex+'@example.test','password':'LocalTestPassword123!'})
            assert response.status_code==200,response.text
            return response.json()['id']
        user=register(owner);register(other)
        body={'manifest':manifest(),'request_id':'motion-api-001'}
        assert owner.post('/api/motion/runs',headers=headers,json=body).status_code==403
        set_policy(DB,user,'full',str(root))
        assert owner.post('/api/motion/tools',headers=headers,json={'executables':{'ffmpeg':str(program)}}).status_code==200
        assert owner.post('/api/motion/runs',json=body).status_code==403
        plan=owner.post('/api/motion/plan',headers=headers,json=body)
        assert plan.status_code==200 and plan.json()['executable'] is True
        created=owner.post('/api/motion/runs',headers=headers,json=body)
        assert created.status_code==200,created.text
        rid=created.json()['id']
        assert other.get('/api/motion/runs/'+rid).status_code==404
        assert other.post('/api/motion/runs/'+rid+'/cancel',headers=headers,json={}).status_code==404
        def controlled_fixture(row,command,stop):
            from pathlib import Path
            Path(command.argv[-1]).write_bytes(b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00fixture')
        monkeypatch.setattr('central.motion_queue.validate_media_with_ffprobe', lambda *args, **kwargs: {
            'duration': 5.0, 'fps': '30/1', 'width': 720, 'height': 1280, 'audio': False,
        })
        monkeypatch.setattr(MOTION,'_command',controlled_fixture)
        assert MOTION.process_one()
        url='/api/motion/runs/'+rid+'/artifacts/output'
        assert other.get(url).status_code==404
        download=owner.get(url)
        assert download.status_code==200 and download.headers['content-disposition'].startswith('attachment;')
        inline_url=url+'/preview'
        assert anonymous.get(inline_url).status_code==401
        assert other.get(inline_url).status_code==404
        inline=owner.get(inline_url)
        assert inline.status_code==200
        assert inline.headers['content-disposition'].startswith('inline;')
        assert inline.headers['content-type'].startswith('video/mp4')
        assert inline.headers['cache-control']=='private, no-store'
        assert inline.content==download.content
        (root/'render.mp4').write_bytes(b'changed')
        assert owner.get(url).status_code==409
        assert owner.get(inline_url).status_code==409
        set_policy(DB,user,'blocked','')
        assert owner.get(url).status_code==403
        assert owner.get(inline_url).status_code==403
