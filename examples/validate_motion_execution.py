"""Real FFmpeg queue acceptance with synthetic media, not AI generation proof."""
import argparse
import json
from pathlib import Path
import subprocess

from central.computer_access import set_policy
from central.database import Database,utcnow
from central.motion_contracts import MotionConfig
from central.motion_queue import MotionQueue


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--ffmpeg',required=True)
    args=parser.parse_args()
    config=MotionConfig(executables={'ffmpeg':str(Path(args.ffmpeg).resolve(strict=True))})
    args.destination.mkdir(parents=True,exist_ok=False)
    root=args.destination.resolve()
    workspace=root/'workspace';workspace.mkdir()
    exe=config.executables['ffmpeg']
    version=subprocess.run([exe,'-version'],capture_output=True,text=True,timeout=15,check=True).stdout.splitlines()[0]
    subprocess.run([exe,'-nostdin','-n','-f','lavfi','-i','color=c=blue:s=160x90:r=10',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(workspace/'source.mp4')],
                    capture_output=True,timeout=30,check=True)
    manifest={'schema_version':1,'project_id':'motion-demo','artifacts':[
        {'id':'source','kind':'video','path':'source.mp4','provenance':{'source':'local'}},
        {'id':'video','kind':'video','path':'renders/final.mp4','provenance':{'source':'planned','job_id':'encode','inputs':['source']}},
        {'id':'audio','kind':'audio','path':'renders/final.wav','provenance':{'source':'planned','job_id':'extract','inputs':['video']}}],
        'jobs':[{'id':'encode','adapter':'ffmpeg','stage':'encode','inputs':['source'],'outputs':['video'],'params':{'profile':'h264'}},
                {'id':'extract','adapter':'ffmpeg','stage':'encode','inputs':['video'],'outputs':['audio'],'params':{'profile':'pcm_s16le'}}]}
    db=Database(root/'central.sqlite3')
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)',('media-operator','media@test.local','unused',utcnow()))
        set_policy(db,'media-operator','full',str(workspace))
        queue=MotionQueue(db,config)
        run=queue.enqueue('media-operator',manifest,'real-motion-acceptance')
        queue.process_one()
        report=queue.get('media-operator',run['id'])
        verified=[]
        for job in report['jobs']:
            if job['state']!='completed':continue
            path=queue.artifact_path('media-operator',run['id'],job['artifact']['id'])
            check=subprocess.run([exe,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(path),'-f','null','-'],
                                 capture_output=True,timeout=30)
            verified.append({'artifact':job['artifact']['id'],'decode_exit_code':check.returncode})
        report.update({'ffmpeg_version':version,'synthetic_source':True,'ai_generation_tested':False,
                       'independent_decodes':verified,'passed':report['state']=='completed' and len(verified)==2 and all(v['decode_exit_code']==0 for v in verified)})
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
        return 0 if report['passed'] else 2
    finally:db.close()


if __name__=='__main__':raise SystemExit(main())
