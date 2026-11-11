/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string
  readonly VITE_API_TARGET?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  readonly loamtrace?: {
    readonly apiBase?: string
    readonly selectDocumentPath?: () => Promise<string | null>
    readonly selectSyncDirectory?: () => Promise<string | null>
    readonly openPath?: (targetPath: string) => Promise<{ ok: boolean; error?: string }>
    readonly openProjectPath?: (targetPath: string) => Promise<{ ok: boolean; error?: string }>
    readonly appMetadata?: () => Promise<{ version: string; platform: string; shell: string }>
  }
}
