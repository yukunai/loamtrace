import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ApiConnectionTestResult, ApiSettings, SyncSettings, SyncSettingsTestResult } from '../types'

const PROVIDERS = [
  { id: 'openai-compatible', label: 'OpenAI-compatible', baseUrl: '' },
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { id: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { id: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com' },
  { id: 'qwen', label: '通义千问 / DashScope', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { id: 'moonshot', label: 'Moonshot / Kimi', baseUrl: 'https://api.moonshot.cn/v1' },
  { id: 'groq', label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1' },
  { id: 'anthropic', label: 'Anthropic', baseUrl: 'https://api.anthropic.com' },
  { id: 'gemini', label: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta' },
  { id: 'custom', label: '自定义', baseUrl: '' },
]

interface Props {
  onError: (message: string) => void
}

export function ApiSettingsPanel({ onError }: Props) {
  const [settings, setSettings] = useState<ApiSettings | null>(null)
  const [provider, setProvider] = useState('openai-compatible')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ApiConnectionTestResult | null>(null)
  const [syncSettings, setSyncSettings] = useState<SyncSettings | null>(null)
  const [syncProvider, setSyncProvider] = useState<'local' | 's3-compatible'>('local')
  const [syncTargetDir, setSyncTargetDir] = useState('')
  const [syncEndpointUrl, setSyncEndpointUrl] = useState('')
  const [syncBucket, setSyncBucket] = useState('')
  const [syncRegion, setSyncRegion] = useState('')
  const [syncPrefix, setSyncPrefix] = useState('loamtrace-sync')
  const [syncAccessKey, setSyncAccessKey] = useState('')
  const [syncSecretKey, setSyncSecretKey] = useState('')
  const [clearSyncSecret, setClearSyncSecret] = useState(false)
  const [savingSync, setSavingSync] = useState(false)
  const [testingSync, setTestingSync] = useState(false)
  const [testingSyncLive, setTestingSyncLive] = useState(false)
  const [syncTestResult, setSyncTestResult] = useState<SyncSettingsTestResult | null>(null)

  useEffect(() => {
    api
      .getApiSettings()
      .then((next) => {
        setSettings(next)
        setProvider(next.provider)
        setBaseUrl(next.base_url)
        setModel(next.model)
      })
      .catch((err) => onError(errMsg(err)))
    api
      .getSyncSettings()
      .then((next) => {
        setSyncSettings(next)
        setSyncProvider(next.provider === 's3-compatible' ? 's3-compatible' : 'local')
        setSyncTargetDir(next.target_dir)
        setSyncEndpointUrl(next.endpoint_url)
        setSyncBucket(next.bucket)
        setSyncRegion(next.region)
        setSyncPrefix(next.prefix)
      })
      .catch((err) => onError(errMsg(err)))
  }, [onError])

  function changeProvider(nextProvider: string) {
    setProvider(nextProvider)
    const preset = PROVIDERS.find((item) => item.id === nextProvider)
    if (preset?.baseUrl) setBaseUrl(preset.baseUrl)
  }

  async function save() {
    setSaving(true)
    try {
      const saved = await api.saveApiSettings({
        provider,
        base_url: baseUrl,
        model,
        api_key: apiKey || undefined,
        clear_api_key: clearKey,
      })
      setSettings(saved)
      setProvider(saved.provider)
      setBaseUrl(saved.base_url)
      setModel(saved.model)
      setApiKey('')
      setClearKey(false)
      onError('API 设置已保存')
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setSaving(false)
    }
  }

  async function testConnection() {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await api.testApiSettings({
        provider,
        base_url: baseUrl,
        model,
        api_key: apiKey || undefined,
        clear_api_key: clearKey,
      })
      setTestResult(result)
    } catch (err) {
      setTestResult({
        ok: false,
        provider,
        base_url: baseUrl,
        model,
        status: 'request_failed',
        checked_url: null,
        http_status: null,
        model_status: 'not_checked',
        available_models: [],
        detail: errMsg(err),
      })
    } finally {
      setTesting(false)
    }
  }

  const syncPayload = () => ({
    provider: syncProvider,
    target_dir: syncTargetDir,
    endpoint_url: syncEndpointUrl,
    bucket: syncBucket,
    region: syncRegion,
    prefix: syncPrefix,
    access_key_id: syncAccessKey || undefined,
    secret_access_key: syncSecretKey || undefined,
    clear_secret: clearSyncSecret,
  })

  async function saveSync() {
    setSavingSync(true)
    try {
      const saved = await api.saveSyncSettings(syncPayload())
      setSyncSettings(saved)
      setSyncProvider(saved.provider === 's3-compatible' ? 's3-compatible' : 'local')
      setSyncTargetDir(saved.target_dir)
      setSyncEndpointUrl(saved.endpoint_url)
      setSyncBucket(saved.bucket)
      setSyncRegion(saved.region)
      setSyncPrefix(saved.prefix)
      setSyncAccessKey('')
      setSyncSecretKey('')
      setClearSyncSecret(false)
      onError('同步设置已保存')
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setSavingSync(false)
    }
  }

  async function testSync() {
    setTestingSync(true)
    setSyncTestResult(null)
    try {
      setSyncTestResult(await api.testSyncSettings(syncPayload()))
    } catch (err) {
      setSyncTestResult({
        ok: false,
        provider: syncProvider,
        status: 'request_failed',
        target_dir: syncTargetDir,
        missing_fields: [],
        detail: errMsg(err),
      })
    } finally {
      setTestingSync(false)
    }
  }

  async function testSyncLive() {
    setTestingSyncLive(true)
    setSyncTestResult(null)
    try {
      setSyncTestResult(await api.testConfiguredSyncProviderLive())
    } catch (err) {
      setSyncTestResult({
        ok: false,
        provider: syncProvider,
        status: 'request_failed',
        target_dir: syncTargetDir,
        missing_fields: [],
        detail: errMsg(err),
      })
    } finally {
      setTestingSyncLive(false)
    }
  }

  async function chooseSyncTargetDir() {
    const selected = await window.loamtrace?.selectSyncDirectory?.()
    if (selected) setSyncTargetDir(selected)
  }

  return (
    <div className="panel api-settings-panel">
      <div className="settings-grid">
        <label>
          <span>Provider</span>
          <select value={provider} onChange={(event) => changeProvider(event.target.value)}>
            {PROVIDERS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Base URL</span>
          <input
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </label>
        <label>
          <span>Model</span>
          <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="按你的账号填写" />
        </label>
        <label>
          <span>API Key</span>
          <input
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={settings?.api_key_configured ? '已保存，留空不变' : '未设置'}
            type="password"
          />
        </label>
      </div>
      <div className="settings-actions">
        <label className="settings-check">
          <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} />
          清除已保存密钥
        </label>
        <span className={`key-status ${settings?.api_key_configured ? 'configured' : ''}`}>
          {settings?.api_key_configured ? '密钥已设置' : '未设置密钥'}
        </span>
        <button className="secondary" onClick={testConnection} disabled={testing}>
          {testing ? '测试中' : '测试连接'}
        </button>
        <button onClick={save} disabled={saving}>
          {saving ? '保存中' : '保存'}
        </button>
      </div>
      {testResult && (
        <div className={`connection-result ${testResult.ok ? 'ok' : 'fail'}`}>
          <div className="connection-status">
            {testResult.ok ? '连接成功' : `连接失败：${connectionStatusLabel(testResult.status)}`}
          </div>
          <div className="connection-meta">
            {testResult.http_status ? `HTTP ${testResult.http_status}` : '未建立连接'}
            {testResult.model_status !== 'not_checked' && ` · 模型${modelStatusLabel(testResult.model_status)}`}
          </div>
          {testResult.checked_url && <div className="connection-url">{testResult.checked_url}</div>}
          {testResult.available_models.length > 0 && (
            <div className="model-suggestions">
              <span>可用模型</span>
              {testResult.available_models.slice(0, 8).map((item) => (
                <button key={item} onClick={() => setModel(item)} title={`使用 ${item}`}>
                  {item}
                </button>
              ))}
            </div>
          )}
          {testResult.detail && <div className="connection-detail">{testResult.detail}</div>}
        </div>
      )}
      <div className="settings-section-title">同步配置</div>
      <div className="settings-grid">
        <label>
          <span>Sync Provider</span>
          <select value={syncProvider} onChange={(event) => setSyncProvider(event.target.value as 'local' | 's3-compatible')}>
            <option value="local">Local folder</option>
            <option value="s3-compatible">S3 / R2 compatible</option>
          </select>
        </label>
        <label>
          <span>Target Dir</span>
          <input
            value={syncTargetDir}
            onChange={(event) => setSyncTargetDir(event.target.value)}
            placeholder="/Volumes/PrivateSync/LoamTrace"
            disabled={syncProvider !== 'local'}
          />
          <button type="button" onClick={chooseSyncTargetDir} disabled={syncProvider !== 'local' || !window.loamtrace?.selectSyncDirectory}>
            选择目录
          </button>
        </label>
        <label>
          <span>Endpoint URL</span>
          <input
            value={syncEndpointUrl}
            onChange={(event) => setSyncEndpointUrl(event.target.value)}
            placeholder="https://account.r2.cloudflarestorage.com"
            disabled={syncProvider === 'local'}
          />
        </label>
        <label>
          <span>Bucket</span>
          <input value={syncBucket} onChange={(event) => setSyncBucket(event.target.value)} disabled={syncProvider === 'local'} />
        </label>
        <label>
          <span>Region</span>
          <input value={syncRegion} onChange={(event) => setSyncRegion(event.target.value)} placeholder="auto" disabled={syncProvider === 'local'} />
        </label>
        <label>
          <span>Prefix</span>
          <input value={syncPrefix} onChange={(event) => setSyncPrefix(event.target.value)} placeholder="loamtrace-sync" />
        </label>
        <label>
          <span>Access Key</span>
          <input
            value={syncAccessKey}
            onChange={(event) => setSyncAccessKey(event.target.value)}
            placeholder={syncSettings?.access_key_configured ? '已保存，留空不变' : '未设置'}
            type="password"
            disabled={syncProvider === 'local'}
          />
        </label>
        <label>
          <span>Secret Key</span>
          <input
            value={syncSecretKey}
            onChange={(event) => setSyncSecretKey(event.target.value)}
            placeholder={syncSettings?.secret_key_configured ? '已保存，留空不变' : '未设置'}
            type="password"
            disabled={syncProvider === 'local'}
          />
        </label>
      </div>
      <div className="settings-actions">
        <label className="settings-check">
          <input type="checkbox" checked={clearSyncSecret} onChange={(event) => setClearSyncSecret(event.target.checked)} />
          清除同步密钥
        </label>
        <span className={`key-status ${syncSettings?.secret_key_configured ? 'configured' : ''}`}>
          {syncSettings?.secret_key_configured ? '同步密钥已加密保存' : '未设置同步密钥'}
        </span>
        <button className="secondary" onClick={testSync} disabled={testingSync}>
          {testingSync ? '测试中' : '测试同步'}
        </button>
        <button className="secondary" onClick={testSyncLive} disabled={testingSyncLive}>
          {testingSyncLive ? '联通中' : '真实联通'}
        </button>
        <button onClick={saveSync} disabled={savingSync}>
          {savingSync ? '保存中' : '保存同步'}
        </button>
      </div>
      {syncTestResult && (
        <div className={`connection-result ${syncTestResult.ok ? 'ok' : 'fail'}`}>
          <div className="connection-status">
            {syncTestResult.ok ? '同步配置可用' : `同步配置失败：${syncStatusLabel(syncTestResult.status)}`}
          </div>
          {syncTestResult.target_dir && <div className="connection-url">{syncTestResult.target_dir}</div>}
          {syncTestResult.missing_fields.length > 0 && (
            <div className="connection-detail">缺少字段：{syncTestResult.missing_fields.join(', ')}</div>
          )}
          {syncTestResult.detail && <div className="connection-detail">{syncTestResult.detail}</div>}
        </div>
      )}
    </div>
  )
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function connectionStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    missing_base_url: '缺少 Base URL',
    missing_api_key: '缺少 API Key',
    http_error: '服务返回错误',
    network_error: '网络不可达',
    request_failed: '测试请求失败',
  }
  return labels[status] ?? status
}

function modelStatusLabel(status: ApiConnectionTestResult['model_status']): string {
  const labels: Record<ApiConnectionTestResult['model_status'], string> = {
    found: '已找到',
    not_found: '未找到',
    unknown: '未确认',
    not_checked: '未检查',
  }
  return labels[status]
}

function syncStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    missing_target_dir: '缺少同步目录',
    target_not_directory: '目标不是目录',
    target_unwritable: '目录不可写',
    missing_required_fields: '缺少必填字段',
    configuration_valid: '配置有效',
    live_ready: '真实联通成功',
    live_check_failed: '真实联通失败',
    unsupported_provider: '不支持的 provider',
    request_failed: '测试请求失败',
  }
  return labels[status] ?? status
}
