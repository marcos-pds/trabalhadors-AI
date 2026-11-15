import test from 'node:test';
import assert from 'node:assert/strict';
import { directScene } from './scene_direction.mjs';

test('walking direction selects forward camera and footsteps', () => {
  assert.deepEqual(directScene({ title: 'Corredor', prompt: 'Câmera avança enquanto ouvimos passos', duration_frames: 360 }).camera, 'push_in');
  assert.equal(directScene({ prompt: 'Walking down a hallway' }).effect, 'footsteps');
});

test('door slam and expressive voice follow requested action', () => {
  const scene = directScene({ prompt: 'A porta bate com força; narrador sussurra', duration_frames: 360 });
  assert.equal(scene.effect, 'door_slam');
  assert.equal(scene.expressive, 'whisper');
  assert.equal(scene.cue, 9.3);
});

test('no sound effect is invented for an unrelated scene', () => {
  assert.equal(directScene({ prompt: 'A mulher olha uma fotografia' }).effect, null);
});

test('walking sound from brief follows a camera push scene', () => {
  const direction = directScene({ title: 'A Aproximação', prompt: 'The camera pushes forward steadily.' },
    'Passos distantes ecoam no corredor.');
  assert.equal(direction.camera, 'push_in');
  assert.equal(direction.effect, 'footsteps');
});

test('location alone does not invent a camera move', () => {
  assert.equal(directScene({ prompt: 'The shadow stands still in the corridor' }).camera, 'gentle');
  assert.equal(directScene({ prompt: 'Camera moves slowly forward through the corridor' }).camera, 'push_in');
});
