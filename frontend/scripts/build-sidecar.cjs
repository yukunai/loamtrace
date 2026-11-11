const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..')
const projectRoot = path.resolve(frontendRoot, '..')
const distPath = path.join(frontendRoot, 'sidecar-bin')
const workPath = path.join(frontendRoot, '.pyinstaller-work')
const specPath = path.join(frontendRoot, '.pyinstaller-spec')

fs.rmSync(distPath, { recursive: true, force: true })
fs.rmSync(workPath, { recursive: true, force: true })
fs.rmSync(specPath, { recursive: true, force: true })
fs.mkdirSync(distPath, { recursive: true })
fs.mkdirSync(workPath, { recursive: true })
fs.mkdirSync(specPath, { recursive: true })

const args = [
  '-m',
  'PyInstaller',
  '--clean',
  '--noconfirm',
  '--onedir',
  '--name',
  'loamtrace-sidecar',
  '--distpath',
  distPath,
  '--workpath',
  workPath,
  '--specpath',
  specPath,
  '--hidden-import',
  'loamtrace.main',
  '--collect-submodules',
  'uvicorn',
  '--collect-submodules',
  'fastapi',
  '--collect-submodules',
  'pydantic',
  '--add-data',
  `${path.join(projectRoot, 'loamtrace', 'static')}${path.delimiter}loamtrace/static`,
  'loamtrace/sidecar_entry.py',
]

const result = spawnSync('python3', args, {
  cwd: projectRoot,
  stdio: 'inherit',
  env: { ...process.env, PYTHONPATH: projectRoot },
})

if (result.status !== 0) {
  process.exit(result.status || 1)
}
