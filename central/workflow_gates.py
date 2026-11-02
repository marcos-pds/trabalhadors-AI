"""Assign stage-specific proof without weakening the final delivery gate."""
import json
from .agent_registry import effective_specialty


def downstream_visual_reviewer(db,user_id,plan,step_id):
    try:nodes=json.loads(plan) if isinstance(plan,str) else plan
    except (ValueError,TypeError):return None
    if not isinstance(nodes,list) or not 1<=len(nodes)<=128:return None
    reached={step_id}
    for _ in nodes:
        new={n.get('id') for n in nodes if isinstance(n,dict) and
             isinstance(n.get('deps',[]),list) and any(d in reached for d in n.get('deps',[]))}
        if new<=reached:break
        reached.update(new)
    reviewers={a['id'] for a in db.all('SELECT * FROM agents WHERE user_id=? AND enabled=1',(user_id,))
               if effective_specialty(a)=='review'}
    return next((n['id'] for n in nodes if isinstance(n,dict) and n.get('id')!=step_id
                 and n.get('id') in reached and n.get('agent_id') in reviewers),None)
