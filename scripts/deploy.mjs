#!/usr/bin/env node
// Publish the site: build dist-public/ here (where the materials are), attach it to a GitHub release
// as site.tar.gz, and start .github/workflows/deploy-pages.yml, which puts it on GitHub Pages.
// Images and videos travel only inside the release asset; they never enter Git.
//
//   npm run deploy            needs the GitHub CLI (gh), logged in with access to the repo
//
// Only Austin decides when the site goes live: run this only with his OK.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const run = (cmd, args) => execFileSync(cmd, args, { cwd: ROOT, stdio: 'inherit' });
const out = (cmd, args) => execFileSync(cmd, args, { cwd: ROOT, encoding: 'utf8' }).trim();

const dirty = out('git', ['status', '--porcelain']);
if (dirty) {
  console.error('Commit (and push) your changes first, so the release records the source it was built from:\n' + dirty);
  process.exit(1);
}
const sha = out('git', ['rev-parse', '--short', 'HEAD']);
const branch = out('git', ['branch', '--show-current']);
const now = new Date();
const pad = (n) => String(n).padStart(2, '0');
const tag = `site-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;

// The strict public build: it stops on anything not cleared, stale or out of step with the catalogue.
run(process.execPath, ['build.mjs', '--public']);

const tmp = mkdtempSync(join(tmpdir(), 'site-'));
try {
  const archive = join(tmp, 'site.tar.gz');
  run('tar', ['-czf', archive, '--exclude', '.portfolio-build', '-C', join(ROOT, 'dist-public'), '.']);
  run('gh', [
    'release', 'create', tag, archive, '--target', 'main', '--title', `Site ${tag.slice(5)}`,
    '--notes', `Built on Austin's Mac from ${branch}@${sha} with npm run deploy; published by the Deploy site workflow.`,
  ]);
  run('gh', ['workflow', 'run', 'deploy-pages.yml', '--ref', 'main', '-f', `tag=${tag}`]);
  console.log(`\nStarted the deploy of ${tag}. Follow it with: gh run watch  (then check https://austinhuang823.github.io/)`);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
