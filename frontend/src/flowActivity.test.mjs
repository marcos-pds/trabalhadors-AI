import test from 'node:test'
import assert from 'node:assert/strict'
import { flowActivity } from './flowActivity.mjs'

const steps = [
  {id:'a',agent_id:'architect',name:'Arquitetura',status:'running',deps:[]},
  {id:'b',agent_id:'frontend',name:'Interface',status:'queued',deps:['a']},
]
test('pending dependencies are shown as next stage without fabricating a dialogue', () => {
  const view = flowActivity({status:'running',steps,events:[]})
  assert.equal(view.sender.id,'architect')
  assert.equal(view.recipient.id,'frontend')
  assert.equal(view.message,undefined)
  assert.equal(view.done,0)
  assert.equal(view.verified,false)
})
test('only persisted messages supply dialogue and participants', () => {
  const message={sender_agent_id:'architect',recipient_agent_id:'frontend',sender_name:'Ana',recipient_name:'Bia',content:'Contrato salvo.'}
  const view=flowActivity({status:'running',steps,agent_messages:[message]},
    [{id:'architect',provider_id:'g'}],[{id:'g',kind:'gemini'}])
  assert.equal(view.text,'Contrato salvo.')
  assert.equal(view.sender.kind,'gemini')
  assert.equal(view.recipient.name,'Bia')
})
test('completed is not a verified delivery and the latest real step is retained', () => {
  const view=flowActivity({status:'completed',steps:steps.map(s=>({...s,status:'completed'})),events:[
    {seq:1,event:'step_status',step_id:'a',status:'completed'},
    {seq:2,event:'run_completed'},
  ]})
  assert.equal(view.current.id,'a')
  assert.equal(view.moving,false)
  assert.equal(view.verified,false)
  assert.equal(view.done,2)
})
test('failed checks and stale activity never animate or imply successful validation', () => {
  const view=flowActivity({status:'running',steps,events:[{seq:1,event:'workspace_validation',success:false}]},[],[],true)
  assert.equal(view.moving,false)
  assert.equal(view.sender.working,false)
  assert.equal(view.logs[0].failed,true)
  assert.match(view.logs[0].text,/falhou/)
})
