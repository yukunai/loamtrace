const { app, BrowserWindow } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..')
const distIndex = path.join(frontendRoot, 'dist', 'index.html')
const artifactsRoot = path.resolve(frontendRoot, '..', 'artifacts', 'bridge-qa')

const checks = []

app.whenReady().then(async () => {
  fs.mkdirSync('/tmp/loamtrace-bridge-qa/input', { recursive: true })
  fs.mkdirSync('/tmp/loamtrace-bridge-qa/sync', { recursive: true })
  fs.mkdirSync(artifactsRoot, { recursive: true })
  fs.writeFileSync('/tmp/loamtrace-bridge-qa/input/bridge-document.pdf', 'bridge qa placeholder')

  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, 'bridge-preload.cjs'),
    },
  })

  try {
    await win.loadFile(distIndex)
    await waitForSelector(win, '.app')
    await waitForSelector(win, '.mini-btn[title="打开项目目录"]')

    await click(win, '.mini-btn[title="打开项目目录"]')
    await delay(200)
    await recordCall(win, 'project reveal calls openPath', 'openPath')

    await click(win, '.import-btn[title="导入文档"]')
    await waitForText(win, 'bridge-document.pdf', 2500)
    await recordCall(win, 'import calls selectDocumentPath', 'selectDocumentPath')

    await click(win, '.settings-entry')
    await waitForSelector(win, '.settings-modal')
    await clickButtonByText(win, '选择目录')
    await waitForInputValue(win, '/tmp/loamtrace-bridge-qa/sync', 2500)
    await recordCall(win, 'sync target calls selectSyncDirectory', 'selectSyncDirectory')

    const calls = await bridgeCalls(win)
    const failed = checks.filter((check) => !check.ok)
    const report = {
      generated_at: new Date().toISOString(),
      status: failed.length ? 'failed' : 'passed',
      checks,
      calls,
    }
    fs.writeFileSync(path.join(artifactsRoot, 'report.json'), JSON.stringify(report, null, 2))
    if (failed.length) {
      console.error(`[bridge-qa] failed: ${failed.map((check) => check.name).join(', ')}`)
      app.exit(1)
      return
    }
    console.log(`[bridge-qa] passed; artifacts: ${artifactsRoot}`)
    app.exit(0)
  } catch (error) {
    checks.push({ name: 'script error', ok: false, detail: error instanceof Error ? error.message : String(error) })
    fs.writeFileSync(
      path.join(artifactsRoot, 'report.json'),
      JSON.stringify({ generated_at: new Date().toISOString(), status: 'failed', checks, calls: [] }, null, 2),
    )
    console.error(`[bridge-qa] ${error instanceof Error ? error.message : String(error)}`)
    app.exit(1)
  }
})

function record(name, ok, detail = '') {
  checks.push({ name, ok: Boolean(ok), detail })
}

async function recordCall(win, name, callName) {
  const calls = await bridgeCalls(win)
  const call = calls.find((item) => item.name === callName)
  record(name, Boolean(call), call ? JSON.stringify(call.args) : 'missing')
}

async function bridgeCalls(win) {
  return win.webContents.executeJavaScript('window.__bridgeQa.calls()')
}

async function click(win, selector) {
  const clicked = await win.webContents.executeJavaScript(`
    (() => {
      const node = document.querySelector(${JSON.stringify(selector)})
      if (!node) return false
      node.click()
      return true
    })()
  `)
  if (!clicked) throw new Error(`missing selector ${selector}`)
}

async function clickButtonByText(win, text) {
  const clicked = await win.webContents.executeJavaScript(`
    (() => {
      const node = Array.from(document.querySelectorAll('button'))
        .find((button) => button.textContent.includes(${JSON.stringify(text)}))
      if (!node) return false
      node.click()
      return true
    })()
  `)
  if (!clicked) throw new Error(`missing button text ${text}`)
}

async function waitForSelector(win, selector, timeoutMs = 2500) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const exists = await win.webContents.executeJavaScript(`!!document.querySelector(${JSON.stringify(selector)})`)
    if (exists) return
    await delay(50)
  }
  throw new Error(`timed out waiting for ${selector}`)
}

async function waitForText(win, text, timeoutMs = 2500) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const exists = await win.webContents.executeJavaScript(`document.body.innerText.includes(${JSON.stringify(text)})`)
    if (exists) return
    await delay(50)
  }
  throw new Error(`timed out waiting for text ${text}`)
}

async function waitForInputValue(win, value, timeoutMs = 2500) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const exists = await win.webContents.executeJavaScript(`
      Array.from(document.querySelectorAll('input')).some((input) => input.value === ${JSON.stringify(value)})
    `)
    if (exists) return
    await delay(50)
  }
  throw new Error(`timed out waiting for input value ${value}`)
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
