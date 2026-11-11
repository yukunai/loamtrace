const fs = require('node:fs')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..')
const projectRoot = path.resolve(frontendRoot, '..')
const sidecarRoot = path.join(frontendRoot, 'sidecar')

fs.rmSync(sidecarRoot, { recursive: true, force: true })
fs.mkdirSync(sidecarRoot, { recursive: true })

copyDir(path.join(projectRoot, 'loamtrace'), path.join(sidecarRoot, 'loamtrace'))
for (const filename of ['requirements.txt', 'pyproject.toml']) {
  fs.copyFileSync(path.join(projectRoot, filename), path.join(sidecarRoot, filename))
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue
    const srcPath = path.join(src, entry.name)
    const destPath = path.join(dest, entry.name)
    if (entry.isDirectory()) copyDir(srcPath, destPath)
    else if (entry.isFile()) fs.copyFileSync(srcPath, destPath)
  }
}
