import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const sql = readFileSync(new URL('../supabase/001_album_privado.sql', import.meta.url), 'utf8');
const cloud = readFileSync(new URL('../src/cloud/supabase.ts', import.meta.url), 'utf8');

test('a leitura e escrita das paginas exige membro autorizado com RLS', () => {
  assert.match(sql, /alter table public\.album_pages enable row level security;/);
  assert.match(sql, /for select to authenticated using \(public\.is_couple_member\(\)\)/);
  assert.match(sql, /for insert to authenticated with check \(public\.is_couple_member\(\)\)/);
  assert.match(sql, /for update to authenticated using \(public\.is_couple_member\(\)\)/);
});

test('fotos sempre usam bucket privado e URLs assinadas', () => {
  assert.match(sql, /'album-private', 'album-private', false/);
  assert.match(sql, /create policy "couple_read_photos"/);
  assert.match(cloud, /PRIVATE_BUCKET = 'album-private'/);
  assert.doesNotMatch(cloud, /service_role|sb_secret_/);
});

test('allowlist de acesso nao fica exposta ao cliente', () => {
  assert.match(sql, /revoke all on schema private from public, anon, authenticated/);
  assert.match(sql, /from private\.couple_allowlist/);
});
