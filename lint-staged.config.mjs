import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(root, 'inspector', 'frontend');
const runner = path.join(root, 'scripts', 'eslint-fix-chunk.mjs');

/** Runner path safe for argv on Windows */
const runnerArg = JSON.stringify(runner.replace(/\\/g, '/'));

/**
 * Stay below ~8k so argv limits are not hit. lint-staged's --max-arg-length only
 * counts raw filepath length; include runner path + JSON quoting here.
 */
const MAX_CMD_CHARS = 7000;

/**
 * @param {string[]} filenames
 * @returns {string | string[]}
 */
function eslintFixCommands(filenames) {
  if (filenames.length === 0) {
    return [];
  }
  const rel = filenames
    .map((f) => {
      const abs = path.isAbsolute(f) ? f : path.join(root, f);
      return path.relative(frontendRoot, abs).replace(/\\/g, '/');
    })
    .filter((r) => r.length > 0 && !r.startsWith('..'));

  const commands = [];
  let batch = [];
  /** `node RUNNER` + space + quoted paths */
  let curLen = `node ${runnerArg} `.length;

  const flush = () => {
    if (batch.length === 0) {
      return;
    }
    commands.push(`node ${runnerArg} ${batch.map((r) => JSON.stringify(r)).join(' ')}`);
    batch = [];
    curLen = `node ${runnerArg} `.length;
  };

  for (const r of rel) {
    const quoted = JSON.stringify(r);
    const increment = batch.length === 0 ? quoted.length : 1 + quoted.length;
    if (batch.length > 0 && curLen + increment > MAX_CMD_CHARS) {
      flush();
    }
    batch.push(r);
    curLen += increment;
  }
  flush();

  if (commands.length === 0) {
    return [];
  }
  return commands.length === 1 ? commands[0] : commands;
}

/** @type {import('lint-staged').Configuration} */
export default {
  'inspector/frontend/**/*.{ts,js,svelte}': (filenames) => eslintFixCommands(filenames),
};
