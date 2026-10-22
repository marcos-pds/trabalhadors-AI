const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

const html=fs.readFileSync('static/index.html','utf8');
const css=fs.readFileSync('static/gemini-theme.css','utf8');
const app=fs.readFileSync('static/app.js','utf8');

test('minimal visual theme loads after the existing styles and preserves the app entrypoint',()=>{
 assert.match(html,/href="\/assets\/style\.css"/);
 assert.match(html,/href="\/assets\/gemini-theme\.css"/);
 assert.ok(html.indexOf('/assets/gemini-theme.css')>html.indexOf('/assets/style.css'));
 assert.match(html,/src="\/assets\/app\.js"/);
 assert.match(html,/name="theme-color" content="#181818"/);
});

test('theme exposes grayscale and accessible light-mode tokens, responsive breakpoints',()=>{
 for(const token of ['--bg: #181818','--side: #202020','--panel: #242424',
                     '--line: #373737','--text: #e9eaed']){
  assert.ok(css.includes(token),token);
 }
 assert.ok(css.includes('body.light'));
 assert.ok(css.includes('.chat-welcome'));
 assert.ok(css.includes('.chat-slash-menu'));
 assert.ok(css.includes('.composer-box'));
 assert.ok(css.includes('.drawer-content .chat-context-bar'));
 assert.ok(css.includes('@media (max-width: 540px)'));
 assert.ok(css.includes('prefers-reduced-motion'));
 assert.ok(css.includes('[hidden] { display: none !important; }'));
});

test('SVGs are generated from an internal whitelist, without remote resources',async()=>{
 const {uiSvg}=await import('../static/ui-icons.mjs');
 for(const name of ['menu','close','plus','paperclip','send','sparkles',
  'dashboard','chat','agents','workflows','projects','workspace','skills',
  'history','monitoring','providers','settings','code','search','stop']){
  const icon=uiSvg(name,18);
  assert.ok(icon.includes('<svg'),name);
  assert.ok(icon.includes('aria-hidden="true"'),name);
  assert.ok(icon.includes('stroke="currentColor"'),name);
  assert.ok(!icon.includes('<script'),name);
 }
 assert.equal(uiSvg('<img src=x onerror=alert(1)>'),uiSvg('sparkles'));
 assert.equal(uiSvg('menu',100).includes('width="36"'),true);
 assert.ok(!html.includes('cdn.tailwindcss.com'));
 assert.ok(!html.includes('unpkg.com'));
});

test('new visual elements do not remove slash commands or project permissions',()=>{
 assert.ok(app.includes("import { uiSvg } from './ui-icons.mjs'"));
 assert.ok(app.includes('id="workspace-menu"'));
 assert.ok(app.includes('id="chat-project"')||app.includes('chatContextBar()'));
 assert.ok(app.includes('id="chat-slash-menu"'));
 assert.ok(app.includes('id="chat-send"'));
 assert.ok(app.includes('aria-label="Enviar mensagem"'));
 assert.ok(app.includes('data-action="chat-review-open"'));
 assert.ok(app.includes("case 'iniciar':await startRuntime();return;"));
 assert.ok(app.includes("case 'revisar':await loadChatPendingReviews()"));
 assert.ok(app.includes('data-suggest="Crie uma interface'));
});
