import { spawn, spawnSync } from 'node:child_process';

const candidates = process.platform === 'win32'
  ? [['py', '-3'], ['python'], ['python3']]
  : [['python3'], ['python']];
const selected = candidates.find(([command, ...prefix]) => {
  const probe = spawnSync(command, [...prefix, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'], { stdio: 'ignore' });
  return probe.status === 0;
});
if (!selected) {
  console.error('Python 3.12 이상이 필요합니다. Python을 설치하고 VS Code를 다시 시작하세요.');
  process.exit(1);
}
const [command, ...prefix] = selected;
const child = spawn(command, [...prefix, ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => { if (!child.killed) child.kill(signal); });
}
