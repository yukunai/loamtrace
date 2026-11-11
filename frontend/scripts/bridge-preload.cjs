const { contextBridge } = require('electron')

const calls = []

contextBridge.exposeInMainWorld('loamtrace', {
  apiBase: '',
  selectDocumentPath: async () => {
    calls.push({ name: 'selectDocumentPath', args: [] })
    return '/tmp/loamtrace-bridge-qa/input/bridge-document.pdf'
  },
  selectSyncDirectory: async () => {
    calls.push({ name: 'selectSyncDirectory', args: [] })
    return '/tmp/loamtrace-bridge-qa/sync'
  },
  openPath: async (targetPath) => {
    calls.push({ name: 'openPath', args: [targetPath] })
    return { ok: true }
  },
  openProjectPath: async (targetPath) => {
    calls.push({ name: 'openProjectPath', args: [targetPath] })
    return { ok: true }
  },
  appMetadata: async () => ({ version: 'bridge-qa', platform: process.platform, shell: 'qa' }),
})

contextBridge.exposeInMainWorld('__bridgeQa', {
  calls: () => calls.slice(),
})
