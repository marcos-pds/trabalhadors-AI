"""Explicit opt-in download of the three official Wan 1.3B files, with pinned SHA256.

Never called by the web UI or worker. No credentials, installers or code execution.
Existing mismatched files are refused; interrupted downloads retain a .part file.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re

import httpx

REPO='Comfy-Org/Wan-2.1'
FILES=(('diffusion_models','wan2.1_t2v_1.3B_fp16.safetensors'),
       ('text_encoders','umt5_xxl_fp8_e4m3fn_scaled.safetensors'),
       ('vae','wan_2.1_vae.safetensors'))


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):digest.update(chunk)
    return digest.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('comfy_root',type=Path)
    args=p.parse_args()
    from central.motion_contracts import _root
    root=_root(args.comfy_root)
    with httpx.Client(timeout=60,trust_env=False,follow_redirects=True) as client:
        response=client.get('https://huggingface.co/api/models/'+REPO);response.raise_for_status()
        revision=response.json()['sha']
        if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('invalid_revision')
        descriptors=[]
        for folder,name in FILES:
            response=client.get('https://huggingface.co/api/models/'+REPO+'/tree/'+revision+'/split_files/'+folder)
            response.raise_for_status()
            file=next(item for item in response.json() if item['path']=='split_files/'+folder+'/'+name)
            expected=file['lfs']['oid']
            if not re.fullmatch('[a-f0-9]{64}',expected) or not 0<file['size']<10*1024**3:raise ValueError('invalid_metadata')
            descriptors.append((folder,name,expected,file['size']))
    def download(descriptor):
        folder,name,expected,total=descriptor
        directory=root/'models'/folder;directory.mkdir(parents=True,exist_ok=True);_root(directory)
        target=directory/name;partial=directory/(name+'.part')
        for path in (target,partial):
            if path.is_symlink() or (path.exists() and path.stat().st_nlink!=1):raise ValueError('linked_model')
        if target.exists():
            if target.stat().st_size!=total or sha(target)!=expected:raise ValueError('existing_model_mismatch')
        else:
            offset=partial.stat().st_size if partial.exists() else 0
            if offset>total:raise ValueError('partial_size_mismatch')
            with httpx.Client(timeout=httpx.Timeout(60,connect=15),trust_env=False,follow_redirects=True) as client:
                url='https://huggingface.co/'+REPO+'/resolve/'+revision+'/split_files/'+folder+'/'+name
                with client.stream('GET',url,headers={'Range':f'bytes={offset}-'} if offset else {}) as response:
                    response.raise_for_status()
                    if offset and response.status_code!=206:offset=0
                    if response.status_code==206 and not response.headers.get('content-range','').startswith(f'bytes {offset}-'):
                        raise ValueError('invalid_range_response')
                    with partial.open('ab' if offset else 'wb') as stream:
                        count=offset;next_report=count+128*1024**2
                        for chunk in response.iter_bytes(1024**2):
                            count+=len(chunk)
                            if count>total:raise ValueError('model_exceeds_metadata')
                            stream.write(chunk)
                            if count>=next_report:
                                print(json.dumps({'file':name,'downloaded_bytes':count,'total_bytes':total}),flush=True)
                                next_report=count+128*1024**2
            if partial.stat().st_size!=total or sha(partial)!=expected:raise ValueError('model_digest_mismatch')
            os.link(partial,target)  # atomic, exclusive; never replace an existing model
            partial.unlink()
        print(json.dumps({'file':name,'verified':True,'bytes':total}),flush=True)
        return {'path':'models/'+folder+'/'+name,'sha256':expected,'bytes':total}
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(download,descriptors))
    report={'repository':REPO,'revision':revision,'files':results,'credentials_used':False}
    (root/'wan-model-receipts.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'failed':True,'error_type':type(exc).__name__}),flush=True)
        raise SystemExit(1)
