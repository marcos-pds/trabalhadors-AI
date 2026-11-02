"""Real small Wan inference through Central's owned media queue, not a quality benchmark."""
import argparse
import json
from pathlib import Path
import subprocess

from central.database import Database,utcnow
from central.computer_access import set_policy
from central.motion_contracts import MotionConfig
from central.motion_queue import MotionQueue


def workflow():
    return {
      '1':{'class_type':'UNETLoader','inputs':{'unet_name':'wan2.1_t2v_1.3B_fp16.safetensors','weight_dtype':'default'}},
      '2':{'class_type':'CLIPLoader','inputs':{'clip_name':'umt5_xxl_fp8_e4m3fn_scaled.safetensors','type':'wan','device':'default'}},
      '3':{'class_type':'VAELoader','inputs':{'vae_name':'wan_2.1_vae.safetensors'}},
      '4':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'A blue sphere moving slowly on a white background'}},
      '5':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'text, watermark'}},
      '6':{'class_type':'EmptyHunyuanLatentVideo','inputs':{'width':64,'height':64,'length':5,'batch_size':1}},
      '7':{'class_type':'KSampler','inputs':{'model':['11',0],'positive':['4',0],'negative':['5',0],'latent_image':['6',0],'seed':1,'steps':1,'cfg':1,'sampler_name':'euler','scheduler':'simple','denoise':1}},
      '8':{'class_type':'VAEDecode','inputs':{'samples':['7',0],'vae':['3',0]}},
      '9':{'class_type':'CreateVideo','inputs':{'images':['8',0],'fps':16}},
      '10':{'class_type':'SaveVideo','inputs':{'video':['9',0],'filename_prefix':'central_acceptance','format':{'format':'mp4','codec':{'codec':'h264'}}}},
      '11':{'class_type':'ModelSamplingSD3','inputs':{'model':['1',0],'shift':8}},
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--comfy-root',required=True)
    parser.add_argument('--endpoint',default='http://127.0.0.1:8189')
    parser.add_argument('--ffmpeg',required=True)
    args=parser.parse_args();args.destination.mkdir(parents=True,exist_ok=False)
    root=args.destination.resolve();workspace=root/'workspace';workspace.mkdir()
    (workspace/'wan-api.json').write_text(json.dumps(workflow(),indent=2),encoding='utf-8')
    config=MotionConfig(comfy_root=args.comfy_root,comfy_endpoint=args.endpoint)
    db=Database(root/'central.sqlite3')
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)',('operator','wan@example.test','unused',utcnow()))
        set_policy(db,'operator','full',str(workspace))
        manifest={'schema_version':1,'project_id':'wan-acceptance','artifacts':[
          {'id':'workflow','kind':'workflow','path':'wan-api.json','provenance':{'source':'local'}},
          {'id':'video','kind':'video','path':'renders/wan.mp4','provenance':{'source':'planned','job_id':'generate','inputs':['workflow']}}],
          'jobs':[{'id':'generate','adapter':'comfyui_wan','stage':'generate','inputs':['workflow'],'outputs':['video'],
                   'params':{'model':'wan','seed':7,'frames':5,'fps':16}}]}
        queue=MotionQueue(db,config,timeout=1200)
        run=queue.enqueue('operator',manifest,'real-wan-acceptance')
        print(json.dumps({'run_id':run['id'],'state':run['state']}),flush=True)
        queue.process_one();report=queue.get('operator',run['id'])
        decoded=False
        if report['state']=='completed':
            path=queue.artifact_path('operator',run['id'],'video')
            check=subprocess.run([args.ffmpeg,'-nostdin','-v','error','-i',str(path),'-f','null','-'],capture_output=True,timeout=30)
            decoded=check.returncode==0
        result={'run':report,'real_inference':True,'small_sanity_fixture':True,'quality_benchmark':False,
                'independent_decode':decoded,'passed':report['state']=='completed' and decoded}
        (root/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
        return 0 if result['passed'] else 2
    finally:db.close()


if __name__=='__main__':raise SystemExit(main())
