"""Real local embedding relevance check on declared synthetic project memories."""
import argparse
import json
from pathlib import Path
import time
import httpx

from fastapi import HTTPException
from central.database import Database,utcnow
from central import semantic_memory as semantic


DOCUMENTS=[
    'Session renewal uses a rotating refresh token stored in an HttpOnly cookie.',
    'Tasks can be moved between pending, in progress and completed columns.',
    'The application uses a white background and a blue accent for primary buttons.',
    'Video exports are encoded as H264 MP4 with AAC audio.',
    'Daily spending limits pause a worker when its token budget is exhausted.',
    'A canceled worker releases its isolated worktree after review.',
]
CASES=[('How does authentication stay valid after the access credential expires?',0),
       ('Where can I drag a task after finishing it?',1),
       ('What colors should the interface use?',2),
       ('Which file format and codecs are used for movie downloads?',3),
       ('What happens when an agent spends its daily allowance?',4),
       ('What happens to the separate working directory when a worker is canceled?',5)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args();args.destination.mkdir(parents=True,exist_ok=False)
    # Cached queries have an eight-second budget; initial indexing has thirty.
    # Warm only this explicit benchmark; never change production preferences.
    warm_start=time.monotonic()
    with httpx.Client(timeout=120,trust_env=False) as client:
        warm=client.post('http://127.0.0.1:11434/api/embed',json={
            'model':'nomic-embed-text','input':['search_query: readiness'],'keep_alive':'5m'})
        warm.raise_for_status()
    warm_seconds=round(time.monotonic()-warm_start,2)
    db=Database(args.destination/'central.sqlite3')
    try:
        for owner in ('operator','outsider'):
            db.execute('INSERT INTO users VALUES(?,?,?,?)',(owner,owner+'@example.test','unused',utcnow()))
        for pid,owner in [('project','operator'),('private','outsider'),('unrelated','operator')]:
            db.execute('INSERT INTO projects(id,user_id,name,description,created_at) VALUES(?,?,?,?,?)',(pid,owner,pid,'fixture',utcnow()))
            for suffix in ('old','current'):
                db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',(pid+'-'+suffix,owner,suffix,pid,utcnow(),utcnow()))
        for index,text in enumerate(DOCUMENTS):
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',('m'+str(index),'project-old','operator','user',None,text,utcnow()))
        for pid,owner in [('private','outsider'),('unrelated','operator')]:
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(pid,pid+'-old',owner,'user',None,'SCOPE_CANARY: '+DOCUMENTS[0],utcnow()))
        assert semantic.retrieve(db,'operator','project','project-current',CASES[0][0])==[]
        semantic.preference(db,'operator','project',True)
        results=[];start=time.monotonic()
        for query,expected in CASES:
            recalled=semantic.retrieve(db,'operator','project','project-current',query)
            results.append({'query':query,'expected_document':expected,
                'top1_correct':bool(recalled and recalled[0]['content']==DOCUMENTS[expected]),
                'top4_contains_expected':any(r['content']==DOCUMENTS[expected] for r in recalled),
                'scope_leak':any('SCOPE_CANARY' in r['content'] for r in recalled),
                'sources':recalled})
        denied=False
        try:semantic.retrieve(db,'outsider','project','private-current','session')
        except HTTPException:denied=True
        report={'synthetic_fixtures':True,'backend':'real_local_ollama','generation_worker_used':False,
                'model':semantic.preference(db,'operator','project')['model'],
                'explicit_benchmark_warmup_seconds':warm_seconds,
                'elapsed_seconds':round(time.monotonic()-start,2),'cases':results,
                'top1_correct':sum(r['top1_correct'] for r in results),
                'unauthorized_project_denied':denied,
                'cached_embeddings':db.one('SELECT COUNT(*) AS n FROM memory_embeddings')['n']}
        report['passed']=all(r['top4_contains_expected'] and not r['scope_leak'] for r in results) and denied
        (args.destination/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)
        return 0 if report['passed'] else 2
    finally:db.close()


if __name__=='__main__':raise SystemExit(main())
