import test from 'node:test';
import assert from 'node:assert/strict';
import { fromRows, makeInitialRows, toRow } from '../src/cloud/albumRows.ts';

const sheet = {
  id: 'sheet-1',
  front: { type: 'editable', text: 'oi', imageUrl: 'blob:https://teste.local/abc', photoPath: 'photos/foto.jpg' },
  back: { type: 'editable', text: 'lembrança' }
};

test('nunca salva blob URL ou link temporário no banco', () => {
  const row = toRow(sheet, 'front', 0, 'usuario');
  assert.equal(row.photo_path, 'photos/foto.jpg');
  assert.equal('imageUrl' in row.content, false);
  assert.equal('photoPath' in row.content, false);
});

test('frente e verso são salvos como registros independentes', () => {
  const rows = makeInitialRows([sheet], 'usuario');
  assert.deepEqual(rows.map(r => r.side), ['front', 'back']);
  assert.equal(rows[0].sheet_id, rows[1].sheet_id);
  assert.equal(rows[0].position, rows[1].position);
});

test('reconstrói livro com fotos assinadas e mantém posição original', () => {
  const rows = [
    ...makeInitialRows([sheet], 'usuario'),
    toRow({ id: 'sheet-2', front: { type: 'editable', text: 'mais' }, back: { type: 'editable', text: 'outro' } }, 'front', 1)
  ].reverse();
  const book = fromRows(rows, { 'photos/foto.jpg': 'https://signed.url/xyz' });
  assert.equal(book.length, 2);
  assert.equal(book[0].id, 'sheet-1');
  assert.equal(book[0].front.imageUrl, 'https://signed.url/xyz');
  assert.equal(book[0].back.text, 'lembrança');
});
