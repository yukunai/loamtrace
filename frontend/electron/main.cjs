const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')

const FRONTEND_ROOT = path.resolve(__dirname, '..')
const PROJECT_ROOT = path.resolve(FRONTEND_ROOT, '..')
const API_HOST = process.env.LOAMTRACE_API_HOST || '127.0.0.1'
const DEFAULT_API_PORT = app.isPackaged ? '8180' : '8000'
const API_PORT = Number(process.env.LOAMTRACE_API_PORT || DEFAULT_API_PORT)
const API_BASE = `http://${API_HOST}:${API_PORT}`
const HEALTH_URL = `${API_BASE}/api/health`
const SETTINGS_URL = `${API_BASE}/api/settings/api`

process.env.LOAMTRACE_API_HOST = API_HOST
process.env.LOAMTRACE_API_PORT = String(API_PORT)

let sidecar = null
let ownsSidecar = false

function sidecarRoot() {
  const bundledSidecar = path.join(FRONTEND_ROOT, 'sidecar')
  if (fs.existsSync(path.join(bundledSidecar, 'loamtrace'))) return bundledSidecar
  return PROJECT_ROOT
}

function sidecarExecutable() {
  const bundledExecutable = path.join(FRONTEND_ROOT, 'sidecar-bin', 'loamtrace-sidecar', 'loamtrace-sidecar')
  if (fs.existsSync(bundledExecutable)) return bundledExecutable
  return null
}

function workspaceRoot() {
  if (app.isPackaged) return path.join(app.getPath('userData'), 'workspace')
  return path.join(PROJECT_ROOT, 'workspace')
}

function requestOk(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume()
      resolve(res.statusCode && res.statusCode >= 200 && res.statusCode < 500)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(800, () => {
      req.destroy()
      resolve(false)
    })
  })
}

// 严格 2xx 探测：用于「路由是否存在」的能力探测。
// 不能用 requestOk（它把 404 也当成功，因为 404 < 500），否则旧 sidecar 缺新路由返回 404 仍被误判为"已就绪"而复用。
function requestSucceeded(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume()
      resolve(!!res.statusCode && res.statusCode >= 200 && res.statusCode < 300)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(800, () => {
      req.destroy()
      resolve(false)
    })
  })
}

async function waitForHealth(deadlineMs = 45000) {
  const started = Date.now()
  while (Date.now() - started < deadlineMs) {
    if (await requestOk(HEALTH_URL)) return true
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return false
}

async function ensureSidecar() {
  // 复用已有 sidecar 的前提：health 存活 且 新版能力路由(/api/settings/api)真正 200。
  // settings 用严格 2xx 探测，确保「旧 sidecar 缺该路由 → 404」不会被误判为可复用。
  if ((await requestOk(HEALTH_URL)) && (await requestSucceeded(SETTINGS_URL))) return

  const root = sidecarRoot()
  const executable = sidecarExecutable()
  const command = executable || process.env.LOAMTRACE_PYTHON || 'python3'
  const args = executable
    ? []
    : ['-m', 'uvicorn', 'loamtrace.main:app', '--host', API_HOST, '--port', String(API_PORT)]
  sidecar = spawn(command, args, {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: root,
      LOAMTRACE_WORKSPACE_ROOT: workspaceRoot(),
      LOAMTRACE_API_HOST: API_HOST,
      LOAMTRACE_API_PORT: String(API_PORT),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  ownsSidecar = true

  sidecar.stdout.on('data', (chunk) => process.stdout.write(`[sidecar] ${chunk}`))
  sidecar.stderr.on('data', (chunk) => process.stderr.write(`[sidecar] ${chunk}`))
  sidecar.on('exit', (code, signal) => {
    sidecar = null
    if (code !== 0 && signal !== 'SIGTERM') {
      console.error(`[sidecar] exited code=${code} signal=${signal}`)
    }
  })

  if (!(await waitForHealth())) {
    throw new Error(`LoamTrace sidecar did not become healthy at ${HEALTH_URL}`)
  }
}

async function createWindow() {
  await ensureSidecar()

  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    title: 'LoamTrace',
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  })

  const devUrl = process.env.VITE_DEV_SERVER_URL
  if (devUrl && (await requestOk(devUrl))) {
    await win.loadURL(devUrl)
    win.webContents.openDevTools({ mode: 'detach' })
    return
  }

  const distIndex = path.join(FRONTEND_ROOT, 'dist', 'index.html')
  if (!fs.existsSync(distIndex)) {
    throw new Error('frontend/dist/index.html is missing. Run `npm run build` first.')
  }
  await win.loadFile(distIndex)
}

function stopSidecar() {
  if (ownsSidecar && sidecar && !sidecar.killed) {
    sidecar.kill('SIGTERM')
  }
}

async function openWorkspacePath(targetPath) {
  if (typeof targetPath !== 'string' || targetPath.length === 0) {
    return { ok: false, error: 'invalid_path' }
  }
  const resolved = path.resolve(targetPath)
  const allowedRoot = path.resolve(workspaceRoot())
  if (resolved !== allowedRoot && !resolved.startsWith(`${allowedRoot}${path.sep}`)) {
    return { ok: false, error: 'path_outside_workspace' }
  }
  const error = await shell.openPath(resolved)
  return error ? { ok: false, error } : { ok: true }
}

app.whenReady().then(() => {
  ipcMain.handle('loamtrace:select-document', async () => {
    const focusedWindow = BrowserWindow.getFocusedWindow()
    const result = await dialog.showOpenDialog(focusedWindow || undefined, {
      title: '导入资料',
      properties: ['openFile'],
      filters: [
        { name: 'Source documents', extensions: ['pdf', 'docx', 'xlsx'] },
        { name: 'PDF', extensions: ['pdf'] },
        { name: 'Word', extensions: ['docx'] },
        { name: 'Excel', extensions: ['xlsx'] },
      ],
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  ipcMain.handle('loamtrace:open-path', async (_event, targetPath) => {
    return openWorkspacePath(targetPath)
  })

  ipcMain.handle('loamtrace:open-project-path', async (_event, targetPath) => {
    return openWorkspacePath(targetPath)
  })

  createWindow().catch((error) => {
    console.error(error)
    app.quit()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow().catch((error) => {
        console.error(error)
        app.quit()
      })
    }
  })
})

app.on('before-quit', stopSidecar)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
