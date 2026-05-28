# ============================================================
# config.py — 所有可调参数集中在这里
# 你只需要改这个文件，不用动其他代码
# ============================================================

# -------- arXiv 检索设置 --------

# 主题关键词（会组合成 arXiv 查询）
# 格式：每行一个关键词或短语，支持 AND/OR
SEARCH_TOPICS = [
    "generative recommendation",
    "large language model recommendation",
    "sequential recommendation",
    "retrieval augmented generation recommendation",
]

# 每次最多拉取多少篇论文（建议 10-30，太多 API 费用高）
MAX_PAPERS = 20

# 只看最近几天的论文（0 = 不限制日期）
DAYS_BACK = 2

# arXiv 分类过滤（留空则不过滤）
# 常用：cs.IR (信息检索), cs.LG (机器学习), cs.AI
ARXIV_CATEGORIES = ["cs.IR", "cs.LG"]

# -------- DeepSeek API 设置 --------

# 模型选择
# 推荐选项：
#   "deepseek-v4-pro"    DeepSeek V4 Pro，质量最好，推荐
#   "deepseek-v4-flash"  DeepSeek V4 Flash，速度更快，费用更低
AI_MODEL = "deepseek-v4-pro"

# 摘要语言
SUMMARY_LANGUAGE = "中文"

# 每篇论文摘要的字数限制（影响 API 费用）
SUMMARY_MAX_TOKENS = 800

# -------- 文章生成设置 --------

# 生成的文章标题模板（{date} 会被替换为日期）
POST_TITLE_TEMPLATE = "推荐算法日报 {date}"

# 文章中每个"主题块"至少要有几篇论文才单独成节
# 低于此数量的主题会合并到"其他"
MIN_PAPERS_PER_SECTION = 2

# -------- 输出设置 --------

# Jekyll _posts 目录路径（相对于本脚本）
POSTS_DIR = "_posts"
