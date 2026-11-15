import sqlite3

from fastapi import HTTPException
import pytest

from central import main as motion_main
from central.database import Database, utcnow
from desktop.motion_studio.apps.api.main import Timeline, initialize, now


def test_visual_review_uses_only_owned_project_references(tmp_path, monkeypatch):
    db = Database(tmp_path / 'central.sqlite3')
    for owner in ('owner', 'other'):
        db.execute('INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)',
                   (owner, owner + '@example.test', 'hash', utcnow()))
    db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,priority,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('vision', 'owner', 'Vision', 'gemini', 'https://generativelanguage.googleapis.com/v1beta',
                'gemini-3.1-flash-lite', 'encrypted-key', 1, 1, utcnow()))
    studio_db = tmp_path / 'studio.sqlite3'
    initialize(studio_db)
    image = 'data:image/png;base64,aGVsbG8='
    timeline = Timeline.model_validate({'fps': 24, 'width': 720, 'height': 1280,
        'storyboard': {'theme': 'Corredor', 'visual_bible': 'Porta de madeira',
                       'scenes': [{'scene': 1, 'title': 'Entrada', 'prompt': 'Abrir a porta'}],
                       'references': [
                           {'id': 'master', 'kind': 'character', 'name': 'Sombra', 'prompt': '',
                            'source': 'upload', 'image_data': image},
                           {'id': 'scene-one', 'kind': 'setting', 'name': 'Entrada', 'prompt': '',
                            'source': 'generated_image', 'scene_number': 1, 'image_data': image}]},
        'tracks': []})
    with sqlite3.connect(studio_db) as connection:
        connection.execute('INSERT INTO projects(id,title,summary,timeline_json,created_at,updated_at,owner_id) VALUES (?,?,?,?,?,?,?)',
                           ('pilot', 'Entrada', '', timeline.model_dump_json(), now(), now(), 'owner'))
    monkeypatch.setattr(motion_main, 'DB', db)
    monkeypatch.setattr(motion_main.motion_studio_api.state, 'database', studio_db, raising=False)
    monkeypatch.setattr(motion_main, 'require_csrf', lambda request: None)
    monkeypatch.setattr(motion_main, 'local_only', lambda request: None)
    monkeypatch.setattr(motion_main.SEC, 'decrypt', lambda value: 'secret-test')
    calls = []
    def fake_review(*args, **kwargs):
        calls.append((args, kwargs))
        return {'status': 'pass', 'findings': [], 'reviewer': 'test'}
    monkeypatch.setattr('central.motion_visual_review.review_scene', fake_review)
    data = motion_main.MotionVisualReviewIn(project_id='pilot', scene=1)
    assert motion_main.motion_photo_review(data, object(), {'id': 'owner'})['status'] == 'pass'
    assert calls[0][1]['api_key'] == 'secret-test'
    assert calls[0][1]['action'] == 'Abrir a porta'
    with pytest.raises(HTTPException) as forbidden:
        motion_main.motion_photo_review(data, object(), {'id': 'other'})
    assert forbidden.value.status_code in (403, 404)
    assert len(calls) == 1
