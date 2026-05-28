---
layout: single
title: "推荐算法日报 2026-05-28"
date: 2026-05-28 08:00:00 +0800
paper_count: 1
summary: "今日arXiv推荐系统方向仅有一篇论文，聚焦于序列推荐中的未来学习。核心趋势是对传统“基于过去预测未来”范式的改进，通过引入不确定性量化来提升模型对长期依赖的捕"
topics:
  - "cs.IR"
---

## 今日概述

今日arXiv推荐系统方向仅有一篇论文，聚焦于序列推荐中的未来学习。核心趋势是对传统“基于过去预测未来”范式的改进，通过引入不确定性量化来提升模型对长期依赖的捕捉能力。值得关注的方向主要包括：不确定性引导的序列建模，以及如何让模型在置信度评估下更稳健地预测用户长期兴趣偏好。

## 论文列表（共 1 篇）

### 1. Looking Farther with Confidence: Uncertainty-Guided Future Learning for Sequential Recommendation

<div class="paper-card">
<div class="paper-authors">Ziqiang Cui、Xing Tang、Peiyang Liu 等7人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2605.28493v1" target="_blank">arXiv:2605.28493v1</a> · 2026-05-27</div>
</div>

**一句话结论**：按模型信心自适应调整未来监督权重，提升序列推荐效果。

**方法**：提出UFRec框架，包含不确定引导未来监督模块（根据当前预测信心动态调节多步未来损失权重）和未来感知对比学习模块（将未来轨迹整体建模），仅在训练时使用。

**效果**：在四个公开数据集上显著超过当前最优方法。

**适用场景**：适用于数据稀疏的序列推荐任务，如电商、视频、音乐等用户行为序列建模场景。
