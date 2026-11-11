const { contextBridge, ipcRenderer } = require('electron')

const host = process.env.LOAMTRACE_API_HOST || '127.0.0.1'
const port = process.env.LOAMTRACE_API_PORT || '8000'

contextBridge.exposeInMainWorld('loamtrace', {
  apiBase: `http://${host}:${port}`,
  selectDocumentPath: () => ipcRenderer.invoke('loamtrace:select-document'),
  openPath: (targetPath) => ipcRenderer.invoke('loamtrace:open-path', targetPath),
  openProjectPath: (targetPath) => ipcRenderer.invoke('loamtrace:open-project-path', targetPath),
})
