"""Controlled HTTP protocol proof, not real Wan inference."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from central.comfy_motion import execute,prepare_workflow
from central.motion_contracts import MotionConfig,ContractError


def workflow():
    return {
      '1':{'class_type':'UNETLoader','inputs':{'unet_name':'wan-fixture.safetensors'}},
      '2':{'class_type':'CLIPLoader','inputs':{'clip_name':'text.safetensors','type':'wan'}},
      '3':{'class_type':'VAELoader','inputs':{'vae_name':'vae.safetensors'}},
      '4':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'positive'}},
      '5':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'negative'}},
      '6':{'class_type':'EmptyHunyuanLatentVideo','inputs':{'width':64,'height':64,'length':5,'batch_size':1}},
      '7':{'class_type':'KSampler','inputs':{'model':['1',0],'positive':['4',0],'negative':['5',0],'latent_image':['6',0],'seed':1,'steps':1,'denoise':1}},
      '8':{'class_type':'VAEDecode','inputs':{'samples':['7',0],'vae':['3',0]}},
      '9':{'class_type':'CreateVideo','inputs':{'images':['8',0],'fps':24}},
      '10':{'class_type':'SaveVideo','inputs':{'video':['9',0],'filename_prefix':'unsafe-original','format':'auto'}},
    }


@pytest.fixture
def configured(tmp_path):
    root=tmp_path/'comfy';root.mkdir();(root/'main.py').write_text('fixture')
    for folder,name in [('diffusion_models','wan-fixture.safetensors'),('text_encoders','text.safetensors'),('vae','vae.safetensors')]:
        path=root/'models'/folder/name;path.parent.mkdir(parents=True);path.write_bytes(b'inert model fixture')
    path=tmp_path/'workflow.json';path.write_text(json.dumps(workflow()))
    return path,MotionConfig(comfy_endpoint='http://127.0.0.1:8189',comfy_root=str(root))


def test_only_owned_prompt_video_is_collected_and_parameters_are_bound(configured,tmp_path):
    path,config=configured;original=path.read_bytes();calls=[];recorded=[]
    def respond(request):
        calls.append(request)
        if request.url.path=='/prompt':
            graph=json.loads(request.content)['prompt']
            assert graph['7']['inputs']['seed']==7 and graph['6']['inputs']['length']==9
            assert graph['9']['inputs']['fps']==16 and graph['4']['inputs']['text']=='new prompt'
            assert graph['10']['inputs']['filename_prefix']=='central_owned'
            assert graph['10']['inputs']['format']=='mp4'
            assert graph['10']['inputs']['format.codec']=='h264'
            return httpx.Response(200,json={'prompt_id':'prompt-1'})
        if request.url.path=='/history/prompt-1':
            return httpx.Response(200,json={'prompt-1':{'status':{'completed':True},'outputs':{'10':{'images':[{'filename':'central_owned_00001_.mp4','subfolder':'','type':'output'}]}}}})
        assert request.url.path=='/view'
        return httpx.Response(200,content=b'\x00\x00\x00\x18ftypisomfixture')
    client=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(respond),**kwargs)
    result=execute(path,tmp_path/'out.mp4',{'model':'wan','seed':7,'frames':9,'fps':16,'prompt':'new prompt'},
                   'central_owned',config,lambda:None,recorded.append,client_factory=client)
    assert recorded==['prompt-1'] and len(result['models'])==3
    assert path.read_bytes()==original and (tmp_path/'out.mp4').exists()
    assert all(request.url.host=='127.0.0.1' for request in calls)


def test_cancel_deletes_only_own_queued_id_never_global_interrupt(configured,tmp_path):
    path,config=configured;calls=[];submitted=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'prompt_id':'owned-1'} if request.url.path=='/prompt' else {})
    def check():
        if submitted:raise InterruptedError('cancelled')
    client=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(respond),**kwargs)
    with pytest.raises(InterruptedError):
        execute(path,tmp_path/'out.mp4',{'model':'wan','seed':1,'frames':5,'fps':24},'owned',config,check,submitted.append,client_factory=client)
    assert [r.url.path for r in calls]==['/prompt','/queue']
    assert json.loads(calls[-1].content)=={'delete':['owned-1']}
    assert not (tmp_path/'out.mp4').exists()


@pytest.mark.parametrize('mutate',[
    lambda g:g['1'].update(class_type='ArbitraryCustomNode'),
    lambda g:g['7']['inputs'].update(latent_image=['7',0]),
    lambda g:g['1']['inputs'].update(unet_name='../outside.safetensors'),
    lambda g:g['8']['inputs'].update(samples=['6',0]),
    lambda g:g['7']['inputs'].update(denoise=0),
    lambda g:g['6']['inputs'].update(width=16384),
    lambda g:g['6']['inputs'].update(batch_size=32),
])
def test_unsafe_or_non_generation_workflows_are_rejected_before_network(configured,mutate):
    path,config=configured;data=workflow();mutate(data);path.write_text(json.dumps(data))
    with pytest.raises(ContractError):
        prepare_workflow(path,{'model':'wan','seed':1,'frames':5,'fps':24},'owned',config)
