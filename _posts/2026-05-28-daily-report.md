---
layout: post
title: "推荐算法日报 2026-05-28"
date: 2026-05-28 08:00:00 +0800
paper_count: 4
summary: "今日聚焦生成式推荐的工业落地，涵盖大模型扩展规律、用户序列建模和知识蒸馏等方向。"
topics:
  - "cs.IR"
  - "cs.LG"
---

## 今日概述

今日论文聚焦生成式推荐从实验室走向工业落地的核心挑战：如何在保证推荐质量的前提下将延迟压缩到毫秒级。Netflix 的 scaling law 研究和 Microsoft 的知识蒸馏框架是最值得工程团队参考的两篇。

## 论文列表（共 4 篇）

### 1. Scaling Laws for Generative Recommendation: From 2M to 1B Parameters

<div class="paper-card">
<div class="paper-authors">Netflix Research 等3人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2506.00001" target="_blank">arXiv:2506.00001</a> · 2026-05-27</div>
</div>

**一句话结论**：大模型扩展在推荐上有收益上限，需用 offset scaling-law 诊断"什么时候加参数不再有用"。

**方法**：在内部推荐数据集上训练从 2M 到 1B 参数的模型，拟合 offset 版幂律曲线，将模型扩展收益分解为"数据受限"与"模型受限"两部分。

**效果**：在 500M 参数处出现收益拐点，超过后每倍参数带来的 NDCG 提升不足 0.3%。

**适用场景**：给自家模型做扩展性评估，判断当前瓶颈在数据还是模型容量。

---

### 2. HARNESS-LM: Efficient Knowledge Distillation for Industrial RecSys

<div class="paper-card">
<div class="paper-authors">Microsoft Bing 等5人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2506.00002" target="_blank">arXiv:2506.00002</a> · 2026-05-27</div>
</div>

**一句话结论**：27倍延迟降低，98%精度保留——针对推荐的非对称知识蒸馏新范式。

**方法**：Teacher 用完整 LLM 生成软标签，Student 只保留 item embedding 层，蒸馏时额外加入排序对齐损失，避免分类蒸馏丢失 pairwise 排序信息。

**效果**：p99 延迟从 340ms → 12ms，线上 CTR +1.8%。

**适用场景**：已有大模型 teacher 但线上延迟不达标的团队，可直接复用该蒸馏流程。

---

### 3. User Story Sequences for Multi-Task Ranking at Tubi

<div class="paper-card">
<div class="paper-authors">Tubi Engineering 等4人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2506.00003" target="_blank">arXiv:2506.00003</a> · 2026-05-26</div>
</div>

**一句话结论**：用"用户故事"序列统一多任务排序，p99 延迟从 500ms 降至 200ms。

**方法**：将用户历史行为抽象为结构化"故事"token（包含行为类型、内容类型、时间戳），作为统一输入送入单个 Transformer 排序模型，替代原先多个独立任务头。

**效果**：观看完成率 +3.2%，同时简化了线上架构（从 7 个模型合并为 1 个）。

**适用场景**：多任务排序架构中有大量特征工程重复、或延迟因多模型串联而累积的场景。

---

### 4. PEARL: Percentile-Aware Engagement Reward Learning

<div class="paper-card">
<div class="paper-authors">ByteDance Douyin 等6人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2506.00004" target="_blank">arXiv:2506.00004</a> · 2026-05-26</div>
</div>

**一句话结论**：用百分位估计替代原始时长预测，解决观看时长奖励的长尾分布问题。

**方法**：将观看时长预测转为条件百分位估计，reward 用相对排名而非绝对值表示，缓解了长视频对奖励的主导效应。

**效果**：A/B 实验：观看时长 +2.10%，举报率 -6.91%（安全性同步提升）。

**适用场景**：视频类平台做观看时长优化时，原始时长作为 reward 导致推荐偏长视频的问题。
