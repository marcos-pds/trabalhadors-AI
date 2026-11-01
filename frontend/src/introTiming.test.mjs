import test from 'node:test';
import assert from 'node:assert/strict';
import {GLASS_CASCADE_DURATION_MS,mountGlassCascade,sampleGlassCascade} from './intro/glass-cascade.mjs';

function browserStub({blocked=false,reduced=false,pending=false}={}) {
  const names=['document','window','Audio','performance','requestAnimationFrame','cancelAnimationFrame','setTimeout','clearTimeout','ResizeObserver'];
  const saved=new Map(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  let now=0,nextId=0,focusRestored=0;
  const timers=new Map(),frames=new Map(),audioInstances=[];
  class Events {
    constructor(){this.listeners=new Map();}
    addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(fn);}
    removeEventListener(name,fn){this.listeners.get(name)?.delete(fn);}
    emit(name,event={}){for(const fn of this.listeners.get(name)||[])fn(event);}
  }
  class Element extends Events {
    constructor(){super();this.style={setProperty(name,value){this[name]=value;}};this.dataset={};this.attrs={};this.children=[];this.inert=false;this.parent=null;this.isConnected=true;this.disabled=false;this.classList={contains:()=>false};this.parts=new Map();}
    setAttribute(name,value){this.attrs[name]=value;}
    appendChild(el){this.children.push(el);el.parent=this;}
    remove(){this.isConnected=false;if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);}
    contains(element){return this.children.includes(element);}
    querySelectorAll(selector){if(selector==='[data-cia-card]'){if(!this.cards)this.cards=Array.from({length:6},()=>new Element());return this.cards;}return [];}
    querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
    getBoundingClientRect(){return{width:1280,height:720};}
    focus(){document.activeElement=this;}
  }
  const body=new Element();body.style.overflow='auto';
  const appRoot=new Element();
  const doc=new Events();doc.body=body;doc.documentElement=new Element();doc.hidden=false;
  doc.activeElement={isConnected:true,focus(){focusRestored++;}};
  doc.createElement=()=>new Element();
  const win=new Events();win.matchMedia=query=>({matches:query.includes('reduced-motion')?reduced:false});
  class FakeAudio extends Events {
    constructor(src){super();this.src=src;this.duration=7;this.currentTime=0;this.playCalls=0;this.pauseCalls=0;this.loadCalls=0;this.allow=!blocked;audioInstances.push(this);}
    play(){this.playCalls++;if(pending)return new Promise(resolve=>{this.resolvePlay=resolve;});return this.allow?Promise.resolve():Promise.reject(Object.assign(new Error('Autoplay blocked'),{name:'NotAllowedError'}));}
    pause(){this.pauseCalls++;}
    removeAttribute(name){if(name==='src')this.src='';}
    load(){this.loadCalls++;}
  }
  const overrides={document:doc,window:win,Audio:FakeAudio,performance:{now:()=>now},
    requestAnimationFrame:fn=>{const id=++nextId;frames.set(id,fn);return id;},
    cancelAnimationFrame:id=>frames.delete(id),
    setTimeout:(fn,delay)=>{const id=++nextId;timers.set(id,{at:now+delay,fn});return id;},
    clearTimeout:id=>timers.delete(id),
    ResizeObserver:class{observe(){}disconnect(){this.disconnected=true;}}
  };
  for(const [key,value] of Object.entries(overrides))Object.defineProperty(globalThis,key,{configurable:true,writable:true,value});
  function advance(ms){now=ms;for(const [id,timer] of [...timers]){if(timer.at<=now){timers.delete(id);timer.fn();}}const callbacks=[...frames.values()];frames.clear();for(const fn of callbacks)fn(now);}
  return{body,appRoot,doc,advance,audioInstances,timers,frames,get focusRestored(){return focusRestored;},restore(){for(const name of names){const descriptor=saved.get(name);if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globalThis[name];}}};
}

test('Duração é 7000 ms; todas as poses permanecem finitas e encerram no limite',()=>{
 assert.equal(GLASS_CASCADE_DURATION_MS,7000);
 for(let i=0;i<6;i++)for(const ms of [-50,0,300,1000,1800,3100,6150,6600,6999,7000,12000]){
   const pose=sampleGlassCascade(ms,i);
   for(const key of ['x','y','scale','rotate','rotateY','opacity','exit'])assert.ok(Number.isFinite(pose[key]),key);
   assert.ok(pose.opacity>=0&&pose.opacity<=1);
   assert.ok(pose.scale>0);
 }
 assert.equal(sampleGlassCascade(6999,0).complete,false);
 assert.equal(sampleGlassCascade(7000,0).complete,true);
 assert.equal(sampleGlassCascade(6150,0).exit,0);
 assert.equal(sampleGlassCascade(7000,0).exit,1);
 assert.throws(()=>sampleGlassCascade(0,6),RangeError);
});

test('A sobreposição permanece até 6999 ms e libera a Central aos 7000 ms, uma única vez',async()=>{
 const b=browserStub();let calls=0;
 try{
  const intro=mountGlassCascade({sound:false,appRoot:b.appRoot,onComplete:()=>calls++});
  assert.equal(b.appRoot.inert,true);
  assert.equal(b.body.children.length,1);
  b.advance(6999);
  assert.equal(b.body.children.length,1);assert.equal(calls,0);
  b.advance(7000);
  const result=await intro.finished;
  assert.deepEqual(result,{reason:'completed',durationMs:7000,elapsedMs:7000});
  assert.equal(b.body.children.length,0);assert.equal(b.body.style.overflow,'auto');
  assert.equal(b.appRoot.inert,false);assert.equal(b.focusRestored,1);
  assert.equal(b.timers.size,0);assert.equal(b.frames.size,0);
  intro.skip();intro.destroy();assert.equal(calls,1);
 }finally{b.restore();}
});

test('Autoplay bloqueado não atrasa a abertura; clique habilita áudio alinhado ao tempo atual',async()=>{
 const b=browserStub({blocked:true});
 try{
  const intro=mountGlassCascade();const overlay=b.body.children[0],audio=b.audioInstances[0];
  await Promise.resolve();await Promise.resolve();
  assert.equal(overlay.querySelector('[data-cia-sound]').textContent,'Ativar som');
  b.advance(2000);audio.allow=true;
  assert.equal(await intro.enableSound(),true);assert.equal(audio.currentTime,2);
  assert.equal(overlay.querySelector('[data-cia-sound]').textContent,'Silenciar');
  await intro.setMuted(true);assert.equal(overlay.querySelector('[data-cia-sound]').textContent,'Ativar som');
  b.advance(7000);assert.equal((await intro.finished).reason,'completed');
  assert.ok(audio.pauseCalls>0);assert.equal(audio.src,'');
 }finally{b.restore();}
});

test('Pular cancela som, timer e renderização sem deixar a tela bloqueada',async()=>{
 const b=browserStub();
 try{
  const intro=mountGlassCascade({sound:false});b.advance(1750);intro.skip();
  assert.equal((await intro.finished).elapsedMs,1750);
  assert.equal((await intro.finished).reason,'skipped');
  assert.equal(b.body.children.length,0);assert.equal(b.timers.size,0);assert.equal(b.frames.size,0);
 }finally{b.restore();}
});

test('Desmontagem de React/StrictMode cancela áudio pendente e não chama onComplete',async()=>{
 const b=browserStub({pending:true});let calls=0;
 try{
  const first=mountGlassCascade({onComplete:()=>calls++});
  const audio=b.audioInstances[0];first.destroy();audio.resolvePlay();
  await Promise.resolve();await Promise.resolve();
  assert.equal((await first.finished).reason,'destroyed');assert.equal(calls,0);
  assert.ok(audio.pauseCalls>=2);assert.equal(b.body.children.length,0);
  const second=mountGlassCascade({sound:false});assert.equal(b.body.children.length,1);
  b.advance(7000);assert.equal((await second.finished).reason,'completed');
 }finally{b.restore();}
});

test('Movimento reduzido mantém composição estável e prazo de sete segundos',async()=>{
 const b=browserStub({reduced:true});
 try{
  for(let i=0;i<6;i++){
   const initial=sampleGlassCascade(0,i,true),end=sampleGlassCascade(6999,i,true);
   assert.equal(initial.x,end.x);assert.equal(initial.y,end.y);assert.equal(initial.rotateY,0);
  }
  const intro=mountGlassCascade({sound:false});b.advance(7000);
  assert.equal((await intro.finished).durationMs,7000);
 }finally{b.restore();}
});

test('Erro de arquivo de áudio não impede encerramento ou acesso ao chat',async()=>{
 const b=browserStub();
 try{
  const intro=mountGlassCascade({sound:false});b.audioInstances[0].emit('error');
  const overlay=b.body.children[0];assert.equal(overlay.querySelector('[data-cia-sound]').disabled,true);
  b.advance(7000);assert.equal((await intro.finished).reason,'completed');
 }finally{b.restore();}
});

test('WAV estéreo PCM tem exatamente sete segundos, pico seguro e fim sem descontinuidade',async()=>{
 const {readFile}=await import('node:fs/promises');
 const wav=await readFile(new URL('./intro/glass-cascade-7s.wav',import.meta.url));
 assert.equal(wav.toString('ascii',0,4),'RIFF');
 assert.equal(wav.toString('ascii',8,12),'WAVE');
 assert.equal(wav.readUInt16LE(22),2);
 assert.equal(wav.readUInt32LE(24),48000);
 assert.equal(wav.readUInt16LE(34),16);
 assert.equal(wav.readUInt32LE(40)/wav.readUInt32LE(28),7);
 let peak=0;for(let i=44;i<wav.length;i+=2)peak=Math.max(peak,Math.abs(wav.readInt16LE(i)));
 assert.ok(peak>0);assert.ok(peak/32767<.6);
 assert.equal(wav.readInt16LE(44),0);assert.equal(wav.readInt16LE(wav.length-2),0);
});

test('Uma tentativa antiga de áudio não silencia uma reprodução nova',async()=>{
 const b=browserStub();
 try{
  const intro=mountGlassCascade({sound:false}),audio=b.audioInstances[0],resolvers=[];
  audio.play=()=>new Promise(resolve=>resolvers.push(resolve));
  const first=intro.enableSound();await intro.setMuted(true);
  const pauseCount=audio.pauseCalls;
  const second=intro.enableSound();resolvers[0]();await first;
  assert.equal(audio.pauseCalls,pauseCount);
  resolvers[1]();assert.equal(await second,true);
  assert.equal(b.body.children[0].querySelector('[data-cia-sound]').textContent,'Silenciar');
  intro.destroy();
 }finally{b.restore();}
});
