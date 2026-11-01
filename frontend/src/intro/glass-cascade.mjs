/**
 * Central IA · Cascata de Vidro
 * 7,000 ms. Sem dependências de animação.
 * Importe também glass-cascade.css.
 */
export const GLASS_CASCADE_DURATION_MS = 7000;
const EXIT_START = 6150;
const clamp = (value, min=0, max=1) => Math.max(min,Math.min(max,value));
const lerp = (a,b,p) => a+(b-a)*p;
const ease = value => 1-Math.pow(1-clamp(value),4);
const spring = value => value<=0?0:value>=1?1:1-Math.exp(-7*value)*Math.cos(11*value);
const PROVIDERS = [
  {
    "name": "OpenAI",
    "color": "#34806b",
    "mark": "<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\"><g stroke=\"currentColor\" stroke-width=\".91\" stroke-linejoin=\"round\" stroke-linecap=\"round\"><path d=\"M12 3.6c-4-2.3-8.1 1-7 5.4l3.4 5.9 6.4 3.7 3.2-1.9V9.3L12 5.6 8.8 7.5v7.4\" transform=\"rotate(0 12 12)\"/><path d=\"M12 3.6c-4-2.3-8.1 1-7 5.4l3.4 5.9 6.4 3.7 3.2-1.9V9.3L12 5.6 8.8 7.5v7.4\" transform=\"rotate(60 12 12)\"/><path d=\"M12 3.6c-4-2.3-8.1 1-7 5.4l3.4 5.9 6.4 3.7 3.2-1.9V9.3L12 5.6 8.8 7.5v7.4\" transform=\"rotate(120 12 12)\"/><path d=\"M12 3.6c-4-2.3-8.1 1-7 5.4l3.4 5.9 6.4 3.7 3.2-1.9V9.3L12 5.6 8.8 7.5v7.4\" transform=\"rotate(180 12 12)\"/><path d=\"M12 3.6c-4-2.3-8.1 1-7 5.4l3.4 5.9 6.4 3.7 3.2-1.9V9.3L12 5.6 8.8 7.5v7.4\" transform=\"rotate(240 12 12)\"/><path d=\"M12 3.6c-4-2.3-8.1 1-7 5.4l3.4 5.9 6.4 3.7 3.2-1.9V9.3L12 5.6 8.8 7.5v7.4\" transform=\"rotate(300 12 12)\"/></g></svg>"
  },
  {
    "name": "Claude",
    "color": "#c87859",
    "mark": "<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\"><g stroke=\"currentColor\" stroke-width=\"1.9\" stroke-linecap=\"square\"><path d=\"M12 3v6.1\" transform=\"rotate(0 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(30 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(60 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(90 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(120 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(150 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(180 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(210 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(240 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(270 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(300 12 12)\"/><path d=\"M12 3v6.1\" transform=\"rotate(330 12 12)\"/></g></svg>"
  },
  {
    "name": "Gemini",
    "color": "#7b85d1",
    "mark": "<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\"><defs><linearGradient id=\"g\" x1=\"0\" x2=\"1\" y2=\"1\"><stop stop-color=\"#4c91ed\"/><stop offset=\".5\" stop-color=\"#9276d5\"/><stop offset=\"1\" stop-color=\"#d894b8\"/></linearGradient></defs><path d=\"M12 1c0 6.075 4.925 11 11 11-6.075 0-11 4.925-11 11C12 16.925 7.075 12 1 12 7.075 12 12 7.075 12 1Z\" fill=\"url(#g)\"/></svg>"
  },
  {
    "name": "DeepSeek",
    "color": "#507bc4",
    "mark": "<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\"><path d=\"M2 8c3 1.2 5.8 1.8 8.5.7C14 4 18 4.8 20 8.8l3-1.6-1.4 4.5c-1 6.7-8.7 9.5-14.2 5.2C4 14.2 3.3 12 2 8Z\" fill=\"currentColor\"/><path d=\"m5 8-3-4 6 3\" fill=\"currentColor\"/><path d=\"M9 15.7c2.3 1.4 5 1.2 7-.2\" stroke=\"white\" stroke-width=\".9\" stroke-linecap=\"round\"/><circle cx=\"17.2\" cy=\"10.2\" r=\".8\" fill=\"white\"/></svg>"
  },
  {
    "name": "Meta",
    "color": "#3e8ec5",
    "mark": "<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\"><path d=\"M2.5 15.5c0-5.9 2.4-10 5-10 3.1 0 5.6 6.3 8 10.6 2.7 4.8 6 2.5 6-1.1 0-5.7-2.2-9.5-4.7-9.5-3.4 0-5.8 6.7-8.5 11C5.8 20.5 2.5 19.5 2.5 15.5Z\" stroke=\"currentColor\" stroke-width=\"2.5\" stroke-linecap=\"round\"/></svg>"
  },
  {
    "name": "Mistral",
    "color": "#eea246",
    "mark": "<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\"><g fill=\"currentColor\"><path d=\"M2 3h4v4H2zm16 0h4v4h-4zM2 7h8v4H2zm12 0h8v4h-8zM2 11h20v4H2zm0 4h4v6H2zm8 0h4v3h-4zm8 0h4v6h-4z\"/></g><path d=\"M2 3h4v4H2zm16 0h4v4h-4\" fill=\"#f9c34e\"/><path d=\"M2 18h4v3H2zm16 0h4v3h-4\" fill=\"#e36d46\"/></svg>"
  }
];
let activeIntro = null;
let serial = 0;

/** Posição determinística: também permite testar a duração sem um navegador. */
export function sampleGlassCascade(elapsedMs, index, reducedMotion=false) {
  if(!Number.isInteger(index)||index<0||index>=PROVIDERS.length)throw new RangeError('Índice de ícone inválido.');
  const ms=clamp(Number.isFinite(elapsedMs)?elapsedMs:0,0,GLASS_CASCADE_DURATION_MS);
  const time=ms/1000;
  const p=reducedMotion?1:spring((time-.3-index*.16)/2);
  const ex=(index-2.5)*118,ey=-93+Math.pow(index-2.5,2)*7;
  const exit=reducedMotion?0:Math.pow(clamp((ms-EXIT_START)/(GLASS_CASCADE_DURATION_MS-EXIT_START)),2);
  const drift=reducedMotion?0:ease((time-2.5)/1.4);
  return {
    x:lerp(ex*1.5,ex,p)+Math.sin(time*.55+index*1.5)*5*drift,
    y:lerp(-530-index*25,ey,p)+Math.cos(time*.7+index*1.2)*6*drift-exit*30,
    scale:lerp(.5,1.1,p),
    rotate:lerp(index%2?70:-70,(index-2.5)*9,p),
    rotateY:lerp(130,0,p),
    opacity:reducedMotion?1:clamp((time-.2-index*.16)*2),
    exit,
    complete:ms>=GLASS_CASCADE_DURATION_MS
  };
}

function detectTheme(theme) {
  if(theme==='light'||theme==='dark')return theme;
  const html=document.documentElement;
  if(html.dataset.theme==='dark'||html.classList.contains('dark'))return 'dark';
  if(html.dataset.theme==='light')return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
}

/**
 * Abre a animação imediatamente e devolve controles e a Promise finished.
 * O som é solicitado, mas um bloqueio de autoplay nunca atrasa a abertura.
 * Chame dentro de um clique para iniciar com som quando o navegador exigir.
 */
export function mountGlassCascade(options={}) {
  if(typeof document==='undefined')throw new Error('Monte a abertura no cliente, dentro de useEffect ou depois de DOMContentLoaded.');
  if(activeIntro)activeIntro.destroy();
  const parent=options.container||document.body;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const previousFocus=document.activeElement;
  const previousOverflow=document.body.style.overflow;
  const appRoot=options.appRoot||null;
  const previousInert=appRoot?appRoot.inert:false;
  if(appRoot&&(appRoot===parent||appRoot.contains(parent)))throw new Error('O container da abertura deve ficar fora de appRoot.');
  const id='cia-glass-intro-'+(++serial);
  const overlay=document.createElement('section');
  overlay.className='cia-intro';
  overlay.dataset.theme=detectTheme(options.theme||'auto');
  overlay.setAttribute('role','dialog');
  overlay.setAttribute('aria-modal','true');
  overlay.setAttribute('aria-labelledby',id+'-title');
  overlay.tabIndex=-1;
  overlay.innerHTML=
    '<div class="cia-intro__glow" aria-hidden="true"></div>'+
    '<div class="cia-intro__grid" aria-hidden="true"></div>'+
    '<div class="cia-intro__particles" aria-hidden="true">'+
      Array.from({length:32},(_,i)=>'<i style="left:'+(8+(i*29%84))+'%;top:'+(12+(i*37%76))+'%;--cia-delay:'+(i*.17)+'s"></i>').join('')+'</div>'+
    '<div class="cia-intro__top"><span class="cia-intro__brand">CENTRAL IA<span> / </span>CASCATA DE VIDRO</span>'+
    '<div class="cia-intro__actions"><button type="button" data-cia-sound aria-pressed="false">Ativar som</button>'+
    '<button type="button" data-cia-skip>Pular abertura <span aria-hidden="true">↗</span></button></div></div>'+
    '<div class="cia-intro__world"><div class="cia-intro__cards">'+
      PROVIDERS.map((provider,index)=>'<div class="cia-intro__card" data-cia-card="'+index+'" style="--cia-icon:'+provider.color+'"><span class="cia-intro__glass">'+provider.mark+'</span></div>').join('')+
    '</div><div class="cia-intro__copy"><p class="cia-intro__eyebrow">CENTRAL DE TRABALHADORES IA</p>'+
    '<h1 id="'+id+'-title">O futuro<br><em>ganha forma.</em></h1>'+
    '<p class="cia-intro__subtitle">Cada inteligência encontra o seu lugar.</p></div></div>'+
    '<div class="cia-intro__bottom"><span>UMA NOVA IDEIA COMEÇA AQUI</span><span data-cia-time>7s</span></div>'+
    '<div class="cia-intro__progress" aria-hidden="true"></div>'+
    '<span class="cia-intro__status" role="status" aria-live="polite" data-cia-status></span>';
  parent.appendChild(overlay);
  const cards=[...overlay.querySelectorAll('[data-cia-card]')];
  const copy=overlay.querySelector('.cia-intro__copy');
  const soundButton=overlay.querySelector('[data-cia-sound]');
  const skipButton=overlay.querySelector('[data-cia-skip]');
  const status=overlay.querySelector('[data-cia-status]');
  const timeLabel=overlay.querySelector('[data-cia-time]');
  let ended=false,rafId=0,timeoutId=0,resizeObserver=null,audio=null;
  let audioState='off',playAttempt=0;
  let resolveFinished;
  const finished=new Promise(resolve=>{resolveFinished=resolve;});
  const startTime=performance.now();
  const elapsed=()=>clamp(performance.now()-startTime,0,GLASS_CASCADE_DURATION_MS);

  function soundLabel() {
    soundButton.textContent=audioState==='playing'?'Silenciar':audioState==='error'?'Som indisponível':'Ativar som';
    soundButton.setAttribute('aria-pressed',String(audioState==='playing'));
    soundButton.disabled=audioState==='error';
  }
  function alignAudio() {
    if(!audio||ended)return;
    try{audio.currentTime=Math.min(elapsed()/1000,Number.isFinite(audio.duration)?audio.duration:7);}catch{}
  }
  function handleAudioError() {
    if(ended)return;
    audioState='error';
    soundLabel();
    status.textContent='O som não pôde ser carregado. A abertura continua normalmente.';
  }
  try {
    audio=new Audio(options.audioUrl||new URL('./glass-cascade-7s.wav',import.meta.url).href);
    audio.preload='auto';
    audio.loop=false;
    audio.volume=clamp(options.volume??.55);
    audio.addEventListener('loadedmetadata',alignAudio);
    audio.addEventListener('error',handleAudioError);
  }catch{audioState='error';}
  soundLabel();

  async function enableSound() {
    if(ended||!audio||audioState==='error')return false;
    const attempt=++playAttempt;
    alignAudio();
    try {
      await audio.play();
      if(ended){audio.pause();return false;}
      if(attempt!==playAttempt)return false;
      audioState='playing';
      soundLabel();
      status.textContent='Som ativado.';
      return true;
    }catch(error){
      if(ended||attempt!==playAttempt)return false;
      audioState=error?.name==='NotSupportedError'?'error':'blocked';
      soundLabel();
      status.textContent=audioState==='error'?'O som não pôde ser carregado.':'Clique em Ativar som para ouvir a abertura.';
      return false;
    }
  }
  function setMuted(muted) {
    if(!muted)return enableSound();
    ++playAttempt;
    audio?.pause();
    if(audioState!=='error')audioState='off';
    soundLabel();
    return Promise.resolve(true);
  }
  function resize() {
    const rect=overlay.getBoundingClientRect();
    const scale=Math.max(.1,Math.min(rect.width/(rect.width<600?850:1100),(rect.height-110)/500,1.25));
    overlay.style.setProperty('--cia-scale',String(scale));
  }
  function render(ms) {
    cards.forEach((card,index)=>{
      const pose=sampleGlassCascade(ms,index,reduced);
      card.style.transform='translate('+pose.x+'px,'+pose.y+'px) scale('+pose.scale+') rotate('+pose.rotate+'deg) perspective(800px) rotateY('+pose.rotateY+'deg)';
      card.style.opacity=String(pose.opacity);
    });
    const reveal=reduced?1:ease((ms-1450)/1450);
    const exit=sampleGlassCascade(ms,0,reduced).exit;
    copy.style.opacity=String(reveal);
    copy.style.transform='translateY('+(20+(1-reveal)*28)+'px)';
    copy.style.filter=reduced?'none':'blur('+((1-reveal)*9)+'px)';
    overlay.style.opacity=String(1-exit);
    overlay.style.setProperty('--cia-progress',String(clamp(ms/GLASS_CASCADE_DURATION_MS)));
    timeLabel.textContent=Math.ceil((GLASS_CASCADE_DURATION_MS-ms)/1000)+'s';
  }
  function cleanAudio() {
    ++playAttempt;
    if(!audio)return;
    audio.removeEventListener('loadedmetadata',alignAudio);
    audio.removeEventListener('error',handleAudioError);
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  }
  function finish(reason) {
    if(ended)return;
    ended=true;
    clearTimeout(timeoutId);
    cancelAnimationFrame(rafId);
    resizeObserver?.disconnect();
    window.removeEventListener('resize',resize);
    document.removeEventListener('visibilitychange',onVisibility);
    overlay.removeEventListener('keydown',onKey);
    cleanAudio();
    overlay.remove();
    document.body.style.overflow=previousOverflow;
    if(appRoot)appRoot.inert=previousInert;
    if(activeIntro===controller)activeIntro=null;
    if(previousFocus?.isConnected&&typeof previousFocus.focus==='function')previousFocus.focus({preventScroll:true});
    const result={reason,durationMs:GLASS_CASCADE_DURATION_MS,elapsedMs:elapsed()};
    resolveFinished(result);
    if(reason!=='destroyed')options.onComplete?.(result);
  }
  function frame() {
    if(ended)return;
    const ms=elapsed();
    if(ms>=GLASS_CASCADE_DURATION_MS){finish('completed');return;}
    render(ms);
    rafId=requestAnimationFrame(frame);
  }
  function onVisibility() {
    if(!document.hidden&&elapsed()>=GLASS_CASCADE_DURATION_MS)finish('completed');
  }
  function onKey(event) {
    if(event.key==='Escape'){event.preventDefault();finish('skipped');return;}
    if(event.key==='Tab'){
      const controls=[soundButton,skipButton].filter(button=>!button.disabled);
      const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey&&(document.activeElement===first||document.activeElement===overlay)){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===overlay)){event.preventDefault();first.focus();}
    }
  }
  const controller={
    finished,
    enableSound,
    setMuted,
    skip:()=>finish('skipped'),
    destroy:()=>finish('destroyed')
  };
  activeIntro=controller;
  soundButton.addEventListener('click',()=>{if(audioState==='playing')void setMuted(true);else void enableSound();});
  skipButton.addEventListener('click',controller.skip);
  overlay.addEventListener('keydown',onKey);
  document.addEventListener('visibilitychange',onVisibility);
  window.addEventListener('resize',resize);
  if(typeof ResizeObserver!=='undefined'){resizeObserver=new ResizeObserver(resize);resizeObserver.observe(overlay);}
  document.body.style.overflow='hidden';
  if(appRoot)appRoot.inert=true;
  resize();
  render(0);
  overlay.focus({preventScroll:true});
  // Nunca aguarda áudio, downloads ou fontes para iniciar ou terminar.
  if(options.sound!==false)void enableSound();
  timeoutId=setTimeout(()=>finish('completed'),GLASS_CASCADE_DURATION_MS);
  rafId=requestAnimationFrame(frame);
  return controller;
}
