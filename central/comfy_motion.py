"""Bounded ComfyUI Wan API workflow. Only owned prompt IDs/results are collected."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time

import httpx

from .motion_contracts import ContractError,scoped_path,_SECRET

ALLOWED={'UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','ModelSamplingSD3',
         'EmptyHunyuanLatentVideo','KSampler','VAEDecode','CreateVideo','SaveVideo',
         'CheckpointLoaderSimple','LoadImage','LTXVImgToVideo','LTXVConditioning',
         'LTXVScheduler','KSamplerSelect','SamplerCustom'}
ERRORS={'workflow_too_large','invalid_workflow','invalid_workflow_text','invalid_workflow_link',
        'unsupported_comfy_node','invalid_wan_workflow','cyclic_workflow','wan_frame_limit',
        'comfy_configuration_required','invalid_model_path','wan_model_required','positive_prompt_node_required',
        'model_size_limit','comfy_request_failed','comfy_response_limit','invalid_comfy_response',
        'invalid_prompt_receipt','comfy_execution_failed','owned_video_missing','invalid_comfy_artifact',
        'comfy_download_failed','artifact_size_limit','unrelated_workflow_nodes','invalid_sampler','wan_resolution_limit'}


def prepare_workflow(path,params,prefix,config):
    if path.stat().st_size>256*1024:raise ContractError('workflow_too_large')
    content=path.read_bytes()
    value=json.loads(content)
    graph=value.get('prompt',value) if isinstance(value,dict) else None
    if not isinstance(graph,dict) or not 1<=len(graph)<=64:raise ContractError('invalid_workflow')
    graph=copy.deepcopy(graph)
    grouped={}
    links={}
    def visit(value,depth=0):
        if depth>6:raise ContractError('invalid_workflow')
        if isinstance(value,str):
            if len(value)>4096 or '\x00' in value or _SECRET.search(value):raise ContractError('invalid_workflow_text')
        elif type(value) in (int,float):
            if not math.isfinite(value):raise ContractError('invalid_workflow')
        elif value is None or type(value) is bool:pass
        elif isinstance(value,list):
            if len(value)!=2 or not isinstance(value[0],str) or value[0] not in graph or type(value[1]) is not int or not 0<=value[1]<=64:
                raise ContractError('invalid_workflow_link')
            return {value[0]}
        elif isinstance(value,dict):
            if len(value)>32:raise ContractError('invalid_workflow')
            result=set()
            for child in value.values():result.update(visit(child,depth+1) or ())
            return result
        else:raise ContractError('invalid_workflow')
        return set()
    for identifier,node in graph.items():
        if (not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',identifier)
            or not isinstance(node,dict) or set(node)-{'class_type','inputs','_meta'}
            or node.get('class_type') not in ALLOWED or not isinstance(node.get('inputs'),dict)):
            raise ContractError('unsupported_comfy_node')
        node.pop('_meta',None)
        grouped.setdefault(node['class_type'],[]).append((identifier,node['inputs']))
        links[identifier]=visit(node['inputs'])
    required = (('CheckpointLoaderSimple','CLIPLoader','LoadImage','LTXVImgToVideo','LTXVConditioning','LTXVScheduler','KSamplerSelect','SamplerCustom','VAEDecode','CreateVideo','SaveVideo')
                if params['model']=='ltxv' else
                ('UNETLoader','CLIPLoader','VAELoader','KSampler','EmptyHunyuanLatentVideo','CreateVideo','SaveVideo'))
    for name in required:
        if len(grouped.get(name,[]))!=1:raise ContractError('invalid_wan_workflow')
    reachable={grouped['SaveVideo'][0][0]}
    for _ in graph:
        expanded=reachable|set().union(*(links[i] for i in reachable))
        if expanded==reachable:break
        reachable=expanded
    if reachable!=set(graph):raise ContractError('unrelated_workflow_nodes')
    pending=dict(links);done=set()
    while pending:
        ready={key for key,deps in pending.items() if deps<=done}
        if not ready:raise ContractError('cyclic_workflow')
        done.update(ready)
        for key in ready:pending.pop(key)
    if params['model']=='ltxv':
        from .motion_ltx import MODEL, ENCODER
        if set(grouped)-set(required)-{'CLIPTextEncode'} or len(grouped.get('CLIPTextEncode',[]))!=2:
            raise ContractError('invalid_wan_workflow')
        if params['frames']>129 or (params['frames']-1)%8:
            raise ContractError('wan_frame_limit')
        if not config.comfy_root or not config.comfy_endpoint:
            raise ContractError('comfy_configuration_required')
        checkpoint=grouped['CheckpointLoaderSimple'][0][1]
        clip=grouped['CLIPLoader'][0][1]
        if checkpoint.get('ckpt_name')!=MODEL or clip.get('clip_name')!=ENCODER or clip.get('type')!='ltxv':
            raise ContractError('invalid_model_path')
        latent=grouped['LTXVImgToVideo'][0][1]
        if any(latent.get(key)!=value for key,value in {'width':params.get('width',288),
                'height':params.get('height',512),'batch_size':1,'strength':1.0}.items()):
            raise ContractError('wan_resolution_limit')
        image_name=grouped['LoadImage'][0][1].get('image')
        if not isinstance(image_name,str) or not re.fullmatch(r'central_ltx_[a-f0-9]{32}\.(?:jpg|png|webp)',image_name):
            raise ContractError('invalid_model_path')
        image=scoped_path(config.comfy_root,'input/'+image_name)
        if hashlib.sha256(image.read_bytes()).hexdigest()!=params['image_sha256']:
            raise ContractError('input_changed')
        sampler=grouped['SamplerCustom'][0][1]
        if sampler.get('cfg')!=1.0 or grouped['LTXVScheduler'][0][1].get('steps')!=8 or grouped['KSamplerSelect'][0][1].get('sampler_name')!='euler':
            raise ContractError('invalid_sampler')
        sampler['noise_seed']=params['seed']
        latent['length']=params['frames']
        grouped['LTXVConditioning'][0][1]['frame_rate']=params['fps']
        grouped['CreateVideo'][0][1]['fps']=params['fps']
        save=grouped['SaveVideo'][0][1]
        save['filename_prefix']=prefix
        save['format']='mp4'
        save['format.codec']='h264'
        positive=latent.get('positive')
        if not isinstance(positive,list) or graph[positive[0]]['class_type']!='CLIPTextEncode':
            raise ContractError('positive_prompt_node_required')
        graph[positive[0]]['inputs']['text']=params['prompt']
        models=[scoped_path(config.comfy_root,'models/checkpoints/'+MODEL),
                scoped_path(config.comfy_root,'models/text_encoders/'+ENCODER)]
        return graph,models,hashlib.sha256(content).hexdigest()
    if set(grouped)-{'UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','ModelSamplingSD3','EmptyHunyuanLatentVideo','KSampler','VAEDecode','CreateVideo','SaveVideo'}:
        raise ContractError('unsupported_comfy_node')
    if params['frames']>129 or (params['frames']-1)%4:raise ContractError('wan_frame_limit')
    latent=grouped['EmptyHunyuanLatentVideo'][0][1]
    if (any(type(latent.get(key)) is not int or not 16<=latent[key]<=1024 or latent[key]%16 for key in ('width','height'))
        or type(latent.get('batch_size')) is not int or latent['batch_size']!=1):
        raise ContractError('wan_resolution_limit')
    if not config.comfy_root or not config.comfy_endpoint:raise ContractError('comfy_configuration_required')
    models=[]
    for kind,key,folder in (('UNETLoader','unet_name','diffusion_models'),('CLIPLoader','clip_name','text_encoders'),('VAELoader','vae_name','vae')):
        name=grouped[kind][0][1].get(key)
        if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or not name.endswith('.safetensors'):
            raise ContractError('invalid_model_path')
        if kind=='UNETLoader' and not name.lower().startswith('wan'):raise ContractError('wan_model_required')
        model=scoped_path(config.comfy_root,'models/'+folder+'/'+name)
        models.append(model)
    sampler=grouped['KSampler'][0][1]
    if (type(sampler.get('steps')) is not int or not 1<=sampler['steps']<=50
        or type(sampler.get('denoise')) not in (int,float) or not 0<sampler['denoise']<=1):
        raise ContractError('invalid_sampler')
    sampler['seed']=params['seed']
    grouped['EmptyHunyuanLatentVideo'][0][1]['length']=params['frames']
    grouped['CreateVideo'][0][1]['fps']=params['fps']
    save=grouped['SaveVideo'][0][1]
    save['filename_prefix']=prefix
    # DynamicCombo's HTTP inputs are flattened, unlike its execute() argument.
    # Submitting the Python dict silently omits the required format at runtime.
    for key in list(save):
        if key.startswith('format.'):save.pop(key)
    save['format']='mp4'
    save['format.codec']='h264'
    save.pop('codec',None)
    if params.get('prompt'):
        positive=sampler.get('positive')
        if (not isinstance(positive,list) or graph[positive[0]]['class_type']!='CLIPTextEncode'):
            raise ContractError('positive_prompt_node_required')
        graph[positive[0]]['inputs']['text']=params['prompt']
    return graph,models,hashlib.sha256(content).hexdigest()


def model_receipts(paths,check):
    result=[]
    for path in paths:
        if path.stat().st_size>32*1024**3:raise ContractError('model_size_limit')
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for index,block in enumerate(iter(lambda:stream.read(1024*1024),b'')):
                if index%64==0:check()
                digest.update(block)
        result.append({'name':path.name,'bytes':path.stat().st_size,'sha256':digest.hexdigest()})
    return result


def _json(client,method,url,**kwargs):
    with client.stream(method,url,**kwargs) as response:
        if response.status_code>=300:raise ContractError('comfy_request_failed')
        body=bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body)>2*1024**2:raise ContractError('comfy_response_limit')
        value=json.loads(body)
        if not isinstance(value,dict):raise ContractError('invalid_comfy_response')
        return value


def execute(path,destination,params,prefix,config,check,record_prompt,timeout=1800,client_factory=None,expected_digest=None):
    graph,models,source_digest=prepare_workflow(path,params,prefix,config)
    if expected_digest is not None and source_digest!=expected_digest:raise ContractError('input_changed')
    receipts=model_receipts(models,check)
    endpoint=config.comfy_endpoint.rstrip('/')
    prompt_id=None;completed=False
    factory=client_factory or httpx.Client
    with factory(timeout=15,trust_env=False,follow_redirects=False) as client:
        try:
            check()
            submitted=_json(client,'POST',endpoint+'/prompt',json={'prompt':graph,'client_id':prefix})
            prompt_id=submitted.get('prompt_id')
            if not isinstance(prompt_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',prompt_id):
                raise ContractError('invalid_prompt_receipt')
            record_prompt(prompt_id)
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                check()
                history=_json(client,'GET',endpoint+'/history/'+prompt_id).get(prompt_id)
                if history:
                    status=history.get('status',{})
                    if status.get('status_str')=='error':raise ContractError('comfy_execution_failed')
                    if status.get('completed'):
                        outputs=history.get('outputs',{})
                        candidates=[item for node in outputs.values() if isinstance(node,dict)
                                    for field in ('videos','gifs','images') for item in node.get(field,[])
                                    if isinstance(item,dict) and isinstance(item.get('filename'),str)
                                    and item['filename'].startswith(prefix) and item['filename'].endswith('.mp4')]
                        if len(candidates)!=1:raise ContractError('owned_video_missing')
                        item=candidates[0];name=item['filename'];subfolder=item.get('subfolder','')
                        if (Path(name).name!=name or '/' in name or '\\' in name or item.get('type')!='output'
                            or not isinstance(subfolder,str) or (subfolder and not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',subfolder))):
                            raise ContractError('invalid_comfy_artifact')
                        with client.stream('GET',endpoint+'/view',params={'filename':name,'subfolder':subfolder,'type':'output'}) as response:
                            if response.status_code!=200:raise ContractError('comfy_download_failed')
                            with destination.open('xb') as stream:
                                size=0
                                for chunk in response.iter_bytes():
                                    check();size+=len(chunk)
                                    if size>2*1024**3:raise ContractError('artifact_size_limit')
                                    stream.write(chunk)
                        completed=True
                        return {'prompt_id':prompt_id,'models':receipts,'workflow_sha256':source_digest}
                time.sleep(.5)
            raise TimeoutError('render_timeout')
        finally:
            if prompt_id and not completed:
                # Never call global /interrupt: it can stop somebody else's job.
                # Remove only our own pending ID; already running GPU work may
                # continue server-side, while local collection stops immediately.
                try:_json(client,'POST',endpoint+'/queue',json={'delete':[prompt_id]})
                except Exception:pass
