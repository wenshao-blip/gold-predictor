# API Key 获取指南

本系统需要 2 个必填 API Key + 1 个可选 Key。以下逐一说明获取方法。

---

## 1. Tavily API Key（必填）— 新闻搜索

Tavily 是专为 AI 设计的新闻/网页搜索 API，用于采集黄金相关要闻。

### 获取步骤

1. 打开 https://tavily.com
2. 点击右上角 **Sign Up**，用 Google 或邮箱注册
3. 登录后进入 Dashboard，复制 **API Key**
4. 免费额度：每月 1000 次搜索（本系统每天用 5 次，月用量约 150 次，免费额度足够）

### 配置

```bash
# GitHub Actions: Settings → Secrets and variables → Actions → New repository secret
Name:  TAVILY_API_KEY
Value: tvly-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

```bash
# 本地运行:
export TAVILY_API_KEY="tvly-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

---

## 2. LLM API Key（必填）— 模型推理

用于调用大语言模型进行预测推理。兼容 OpenAI API 格式的服务商均可。

### 方案 A：OpenAI（推荐，效果最好）

1. 打开 https://platform.openai.com
2. 注册并登录
3. 左侧菜单 → **API Keys** → **Create new secret key**
4. 复制 sk- 开头的 Key
5. 充值余额：https://platform.openai.com/settings/organization/billing（最低 $5 即可，每次推理约 $0.01-0.03）

```bash
# GitHub Secrets
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

### 方案 B：DeepSeek（性价比最高）

1. 打开 https://platform.deepseek.com
2. 注册并登录
3. 左侧 **API Keys** → **创建 API Key**
4. 复制 Key
5. 充值：支持微信/支付宝，最低 ¥1（每次推理约 ¥0.01）

```bash
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 方案 C：通义千问（阿里云）

1. 打开 https://dashscope.console.aliyun.com
2. 注册阿里云账号并开通 DashScope
3. 左侧 **API-KEY 管理** → **创建**
4. 复制 Key

```bash
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

### 方案 D：Claude（Anthropic）

1. 打开 https://console.anthropic.com
2. 注册并登录
3. **Settings** → **API Keys** → **Create Key**
4. 复制 Key

```bash
LLM_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_MODEL=claude-3-5-sonnet-20241022
```

> 注：Claude API 格式与 OpenAI 略有不同，如果选 Claude 需要微调 predict.py 的请求格式。

---

## 3. GitHub Personal Access Token（可选）— 面板刷新按钮

如果你想让面板的"立即刷新"按钮能触发 GitHub Actions 重新采集数据，需要一个 Token。

### 获取步骤

1. 打开 https://github.com/settings/tokens
2. 点击 **Generate new token (classic)**
3. 勾选权限：`repo`（完整仓库访问）和 `workflow`
4. 生成后复制 Token（只显示一次）

### 配置面板

编辑 `dashboard/dashboard.html`，找到 `GITHUB_CONFIG` 对象：

```javascript
const GITHUB_CONFIG = {
  owner: 'your-github-username',   // 你的 GitHub 用户名
  repo: 'gold-predictor',            // 仓库名
  workflowId: 'refresh.yml',
  token: 'ghp_xxxxxxxxxxxx'          // 你的 Token
};
```

> 安全提示：不要把 Token 提交到公开仓库。建议用 GitHub Pages 的 Jekyll 或其他方式注入。如果是私人仓库，可以直接写在代码里。

---

## 4. FRED API Key（可选）— 美联储经济数据

用于获取更详细的美国经济指标（PCE、CPI、PMI 等）。系统不依赖此项也能运行。

### 获取步骤

1. 打开 https://fredaccount.stlouisfed.org/apikeys
2. 注册账户
3. 点击 **Request API Key**
4. 填写用途说明，提交
5. 复制 32 位 API Key

---

## 快速配置清单

在 GitHub 仓库 **Settings → Secrets and variables → Actions** 中添加以下 Secrets：

| Secret Name | Value | 必填 |
|---|---|:---:|
| `TAVILY_API_KEY` | tvly-xxxx... | 是 |
| `LLM_API_KEY` | sk-xxxx... | 是 |
| `LLM_BASE_URL` | https://api.openai.com/v1 | 是 |
| `LLM_MODEL` | gpt-4o | 是 |

配好后，GitHub Actions 定时任务即可自动运行。

---

## 验证配置

配好 Key 后，可以在 GitHub 仓库的 **Actions** 标签页手动触发 **晨间流水线** workflow 测试：

1. 进入 Actions 页面
2. 左侧选择 **晨间流水线**
3. 右侧点击 **Run workflow**
4. 等待执行完成，查看日志确认无报错
5. 访问 GitHub Pages 面板确认数据已更新

如果报错，检查 Actions 日志中哪个步骤失败，通常是 API Key 未配或额度不足。
