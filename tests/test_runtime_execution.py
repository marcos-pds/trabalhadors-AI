"""Real subprocess fixtures for CLI/ACP, not live account homologation."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from central import runtime_execution as execution
from central.external_runtimes import RuntimeBlocked


FIXTURE = r'''
import sys,json,os,time
runtime,mode=sys.argv[1:3]
def emit(value): print(json.dumps(value),flush=True)
if '--version' in sys.argv:
 print({'claude':'2.1.316 (Claude Code)','gemini':'0.66.0','acp':'0.66.0','opencode':'1.19.5'}[runtime]);sys.exit(0)
if mode=='hang':time.sleep(30)
if runtime=='acp':
 while True:
  raw=sys.stdin.readline()
  if not raw:break
  q=json.loads(raw);method=q['method'];rid=q['id']
  if method=='initialize':result={'protocolVersion':1,'agentCapabilities':{},'authMethods':[]}
  elif method=='session/new':
   assert q['params']['mcpServers']==[]
   assert q['params']['cwd']==os.getcwd()
   result={'sessionId':'lab-session'}
  elif method=='session/prompt':
   if mode=='wrong_session':session='other'
   else:session='lab-session'
   if mode=='tool':
    emit({'jsonrpc':'2.0','id':'tool-1','method':'fs/read_text_file','params':{'sessionId':session,'path':'private'}})
    sys.stdin.readline();time.sleep(30)
   emit({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':session,'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'ACP_OK'}}}})
   result={'stopReason':'end_turn'}
  else:raise AssertionError(method)
  emit({'jsonrpc':'2.0','id':rid,'result':result})
else:
 context=json.loads(sys.stdin.read());assert context['system']=='SYSTEM'
 assert os.environ.get('NODE_OPTIONS') is None
 assert os.environ.get('PYTHONPATH') is None
 if mode=='tool':emit({'type':'tool_use'});time.sleep(30)
 if mode=='malformed':print('{not-json',flush=True);time.sleep(30)
 if runtime=='claude':emit({'type':'result','subtype':'success','is_error':False,'result':'CLI_OK'})
 elif runtime=='gemini':
  emit({'type':'message','role':'assistant','content':'CLI_OK'})
  emit({'type':'result','status':'success'})
 else:
  emit({'type':'text','part':{'text':'CLI_OK'}})
  emit({'type':'step_finish'})
 if mode=='exit':sys.exit(7)
'''


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    script = tmp_path / 'runtime.py'
    script.write_text(FIXTURE, encoding='utf-8')
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    monkeypatch.setenv('CENTRAL_ACP_BACKEND', 'gemini')
    monkeypatch.setenv('NODE_OPTIONS', '--malicious')
    monkeypatch.setenv('PYTHONPATH', 'private')
    original = execution.prepare
    def configure(runtime, mode='ok'):
        command = [sys.executable, '-u', str(script), runtime, mode]
        monkeypatch.setattr(execution, 'command', lambda name: list(command))
        # Profiles remain real; only the external executable is replaced.
        return lambda: list(execution.stream(runtime, 'groq/test' if runtime=='opencode' else 'test',
                            'SYSTEM', [{'role':'user','content':'hello'}], api_key='fixture-key', timeout=3))
    yield configure
    assert not [t for t in threading.enumerate() if t.name == 'central-runtime-discovery']


@pytest.mark.parametrize('runtime', ['claude','gemini','opencode','acp'])
def test_real_subprocess_text_and_acp_handshake(launcher, runtime):
    assert launcher(runtime)() == ['ACP_OK' if runtime=='acp' else 'CLI_OK']


@pytest.mark.parametrize('runtime,mode,code', [('gemini','tool','native_tools_requested'),
    ('gemini','malformed','protocol_error'),('gemini','exit','runtime_request_failed'),
    ('acp','tool','native_tools_requested'),('acp','wrong_session','protocol_error')])
def test_tools_foreign_sessions_and_failed_output_are_rejected(launcher,runtime,mode,code):
    with pytest.raises(RuntimeBlocked, match=code):
        launcher(runtime,mode)()


def test_profiles_disable_hooks_mcp_plugins_and_native_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(execution,'command',lambda name:['trusted.exe'])
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path/'managed'))
    for runtime in ('claude','gemini','opencode','acp'):
        root=tmp_path/runtime;root.mkdir()
        argv,env=execution.prepare(runtime,'groq/test' if runtime=='opencode' else 'test','fixture-key',str(root))
        assert 'fixture-key' not in json.dumps(argv)
        assert env['HOME']==str(root)
        assert all('fixture-key' not in p.read_text() for p in root.glob('*') if p.is_file())
        if runtime=='claude':
            assert '--tools' in argv and '--restricted' in argv and '--bare' in argv
        elif runtime in ('gemini','acp'):
            settings=json.loads((root/'settings.json').read_text())
            assert settings['hooksConfig']['enabled'] is False
            assert settings['admin']['mcp']['enabled'] is False
            assert 'decision = "deny"' in (root/'deny.toml').read_text()
        else:
            assert '--pure' in argv
            assert json.loads((root/'opencode.json').read_text())['permission']=='deny'


def test_server_mode_rejects_before_resolving_or_inspecting_prompts(monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE','server')
    monkeypatch.setattr(execution,'command',lambda name:pytest.fail('resolved'))
    with pytest.raises(RuntimeBlocked,match='server_mode_refused'):
        list(execution.stream('gemini',None,None,None,api_key=''))


def test_timeout_kills_owned_child_and_pipe_workers(launcher):
    launcher('gemini','hang')
    with pytest.raises(RuntimeBlocked, match='timeout'):
        list(execution.stream('gemini','test','SYSTEM',[],api_key='fixture-key',timeout=.3))


def test_async_cancellation_closes_runtime_without_blocking_event_loop(launcher):
    launcher('gemini','hang')
    async def exercise():
        async def consume():
            async for _ in execution.stream_response({'kind':'gemini_cli'},'fixture-key','test','SYSTEM',[],timeout=10):
                pass
        task=asyncio.create_task(consume())
        await asyncio.sleep(.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert not [t for t in threading.enumerate() if t.name=='central-runtime-execution']


@pytest.mark.parametrize('status,expected', [(401,'authentication_required'), (429,'runtime_rate_limit'), (413,'input_limit'), (404,'runtime_model_unavailable')])
def test_nested_opencode_error_metadata(status, expected):
    assert execution._failure({'error': {'data': {'statusCode': status, 'message': 'private'}}}) == expected
