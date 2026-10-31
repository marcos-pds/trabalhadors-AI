'use strict';
// Separate output protects the existing unsigned installer. Never silently fall back.
if (!/^[a-f0-9]{40}$/i.test(process.env.CENTRAL_SIGN_CERT_SHA1 || '')) {
  throw new Error('Certificado ausente: configure CENTRAL_SIGN_CERT_SHA1 antes do build assinado.');
}
const base = require('./package.json').build;
const hooks = require('./signing.cjs');
module.exports = {
  ...base,
  extends: null,
  directories: { ...base.directories, output: 'dist-signed' },
  forceCodeSigning: true,
  afterPack: hooks.afterPack,
  win: {
    ...base.win,
    signAndEditExecutable: true,
    signExecutable: true,
    // Additional native extensions retain any existing explicit inclusions.
    signExts: [...new Set([...(base.win.signExts || []), '.dll', '.pyd'])],
    signtoolOptions: {
      ...base.win.signtoolOptions,
      signingHashAlgorithms: ['sha256'],
      sign: hooks.sign,
    },
  },
};
