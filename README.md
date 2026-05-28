# 每日推荐算法论文速递

自动从 arXiv 拉取推荐系统方向论文，用 Claude AI 生成中文摘要，每日 09:00（北京时间）更新。

网站：https://yxx6.github.io

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 设置 API Key

```bash
export ANTHROPIC_API_KEY="sk-ant-xxxx"
```

### 3. 手动生成今天的日报

```bash
python fetch_papers.py
```

生成指定日期的日报：

```bash
python fetch_papers.py --date 2026-05-26
```

### 4. 本地预览网站（需要安装 Jekyll）

```bash
gem install jekyll bundler
jekyll serve
# 访问 http://localhost:4000
```

## 配置

所有参数在 [config.py](config.py) 中，包括：

| 参数 | 说明 |
|------|------|
| `SEARCH_TOPICS` | arXiv 检索关键词列表 |
| `MAX_PAPERS` | 每日最多拉取论文数 |
| `DAYS_BACK` | 只看最近 N 天的论文 |
| `CLAUDE_MODEL` | 使用的 Claude 模型（影响费用和质量） |

## 部署到 GitHub Pages

1. 在 GitHub 创建仓库 `yxx6.github.io`
2. 推送本项目代码
3. 在仓库 Settings → Secrets → Actions 中添加 `ANTHROPIC_API_KEY`
4. 在 Settings → Pages 中将 Source 设为 `gh-pages` 分支
5. GitHub Actions 会在每天 09:00（北京时间）自动运行

也可以在 Actions 页面手动触发 `Daily Paper Fetch` 工作流。
