"""Durable queue boundaries with SQLite/files; fake tool bodies are not render proof."""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from central.database import Database,utcnow
from central.computer_access import set_policy
from central.motion_contracts import MotionConfig
from central.motion_queue import MotionQueue
from test_motion_contracts import manifest


class FixtureQueue(MotionQueue):
    calls=0
    def _command(self,row,command,stop):
        self.calls+=1
        self._check(row,stop)
        from pathlib import Path
        path=Path(command.argv[-1])
        path.write_bytes(b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00fixture')


@pytest.fixture
def queued(tmp_path,monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE','local')
    db=Database(tmp_path/'motion.sqlite')
    for user in ('u','other'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)',(user,user+'@test.local','hash',utcnow()))
    root=tmp_path/'media';root.mkdir()
    (root/'clip.mp4').write_bytes(b'input fixture')
    program=tmp_path/'ffmpeg.exe';program.write_bytes(b'inert runtime fixture')
    set_policy(db,'u','full',str(root))
    queue=FixtureQueue(db,MotionConfig(executables={'ffmpeg':str(program)}))
    yield db,root,program,queue
    db.close()


def test_idempotent_enqueue_completion_and_receipt_survive_reopen(queued):
    db,root,program,queue=queued
    plan=manifest()
    first=queue.enqueue('u',plan,'request-001')
    assert queue.enqueue('u',plan,'request-001')['id']==first['id']
    assert queue.process_one()
    result=queue.get('u',first['id'])
    assert result['state']=='completed' and result['jobs'][0]['artifact']['sha256']
    assert queue.enqueue('u',plan,'request-001')['id']==first['id']
    second=Database(root.parent/'motion.sqlite')
    try:assert MotionQueue(second).get('u',first['id'])['state']=='completed'
    finally:second.close()
    changed=copy.deepcopy(plan);changed['jobs'][0]['params']['profile']='pcm_s16le'
    with pytest.raises(HTTPException) as err:queue.enqueue('u',changed,'request-001')
    assert err.value.status_code==409
    (root/'render.mp4').write_bytes(b'changed')
    with pytest.raises(HTTPException) as err:queue.artifact_path('u',first['id'],'output')
    assert err.value.status_code==409


@pytest.mark.parametrize('change', ['input','runtime','permission'])
def test_changed_inputs_runtime_or_permission_stop_before_execution(queued,change):
    db,root,program,queue=queued
    run=queue.enqueue('u',manifest(),'request-002')
    if change=='input':(root/'clip.mp4').write_bytes(b'changed input')
    elif change=='runtime':program.write_bytes(b'changed runtime')
    else:set_policy(db,'u','blocked','')
    assert queue.process_one()
    result=queue.get('u',run['id'])
    assert result['state']=='failed' and queue.calls==0
    assert not (root/'render.mp4').exists()


def test_scope_and_cancel_queued_job(queued):
    db,root,program,queue=queued
    run=queue.enqueue('u',manifest(),'request-003')
    for fn in (queue.get,queue.cancel):
        with pytest.raises(HTTPException) as err:fn('other',run['id'])
        assert err.value.status_code==404
    assert queue.cancel('u',run['id'])['state']=='cancelled'
    assert queue.get('u',run['id'])['jobs'][0]['state']=='cancelled'
    assert queue.process_one() is False


def test_two_dispatchers_claim_only_once_and_running_cancel_is_observed(queued):
    db,root,program,queue=queued
    run=queue.enqueue('u',manifest(),'request-004')
    started=threading.Event()
    def command(row,plan,stop):
        started.set()
        while True:
            queue._check(row,stop)
            time.sleep(.01)
    queue._command=command
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(queue.process_one)
        assert started.wait(5)
        assert pool.submit(queue.process_one).result(timeout=5) is False
        queue.cancel('u',run['id'])
        assert first.result(timeout=5)
    assert queue.get('u',run['id'])['state']=='cancelled'
    assert not (root/'render.mp4').exists()


def test_crashed_job_is_marked_interrupted_and_never_silently_replayed(queued):
    db,root,program,queue=queued
    run=queue.enqueue('u',manifest(),'request-005')
    db.execute("UPDATE motion_runs SET state='running',lease_owner='old',heartbeat=? WHERE id=?",(time.time()-121,run['id']))
    db.execute("UPDATE motion_jobs SET state='running' WHERE run_id=?",(run['id'],))
    assert queue.process_one() is False
    assert queue.get('u',run['id'])['state']=='interrupted'
    assert queue.get('u',run['id'])['jobs'][0]['state']=='interrupted'
    assert queue.calls==0
