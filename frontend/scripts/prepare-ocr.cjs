const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const frontendRoot = path.resolve(__dirname, '..')
const ocrRoot = path.join(frontendRoot, 'ocr')

fs.rmSync(ocrRoot, { recursive: true, force: true })

const result = spawnSync(
  'python3',
  [
    '-c',
    'from pathlib import Path; import tesseract_bin; print(Path(tesseract_bin.__file__).parent / "data")',
  ],
  { encoding: 'utf8' },
)

if (result.status !== 0) {
  console.warn('[prepare-ocr] tesseract-bin is not installed; packaged app will use system/user OCR if available.')
  process.exit(0)
}

const dataRoot = result.stdout.trim()
const sourceBinary = path.join(dataRoot, 'bin', 'tesseract')
const sourceTessdata = path.join(dataRoot, 'share', 'tessdata')

if (!fs.existsSync(sourceBinary) || !fs.existsSync(sourceTessdata)) {
  console.warn(`[prepare-ocr] tesseract-bin data is incomplete at ${dataRoot}; skipping OCR bundle.`)
  process.exit(0)
}

copyFile(sourceBinary, path.join(ocrRoot, 'bin', 'tesseract'), 0o755)
copyDir(sourceTessdata, path.join(ocrRoot, 'share', 'tessdata'))
console.log(`[prepare-ocr] bundled OCR from ${dataRoot}`)

function copyFile(src, dest, mode) {
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.copyFileSync(src, dest)
  fs.chmodSync(dest, mode)
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name)
    const destPath = path.join(dest, entry.name)
    if (entry.isDirectory()) copyDir(srcPath, destPath)
    else if (entry.isFile()) fs.copyFileSync(srcPath, destPath)
  }
}
