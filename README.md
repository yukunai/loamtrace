# LoamTrace

本地证据检索、引用核对和研究报告工作台。

## 安装

需要 Python 3、Node.js 与 npm。

克隆仓库后，在项目根目录执行以下步骤。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn loamtrace.main:app --host 127.0.0.1 --port 8000
```

## 使用

另开终端进入 frontend，运行 npm ci 和 npm run dev。创建项目，导入源文档，核对引用和结论后导出报告或 PPTX。

## 检查

```sh
cd frontend && npm run build
```

## 说明

仓库包含源码与启动所需的示例。模型、平台或推送服务的凭据由使用者在本机配置。
