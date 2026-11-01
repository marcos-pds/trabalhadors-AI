"""Real Remotion/WhisperX acceptance on explicit synthetic fixtures; no AI app worker."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from central.computer_access import set_policy
from central.database import Database,utcnow
from central.motion_contracts import MotionConfig
from central.motion_queue import MotionQueue

SCENE="""import React from 'react';
import {AbsoluteFill,Composition,registerRoot,useCurrentFrame} from 'remotion';
const Scene=()=>{const frame=useCurrentFrame();return <AbsoluteFill style={{background:'#eff6ff',justifyContent:'center',alignItems:'center'}}><div style={{width:25,height:25,borderRadius:50,background:'#38bdf8',transform:`translateX(${frame-15}px)`}}/></AbsoluteFill>};
registerRoot(()=> <Composition id="Intro" component={Scene} durationInFrames={30} fps={30} width={160} height={90}/>);
"""


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination',type=Path)
    for key in ('ffmpeg','remotion','whisperx','speech'):p.add_argument('--'+key,required=True)
    args=p.parse_args()
    config=MotionConfig(executables={k:str(Path(getattr(args,k)).resolve(strict=True)) for k in ('ffmpeg','remotion','whisperx')})
    args.destination.mkdir(parents=True,exist_ok=False)
    root=args.destination.resolve();workspace=root/'workspace';workspace.mkdir()
    (workspace/'scene.tsx').write_text(SCENE,encoding='utf-8')
    shutil.copyfile(args.speech,workspace/'speech.wav')
    db=Database(root/'central.sqlite3')
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)',('media-operator','media@test.local','unused',utcnow()))
        set_policy(db,'media-operator','full',str(workspace))
        queue=MotionQueue(db,config,timeout=600)
        ids=[]
        for kind,source,output,adapter,stage,params,outkind in (
                ('composition','scene.tsx','renders/scene.mp4','remotion','compose',{'composition':'Intro','fps':30},'video'),
                ('audio','speech.wav','renders/speech.json','whisperx','transcribe',{'language':'en','model':'tiny'},'captions')):
            manifest={'schema_version':1,'project_id':'adapter-demo','artifacts':[
                {'id':'source','kind':kind,'path':source,'provenance':{'source':'local'}},
                {'id':'result','kind':outkind,'path':output,'provenance':{'source':'planned','job_id':'render','inputs':['source']}}],
                'jobs':[{'id':'render','adapter':adapter,'stage':stage,'inputs':['source'],'outputs':['result'],'params':params}]}
            ids.append(queue.enqueue('media-operator',manifest,'acceptance-'+adapter)['id'])
        reports=[]
        for rid in ids:
            queue.process_one()
            report=queue.get('media-operator',rid)
            print(json.dumps({'adapter':report['jobs'][0]['adapter'],'state':report['state'],'error':report['error']}),flush=True)
            reports.append(report)
            (root/'report.json').write_text(json.dumps({'runs':reports,'passed':False,'synthetic_fixtures':True},indent=2),encoding='utf-8')
        decoded=False;transcribed=False
        for report in reports:
            if report['state']!='completed':continue
            job=report['jobs'][0];path=queue.artifact_path('media-operator',report['id'],'result')
            if job['adapter']=='remotion':
                check=subprocess.run([config.executables['ffmpeg'],'-nostdin','-v','error','-i',str(path),'-f','null','-'],capture_output=True,timeout=30)
                decoded=check.returncode==0
            else:
                data=json.loads(path.read_text(encoding='utf-8'))
                text=' '.join(s.get('text','') for s in data['segments']).lower()
                transcribed=sum(word in text for word in ('central','media','studio'))>=2
                report['recognized_text']=text
                report['aligned_word_count']=sum(len(s.get('words',[])) for s in data['segments'])
        result={'runs':reports,'synthetic_fixtures':True,'ai_app_generation_tested':False,
                'independent_video_decode':decoded,'speech_content_verified':transcribed,
                'passed':decoded and transcribed and all(r['state']=='completed' for r in reports)}
        (root/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
        return 0 if result['passed'] else 2
    finally:db.close()


if __name__=='__main__':raise SystemExit(main())
