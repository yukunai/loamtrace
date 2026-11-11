const { app, BrowserWindow } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..')
const distIndex = path.join(frontendRoot, 'dist', 'index.html')
const artifactsRoot = path.resolve(frontendRoot, '..', 'artifacts', 'visual-qa')

const checks = []

app.whenReady().then(async () => {
  fs.mkdirSync(artifactsRoot, { recursive: true })
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: {
      contextIsolation: true,
    },
  })

  try {
    await win.loadFile(distIndex)
    await waitForSelector(win, '.app')
    await checkDesktop(win)
    await screenshot(win, 'desktop-main.png')

    await exerciseMainJourney(win)
    await screenshot(win, 'desktop-journey.png')

    await win.webContents.executeJavaScript(`document.querySelector('.settings-entry')?.click()`)
    await waitForSelector(win, '.settings-modal')
    await checkSettingsModal(win)
    await screenshot(win, 'desktop-settings.png')

    win.setContentSize(390, 760)
    await delay(250)
    await checkMobile(win)
    await screenshot(win, 'mobile-settings.png')

    const failed = checks.filter((check) => !check.ok)
    const report = {
      generated_at: new Date().toISOString(),
      screenshots: ['desktop-main.png', 'desktop-journey.png', 'desktop-settings.png', 'mobile-settings.png'],
      checks,
      status: failed.length ? 'failed' : 'passed',
    }
    fs.writeFileSync(path.join(artifactsRoot, 'report.json'), JSON.stringify(report, null, 2))
    if (failed.length) {
      console.error(`[visual-qa] failed: ${failed.map((check) => check.name).join(', ')}`)
      app.exit(1)
      return
    }
    console.log(`[visual-qa] passed; artifacts: ${artifactsRoot}`)
    app.exit(0)
  } catch (error) {
    console.error(`[visual-qa] ${error instanceof Error ? error.message : String(error)}`)
    app.exit(1)
  }
})

async function checkDesktop(win) {
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      appVisible: !!document.querySelector('.app'),
      settingsEntryVisible: !!document.querySelector('.settings-entry'),
      resizerCount: document.querySelectorAll('.resizer').length,
      importButtonVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('导入')),
      generateButtonVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('生成')),
      memoQueryInputVisible: !!document.querySelector('.memo-generate-bar input'),
      bodyTextLength: document.body.innerText.length,
    }))()
  `)
  record('app visible', result.appVisible)
  record('settings entry visible', result.settingsEntryVisible)
  record('three resizers visible', result.resizerCount === 3)
  record('import control visible', result.importButtonVisible)
  record('memo generate control visible', result.generateButtonVisible && result.memoQueryInputVisible)
  record('body has rendered text', result.bodyTextLength > 20)
}

async function exerciseMainJourney(win) {
  await waitForSelector(win, '.nav-item.doc')
  await win.webContents.executeJavaScript(`
    (() => {
      const firstDoc = document.querySelector('.nav-item.doc .doc-main')
      firstDoc?.click()
      const searchToggle = Array.from(document.querySelectorAll('button')).find((button) => button.textContent.includes('检索参数'))
      searchToggle?.click()
      const firstClaim = document.querySelector('.review-item')
      firstClaim?.click()
    })()
  `)
  await delay(250)
  await checkSearchOptions(win)
  await checkEvidencePanel(win)
  await checkNonPdfCitationTarget(win)
  await checkXlsxCitationTarget(win)
  await checkChartPanel(win)
  await checkAnalysisPanel(win)
  await checkAssetLibraryPanel(win)

  await win.webContents.executeJavaScript(`
    (() => {
      const scannedDoc = Array.from(document.querySelectorAll('.nav-item.doc')).find((item) => item.textContent.includes('scanned_appendix'))
      scannedDoc?.querySelector('.doc-main')?.click()
    })()
  `)
  await delay(250)
  await checkManualTextPanel(win)
}

async function checkNonPdfCitationTarget(win) {
  await win.webContents.executeJavaScript(`
    (() => {
      const riskClaim = Array.from(document.querySelectorAll('.review-item'))
        .find((item) => item.textContent.includes('single cloud provider'))
      riskClaim?.click()
      const citationButton = document.querySelector('.citation-quote')
      citationButton?.click()
    })()
  `)
  await delay(350)
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      docxSelected: document.body.innerText.includes('risk_memo.docx'),
      nonPdfViewVisible: !!document.querySelector('.nonpdf-view'),
      precisionVisible: !!document.querySelector('.nonpdf-precision'),
      contextVisible: !!document.querySelector('.nonpdf-context'),
      paragraphLocationVisible: !!document.querySelector('.nonpdf-loc')?.textContent.trim(),
    }))()
  `)
  record('non-pdf citation switches document', result.docxSelected)
  record('non-pdf citation view visible', result.nonPdfViewVisible)
  record('non-pdf target precision visible', result.precisionVisible)
  record('non-pdf paragraph context visible', result.contextVisible)
  record('non-pdf paragraph location visible', result.paragraphLocationVisible)
  await win.webContents.executeJavaScript(`
    (() => {
      const pdfDoc = Array.from(document.querySelectorAll('.nav-item.doc'))
        .find((item) => item.textContent.includes('company_overview'))
      pdfDoc?.querySelector('.doc-main')?.click()
    })()
  `)
  await delay(250)
}

async function checkXlsxCitationTarget(win) {
  await win.webContents.executeJavaScript(`
    (() => {
      const metricClaim = Array.from(document.querySelectorAll('.review-item'))
        .find((item) => item.textContent.includes('Revenue was 148 in 2025'))
      metricClaim?.click()
    })()
  `)
  await delay(250)
  await win.webContents.executeJavaScript(`
    (() => {
      const citationButton = Array.from(document.querySelectorAll('.citation-quote'))
        .find((button) => button.textContent.includes('B3: 148'))
      citationButton?.click()
    })()
  `)
  await delay(650)
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      xlsxSelected: document.body.innerText.includes('operating_model.xlsx'),
      nonPdfViewVisible: !!document.querySelector('.nonpdf-view'),
      cellPrecisionVisible: document.querySelector('.nonpdf-precision')?.textContent.includes('单元格') ?? false,
      cellChipVisible: Array.from(document.querySelectorAll('.nonpdf-cell code')).some((node) => node.textContent.includes('B3')),
      cellValueVisible: Array.from(document.querySelectorAll('.nonpdf-cell span')).some((node) => node.textContent.includes('148')),
    }))()
  `)
  record('xlsx citation switches document', result.xlsxSelected)
  record('xlsx citation non-pdf view visible', result.nonPdfViewVisible)
  record('xlsx citation cell precision visible', result.cellPrecisionVisible)
  record('xlsx citation cell chip visible', result.cellChipVisible)
  record('xlsx citation cell value visible', result.cellValueVisible)
  await win.webContents.executeJavaScript(`
    (() => {
      const pdfDoc = Array.from(document.querySelectorAll('.nav-item.doc'))
        .find((item) => item.textContent.includes('company_overview'))
      pdfDoc?.querySelector('.doc-main')?.click()
    })()
  `)
  await delay(250)
}

async function checkSearchOptions(win) {
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      toggleVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('检索参数')),
      optionsPanelVisible: !!document.querySelector('.search-options-panel'),
      numericInputs: document.querySelectorAll('.search-options-panel input[type="number"]').length,
      saveDefaultVisible: Array.from(document.querySelectorAll('.search-options-panel button')).some((button) => button.textContent.includes('保存为项目默认')),
    }))()
  `)
  record('search parameters toggle visible', result.toggleVisible)
  record('search parameters panel opens', result.optionsPanelVisible)
  record('search parameters numeric controls visible', result.numericInputs >= 6)
  record('search save-default control visible', result.saveDefaultVisible)
}

async function checkEvidencePanel(win) {
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      reviewItemVisible: !!document.querySelector('.review-item'),
      claimTextVisible: !!document.querySelector('.claim-text'),
      citationCardVisible: !!document.querySelector('.citation-card'),
      supportJudgeButtonVisible: Array.from(document.querySelectorAll('.evidence-panel button')).some((button) => button.textContent.includes('支撑性判断')),
      supportSignalsVisible: !!document.querySelector('.support-signals'),
    }))()
  `)
  record('review item visible', result.reviewItemVisible)
  record('claim detail visible', result.claimTextVisible)
  record('citation card visible', result.citationCardVisible)
  record('support judge button visible', result.supportJudgeButtonVisible)
  record('support signal badges visible', result.supportSignalsVisible)
}

async function checkAnalysisPanel(win) {
  await win.webContents.executeJavaScript(`
    (() => {
      const riskButton = Array.from(document.querySelectorAll('.analysis-panel button')).find((button) => button.textContent.includes('扫描风险'))
      riskButton?.click()
    })()
  `)
  await delay(300)
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      panelVisible: !!document.querySelector('.analysis-panel'),
      tabsVisible: document.querySelectorAll('.analysis-tabs button').length >= 3,
      runAllVisible: Array.from(document.querySelectorAll('.analysis-panel button')).some((button) => button.textContent.includes('全部扫描')),
      findingVisible: !!document.querySelector('.analysis-finding'),
      severityVisible: !!document.querySelector('.finding-severity'),
      sourceVisible: !!document.querySelector('.finding-source'),
    }))()
  `)
  record('analysis panel visible', result.panelVisible)
  record('analysis tabs visible', result.tabsVisible)
  record('analysis run-all control visible', result.runAllVisible)
  record('analysis finding renders after scan', result.findingVisible)
  record('analysis severity badge visible', result.severityVisible)
  record('analysis source uri visible', result.sourceVisible)
}

async function checkChartPanel(win) {
  await win.webContents.executeJavaScript(`
    (() => {
      const generateButton = Array.from(document.querySelectorAll('.chart-panel button')).find((button) => button.textContent.includes('生成图表数据'))
      generateButton?.click()
    })()
  `)
  await delay(300)
  await win.webContents.executeJavaScript(`
    (() => {
      const deckButton = Array.from(document.querySelectorAll('.chart-panel button')).find((button) => button.textContent.includes('生成图表 Deck'))
      deckButton?.click()
    })()
  `)
  await delay(260)
  await win.webContents.executeJavaScript(`
    (() => {
      const exportButton = Array.from(document.querySelectorAll('.chart-panel button')).find((button) => button.textContent.includes('导出图表 PPTX'))
      exportButton?.click()
    })()
  `)
  await delay(260)
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      panelVisible: !!document.querySelector('.chart-panel'),
      tableSelectVisible: !!document.querySelector('.chart-select select'),
      previewVisible: !!document.querySelector('.chart-preview'),
      controlsVisible: document.querySelectorAll('.chart-controls input, .chart-controls select').length >= 3,
      resultVisible: !!document.querySelector('.chart-result'),
      verifiedVisible: !!document.querySelector('.chart-verified'),
      sourceCellsVisible: document.body.innerText.includes('source cells'),
      seriesVisible: !!document.querySelector('.chart-series'),
      deckControlsVisible: Array.from(document.querySelectorAll('.chart-panel button')).some((button) => button.textContent.includes('生成图表 Deck')),
      exportControlsVisible: Array.from(document.querySelectorAll('.chart-panel button')).some((button) => button.textContent.includes('导出图表 PPTX')),
      exportStatusVisible: document.querySelectorAll('.chart-export-path').length >= 2,
    }))()
  `)
  record('chart panel visible', result.panelVisible)
  record('chart table select visible', result.tableSelectVisible)
  record('chart table preview visible', result.previewVisible)
  record('chart controls visible', result.controlsVisible)
  record('chart result renders after generation', result.resultVisible)
  record('chart verified badge visible', result.verifiedVisible)
  record('chart source cells visible', result.sourceCellsVisible)
  record('chart series visible', result.seriesVisible)
  record('chart deck control visible', result.deckControlsVisible)
  record('chart pptx export control visible', result.exportControlsVisible)
  record('chart deck/export status visible', result.exportStatusVisible)
}

async function checkAssetLibraryPanel(win) {
  await win.webContents.executeJavaScript(`
    (() => {
      const registerButton = Array.from(document.querySelectorAll('.asset-panel button')).find((button) => button.textContent.includes('加入资产库'))
      registerButton?.click()
    })()
  `)
  await delay(300)
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      panelVisible: !!document.querySelector('.asset-panel'),
      registerVisible: Array.from(document.querySelectorAll('.asset-panel button')).some((button) => button.textContent.includes('加入资产库') || button.textContent.includes('加入中')),
      searchVisible: document.querySelectorAll('.asset-search input').length >= 2,
      assetItemVisible: !!document.querySelector('.asset-item'),
      importVisible: Array.from(document.querySelectorAll('.asset-item button')).some((button) => button.textContent.includes('导入')),
      tagEditVisible: Array.from(document.querySelectorAll('.asset-item button')).some((button) => button.textContent.includes('标签')),
      deleteVisible: Array.from(document.querySelectorAll('.asset-item button')).some((button) => button.textContent.includes('删除')),
      statusVisible: !!document.querySelector('.asset-status'),
    }))()
  `)
  record('asset library panel visible', result.panelVisible)
  record('asset register control visible', result.registerVisible)
  record('asset search controls visible', result.searchVisible)
  record('asset item visible', result.assetItemVisible)
  record('asset import control visible', result.importVisible)
  record('asset tag edit control visible', result.tagEditVisible)
  record('asset delete control visible', result.deleteVisible)
  record('asset register status visible', result.statusVisible)
}

async function checkManualTextPanel(win) {
  await win.webContents.executeJavaScript(`
    (() => {
      const toggle = document.querySelector('.manual-text-panel button')
      if (toggle && toggle.textContent.includes('补录')) toggle.click()
    })()
  `)
  await delay(150)
  const result = await win.webContents.executeJavaScript(`
    (() => {
      const textarea = document.querySelector('.manual-text-panel textarea')
      return {
        ocrRequiredVisible: !!document.querySelector('.ocr-required-banner') || document.body.innerText.includes('需OCR'),
        manualPanelVisible: !!document.querySelector('.manual-text-panel'),
        manualTextareaVisible: !!textarea,
        manualSaveVisible: Array.from(document.querySelectorAll('.manual-text-panel button')).some((button) => button.textContent.includes('保存并索引')),
      }
    })()
  `)
  record('ocr required state visible', result.ocrRequiredVisible)
  record('manual text panel visible', result.manualPanelVisible)
  record('manual text textarea visible after toggle', result.manualTextareaVisible)
  record('manual text save control visible', result.manualSaveVisible)
}

async function checkSettingsModal(win) {
  const result = await win.webContents.executeJavaScript(`
    (() => ({
      modalVisible: !!document.querySelector('.settings-modal'),
      providerVisible: !!document.querySelector('.settings-modal select'),
      testButtonVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('测试连接')),
      saveButtonVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('保存')),
      passwordInputVisible: !!document.querySelector('input[type="password"]'),
      syncSectionVisible: document.body.innerText.includes('同步配置'),
      syncTestVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('测试同步')),
      syncLiveTestVisible: Array.from(document.querySelectorAll('button')).some((button) => button.textContent.includes('真实联通')),
      syncProviderVisible: Array.from(document.querySelectorAll('.settings-grid select')).some((select) => select.textContent.includes('S3 / R2 compatible')),
    }))()
  `)
  record('settings modal visible', result.modalVisible)
  record('provider select visible', result.providerVisible)
  record('test connection button visible', result.testButtonVisible)
  record('save button visible', result.saveButtonVisible)
  record('api key password input visible', result.passwordInputVisible)
  record('sync settings section visible', result.syncSectionVisible)
  record('sync settings test button visible', result.syncTestVisible)
  record('sync live provider test button visible', result.syncLiveTestVisible)
  record('sync provider select visible', result.syncProviderVisible)
}

async function checkMobile(win) {
  const result = await win.webContents.executeJavaScript(`
    (() => {
      const modal = document.querySelector('.settings-modal')
      const modalRect = modal?.getBoundingClientRect()
      return {
        modalVisible: !!modal,
        modalFitsViewport: !!modalRect && modalRect.left >= 0 && modalRect.right <= window.innerWidth,
        bodyWidth: document.body.scrollWidth,
        viewportWidth: window.innerWidth,
      }
    })()
  `)
  record('mobile modal visible', result.modalVisible)
  record('mobile modal fits viewport', result.modalFitsViewport)
  record('mobile no severe horizontal overflow', result.bodyWidth <= result.viewportWidth + 24)
}

function record(name, ok) {
  checks.push({ name, ok: !!ok })
}

async function screenshot(win, filename) {
  const image = await win.webContents.capturePage()
  fs.writeFileSync(path.join(artifactsRoot, filename), image.toPNG())
}

async function waitForSelector(win, selector) {
  const started = Date.now()
  while (Date.now() - started < 10000) {
    const exists = await win.webContents.executeJavaScript(`!!document.querySelector(${JSON.stringify(selector)})`)
    if (exists) return
    await delay(100)
  }
  throw new Error(`selector not found: ${selector}`)
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
