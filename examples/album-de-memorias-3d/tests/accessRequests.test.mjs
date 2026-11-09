import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const sql = readFileSync(new URL('../supabase/002_acesso_com_aprovacao.sql', import.meta.url), 'utf8');
const access = readFileSync(new URL('../src/cloud/AccessPortal.tsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('pedidos exigem login e nao autorizam alteracao de status pelo navegador', () => {
  assert.match(sql, /alter table public\.album_access_requests enable row level security/);
  assert.match(sql, /grant select,insert on public\.album_access_requests to authenticated/);
  assert.match(sql, /revoke update,delete on public\.album_access_requests from authenticated/);
  assert.match(sql, /requester_id=\(select auth\.uid\(\)\)/);
  assert.match(sql, /status='pending'/);
});

test('somente o proprietario autoriza e existe limite de uma pessoa parceira', () => {
  assert.match(sql, /public\.album_my_role\(\)\) is distinct from 'owner'/);
  assert.match(sql, /role='partner'/);
  assert.match(sql, /email_confirmed_at is not null/);
  assert.match(access, /review_album_request/);
  assert.match(access, /p_decision: decision/);
});

test('cadastro e tela de espera estao integrados a aprovacao', () => {
  assert.match(access, /auth\.signUp/);
  assert.match(access, /auth\.signInWithPassword/);
  assert.match(access, /auth\.signInWithOtp/);
  assert.match(access, /Solicitar acesso ao álbum/);
  assert.match(access, /Aprovar/);
  assert.match(access, /Recusar/);
  assert.match(access, /album_access_requests/);
});

test('capa esta personalizada com o monograma do casal', () => {
  assert.match(app, /Rayssa & Marcos Paulo/);
  assert.match(app, /R & M/);
  assert.match(app, /cover-seal/);
});
