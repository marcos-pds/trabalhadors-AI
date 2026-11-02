import pytest
from central.database import Database,utcnow
from central.workflow_gates import downstream_visual_reviewer


def test_visual_qa_can_be_deferred_only_to_enabled_downstream_review_in_same_account():
    db=Database(':memory:')
    try:
        for user in ('u','other'):
            db.execute('INSERT INTO users VALUES(?,?,?,?)',(user,user+'@test.local','hash',utcnow()))
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,enabled,created_at) VALUES(?,?,?,?,?,?,?)',
                   ('reviewer','u','Review','review','Review the delivery',1,utcnow()))
        graph=[{'id':'backend','deps':[]},{'id':'frontend','deps':['backend']},
               {'id':'review','deps':['frontend'],'agent_id':'reviewer'}]
        assert downstream_visual_reviewer(db,'u',graph,'backend')=='review'
        assert downstream_visual_reviewer(db,'other',graph,'backend') is None
        graph[1]['deps']=[]
        assert downstream_visual_reviewer(db,'u',graph,'backend') is None
        graph[1]['deps']=['backend']
        db.execute('UPDATE agents SET enabled=0')
        assert downstream_visual_reviewer(db,'u',graph,'backend') is None
    finally:db.close()
