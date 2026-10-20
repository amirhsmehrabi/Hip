'use strict';
// Copies what the installed app needs next to its executable: the backend sources, the built frontend, the
// ACE-Step patch and the Stable Audio 3 server sources (installed into a venv on the user's machine). Run by `npm run dist`. Never ships anything from a developer's machine (.env, database, venv).
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const root = path.resolve(__dirname, '..', '..');
const out = path.resolve(__dirname, '..', 'resources');
const skipFrontendBuild = process.argv.includes('--skip-frontend-build');

if (!skipFrontendBuild) {
  // vue-tsc + vite build; needs `npm ci` in frontend/ first.
  const [cmd, args] = process.platform === 'win32'
    ? [process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', 'npm run build']]
    : ['npm', ['run', 'build']];
  execFileSync(cmd, args, { cwd: path.join(root, 'frontend'), stdio: 'inherit' });
}

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

// Top-level backend entries that are local state, not source.
const LOCAL_ONLY = new Set(['.venv', '.env', 'data', 'logs', 'run.bat', 'run.sh']);
const backendSrc = path.join(root, 'backend');
fs.cpSync(backendSrc, path.join(out, 'backend'), {
  recursive: true,
  filter: (src) => {
    const rel = path.relative(backendSrc, src);
    if (!rel) return true;
    if (LOCAL_ONLY.has(rel.split(path.sep)[0])) return false;
    return !rel.split(path.sep).includes('__pycache__') && !rel.endsWith('.pyc');
  },
});

const dist = path.join(root, 'frontend', 'dist');
if (!fs.existsSync(path.join(dist, 'index.html'))) throw new Error('frontend/dist is missing: build the frontend first');
fs.cpSync(dist, path.join(out, 'frontend', 'dist'), { recursive: true });

fs.mkdirSync(path.join(out, 'patches'), { recursive: true });
fs.copyFileSync(path.join(root, 'external', 'patches', 'ace-step.patch'), path.join(out, 'patches', 'ace-step.patch'));

// The Stable Audio 3 server: a uv project; only its sources, not the venv or the WAVs it generated.
const sa3Src = path.join(root, 'external', 'sa3-server');
const SA3_SOURCES = new Set(['pyproject.toml', 'README.md', 'sa3_server']);
fs.cpSync(sa3Src, path.join(out, 'sa3-server'), {
  recursive: true,
  filter: (src) => {
    const rel = path.relative(sa3Src, src);
    if (!rel) return true;
    if (!SA3_SOURCES.has(rel.split(path.sep)[0])) return false;
    return !rel.split(path.sep).includes('__pycache__') && !rel.endsWith('.pyc');
  },
});

// Guard: fail the build rather than ship personal data.
const forbidden = [];
(function scan(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (['.venv', '__pycache__'].includes(e.name)) forbidden.push(p); else scan(p); }
    else if (e.name === '.env' || /\.(db|sqlite3?)$/i.test(e.name)) forbidden.push(p);
  }
})(out);
if (forbidden.length) throw new Error(`refusing to package local files:\n${forbidden.join('\n')}`);

console.log(`resources ready in ${out}`);
