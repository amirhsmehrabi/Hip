'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { resourcePaths } = require('../src/paths');

// The installed app looks for its sources under process.resourcesPath; each folder it names there has to be copied
// in by electron-builder, or picking that part at setup fails with "the sources are missing from this build".
test('every folder the installed app reads from resources is packaged by electron-builder', () => {
  const yml = fs.readFileSync(path.join(__dirname, '..', 'electron-builder.yml'), 'utf8');
  const packaged = new Set([...yml.matchAll(/^\s+to:\s*(\S+)\s*$/gm)].map((m) => m[1]));
  const saved = process.resourcesPath;
  process.resourcesPath = path.join(path.sep, 'res');
  try {
    for (const [key, p] of Object.entries(resourcePaths(true))) {
      const top = path.relative(process.resourcesPath, p).split(path.sep)[0];
      assert.ok(packaged.has(top), `${key} reads resources/${top}, which electron-builder.yml does not package`);
    }
  } finally {
    process.resourcesPath = saved;
  }
});
