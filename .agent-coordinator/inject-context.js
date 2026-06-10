import { execFileSync } from 'child_process';
import fs from 'fs';
import path from 'path';

const KB_MARKER = 'SHARED KNOWLEDGE BASE (Obsidian)';

export function findProjectRoot(fromDir) {
  let dir = path.resolve(fromDir, '..');
  for (let i = 0; i < 10; i++) {
    try {
      if (fs.existsSync(path.join(dir, '.agent-coordinator'))) return dir;
    } catch (_) {}
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return process.cwd();
}

export function injectCoordinatorContext(tool, root) {
  try {
    execFileSync('coordinator', ['context', 'inject', tool], { stdio: 'inherit', cwd: root });
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    execFileSync('npx', ['coordinator', 'context', 'inject', tool], { stdio: 'inherit', cwd: root });
  }
  appendKnowledgeBaseContext(root);
}

function appendKnowledgeBaseContext(root) {
  const kbFile = path.join(root, '.agent-coordinator/knowledge-base.md');
  const contextFile = path.join(root, '.agent-coordinator/context-inject.txt');
  if (!fs.existsSync(kbFile)) return;

  const existing = fs.existsSync(contextFile) ? fs.readFileSync(contextFile, 'utf8') : '';
  if (existing.includes(KB_MARKER)) return;

  const kb = fs.readFileSync(kbFile, 'utf8');
  const block = `\n\n---\n${KB_MARKER}:\n---\n\n${kb}`;
  fs.appendFileSync(contextFile, block, 'utf8');
}
