import test from 'node:test'
import assert from 'node:assert/strict'
import { activityLabel, compactActivityEvents, mergeActivityEvents } from './conversationActivity.mjs'

test('polling merges events once in server order and bounds the visible history', () => {
  const initial = [{seq:1,event:'run_created'}, {seq:2,event:'worker_phase'}]
  assert.deepEqual(mergeActivityEvents(initial, [{seq:2,event:'worker_phase'}, {seq:3,event:'run_completed'}]).map(e => e.seq), [1,2,3])
  const events = mergeActivityEvents([], Array.from({length:250}, (_, seq) => ({seq})))
  assert.equal(events.length, 200)
  assert.equal(events[0].seq, 50)
})

test('compact logs keep failures while removing heartbeat, duplicated tool messages and repeated skill lists', () => {
  const events = [
    {seq:1,event:'skill_context_selected',selected_skills:[{name:'Design'}, {name:'Design'}]},
    {seq:2,event:'worker_heartbeat'},
    {seq:3,event:'skill_context_selected',selected_skills:[{name:'Design'}]},
    {seq:4,event:'workspace_action_requested',step_id:'s',action:'replace',path:'App.tsx',description:'Alterar'},
    {seq:5,event:'workspace_action_result',step_id:'s',action:'replace',path:'App.tsx',description:'Alterar',success:false,detail:'Conflito de edição'},
    {seq:6,event:'worker_message',action:'replace'},
  ]
  const visible = compactActivityEvents(events)
  assert.deepEqual(visible.map(e => e.seq), [1,5])
  assert.equal(activityLabel(visible[0]), 'Skills: Design')
  assert.equal(activityLabel(visible[1]), 'Falha: App.tsx')
})

test('an operation still in progress remains visible until a matching result arrives', () => {
  const request = {seq:1,event:'workspace_action_requested',step_id:'s',action:'read',path:'App.tsx'}
  const unrelated = {seq:2,event:'workspace_action_result',step_id:'other',action:'read',path:'App.tsx',success:true}
  assert.equal(compactActivityEvents([request,unrelated]).length, 2)
})

test('failed validation is never described as successful validation', () => {
  assert.equal(activityLabel({event:'workspace_validation',success:false}), 'Validação falhou')
  assert.equal(activityLabel({event:'workspace_validation',success:true}), 'Validação concluída')
})
