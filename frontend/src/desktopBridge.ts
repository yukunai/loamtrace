type OpenPathResult = { ok: boolean; error?: string }

type TauriApi = {
  core?: {
    invoke?: <T>(command: string, args?: Record<string, unknown>) => Promise<T>
  }
}

declare global {
  interface Window {
    readonly __TAURI__?: TauriApi
  }
}

const tauriInvoke = window.__TAURI__?.core?.invoke

if (!window.loamtrace && tauriInvoke) {
  Object.defineProperty(window, 'loamtrace', {
    configurable: false,
    enumerable: true,
    value: {
      apiBase: '',
      selectDocumentPath: () => tauriInvoke<string | null>('select_document_path'),
      selectSyncDirectory: () => tauriInvoke<string | null>('choose_sync_directory'),
      openPath: (targetPath: string) => tauriInvoke<OpenPathResult>('open_path', { targetPath }),
      openProjectPath: (targetPath: string) => tauriInvoke<OpenPathResult>('open_project_path', { targetPath }),
      appMetadata: () => tauriInvoke('app_metadata'),
    },
  })
}

export {}
