import json
import sqlite3

from fastapi import HTTPException
import pytest

from central import main as motion_main
from central.database import Database, utcnow
from desktop.motion_studio.apps.api.main import Timeline, initialize, now


@pytest.mark.parametrize('scene_count', [2, 8])
def test_export_is_scoped_to_owned_runs_and_current_timeline(tmp_path, monkeypatch, scene_count):
    db = Database(tmp_path / 'central.sqlite3')
    db.execute('INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)',
               ('owner', 'owner@example.test', 'hash', utcnow()))
    db.execute('INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)',
               ('other', 'other@example.test', 'hash', utcnow()))
    studio_db = tmp_path / 'studio.sqlite3'
    initialize(studio_db)
    clips = [{'id': f'clip_{index}', 'kind': 'video', 'name': f'Cena {index}',
              'start_frame': index * 120, 'duration_frames': 120,
              'style': {'motion_run_id': f'run_{index}', 'motion_artifact_id': 'video'}}
             for index in range(scene_count)]
    timeline = Timeline.model_validate({'fps': 24, 'width': 720, 'height': 1280,
        'tracks': [{'id': 'video_main', 'name': 'Vídeo', 'kind': 'video', 'clips': clips}],
        'storyboard': {'theme': 'Pilot', 'scenes': [
            {'scene': index + 1, 'title': f'Cena {index+1}', 'prompt': 'Test'}
            for index in range(scene_count)]}})
    with sqlite3.connect(studio_db) as connection:
        connection.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)',
                           ('pilot', 'Episódio', '', timeline.model_dump_json(), now(), now()))
    root = tmp_path / 'MotionStudio'
    folder = root / 'episodes' / 'pilot' / 'episode_01'
    folder.mkdir(parents=True)
    source = folder / 'source.mp4'
    source.write_bytes(b'video')

    class FakeMotion:
        def get(self, owner, run_id):
            if owner != 'owner':
                raise HTTPException(404, 'not owned')
            return {'project_id': 'motion-pilot'}

        def artifact_path(self, owner, run_id, artifact_id):
            self.get(owner, run_id)
            return source

    monkeypatch.setattr(motion_main, 'DB', db)
    monkeypatch.setattr(motion_main, 'MOTION', FakeMotion())
    monkeypatch.setattr(motion_main.motion_studio_api.state, 'database', studio_db, raising=False)
    monkeypatch.setattr('central.motion_queue.authorized_root',
                        lambda database, user: (tmp_path, str(tmp_path)))
    monkeypatch.setattr(motion_main, 'require_csrf', lambda request: None)
    monkeypatch.setattr(motion_main, 'local_only', lambda request: None)

    def fake_assemble(scenes, output, captions=None):
        assert len(scenes) == scene_count
        assert captions == [''] * scene_count
        assert all(video == source and audio is None and duration == 5 for video, audio, duration in scenes)
        output.write_bytes(b'final video')
        return {'path': output, 'duration': scene_count * 5, 'scenes': scene_count}

    monkeypatch.setattr('central.motion_export.assemble_episode', fake_assemble)
    result = motion_main.motion_export_episode('pilot', object(), {'id': 'owner'})
    assert motion_main._motion_export_record('owner', 'pilot')['id'] == result['id']
    assert motion_main._motion_export_record('other', 'pilot') is None
    with sqlite3.connect(studio_db) as connection:
        changed = json.loads(timeline.model_dump_json())
        changed['tracks'][0]['clips'][0]['name'] = 'Revisada'
        changed['tracks'][0]['clips'][0]['style']['review_status'] = 'needs_revision'
        connection.execute('UPDATE projects SET timeline_json=? WHERE id=?',
                           (Timeline.model_validate(changed).model_dump_json(), 'pilot'))
    assert motion_main._motion_export_record('owner', 'pilot')['id'] == result['id']
    with sqlite3.connect(studio_db) as connection:
        changed['tracks'][0]['clips'][0]['style']['motion_artifact_id'] = 'revised_video'
        connection.execute('UPDATE projects SET timeline_json=? WHERE id=?',
                           (Timeline.model_validate(changed).model_dump_json(), 'pilot'))
    assert motion_main._motion_export_record('owner', 'pilot') is None
