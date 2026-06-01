---
layout: single
title: "推荐算法日报 2026-05-27"
date: 2026-05-27 08:00:00 +0800
permalink: /daily/2026-05-27/
paper_count: 2
share: false
related: false
read_time: false
comments: false
excerpt: "今天聚焦 future supervision 与 Semantic ID 评估纠偏，重点看训练信号和离线指标如何影响推荐系统结论。"
---

## 今日概览

今天这组论文都在修推荐系统里两个容易被忽视的基础问题。一类是在训练时到底要不要强行看更远的未来，另一类是在生成式推荐里我们到底有没有用对评估尺子。前者对应 UFRec，核心是把 future supervision 建立在模型自己的置信度之上；后者对应 Semantic ID tokenizer 的评估纠偏，提醒我们很多看起来更好的 SID 方案，可能只是被碰撞和错误指标虚高了。

从工程价值看，这两篇论文都不是单纯追求更复杂的模型，而是在降低错误决策的概率。UFRec 更像训练范式升级，适合已经在用 SASRec、BERT4Rec 这类序列模型的团队离线增强；而 SID 评估纠偏那篇论文更像先把尺子校准，否则 tokenizer、生成模型乃至线上实验结论都可能被带偏。

## 论文列表（共 2 篇）

### 1. Looking Farther with Confidence: Uncertainty-Guided Future Learning for Sequential Recommendation

- 作者：Ziqiang Cui, Xing Tang, Peiyang Liu 等 7 人
- arXiv：[2605.28493v1](https://arxiv.org/abs/2605.28493v1)
- 发布时间：2026-05-27

**论文定位**

这篇论文关注的是 sequential recommendation 里监督太短视的问题。很多方法只优化 next-item prediction，因此模型更容易学到局部点击转移，而不容易学到更长期的兴趣演化。已有工作虽然尝试加入 future interactions，但往往默认所有样本都应该等强度地看向更远未来，这在用户状态本身就不清晰时很容易引入噪声。UFRec 的新意在于让模型先判断自己对当前预测是否有把握，再决定要不要加强 future supervision。

**核心方法**

UFRec 建立在标准序列推荐 backbone 之上，但在训练阶段额外加入两类辅助信号：

- uncertainty-guided future supervision：如果模型对当前下一步预测更自信，就更积极地利用未来多步标签；如果当前预测本身就很不确定，就自动压低未来监督的权重。
- future-aware contrastive learning：不是只看单步未来，而是把整段未来轨迹压缩成更稳定的 horizon 表示，让当前状态和整体未来趋势对齐。

这两个分支都只在训练时使用，推理时保留原有 backbone，因此线上时延基本不增加。

**实验结果**

- 论文在 Amazon、Yelp 等多个真实数据集上验证。
- 对比对象覆盖 SASRec、BERT4Rec、CL4SRec、DuoRec、DSSRec、FENRec 等方法。
- 文中结论是：UFRec 在多个数据集上稳定优于已有 SOTA，并且 uncertainty modulation 与 future-aware contrastive learning 都带来独立增益。

**工程价值与风险**

它的优点是接入位置干净，额外成本主要发生在离线训练阶段，对线上推理链路影响很小。真正要注意的是适用边界：当用户序列很短、future horizon 太弱，或者负样本质量不够时，这类 future supervision 的收益会明显下降。如果团队本身已经有成熟的序列推荐训练框架，UFRec 值得先做离线对比实验。

**一句话总结**

UFRec 把是否看更远未来建立在模型置信度之上，比固定 future loss 更稳，也更接近工业系统可落地的训练增强思路。

### 2. How Reliable Are Semantic-ID Tokenizer Comparisons in Generative Recommendation?

- 作者：Qian Zhang, Lech Szymanski, Haibo Zhang 等
- arXiv：[2605.25330v1](https://arxiv.org/abs/2605.25330v1)
- 发布时间：2026-05-25

**论文定位**

这篇论文直指 generative recommendation 里一个很关键但经常被忽略的问题：Semantic ID tokenizer 的比较可能从一开始就不公平。很多评估默认一个 SID 序列唯一对应一个 item，但真实 tokenizer 往往存在 collision，也就是多个 item 被压到同一个 SID 上。这样一来，SID-level Hit@K 和 NDCG 看起来很好，并不代表 item-level 推荐真的更好。

**核心方法**

论文提出两条互补路线：

- CCE（Collision-Corrected Evaluation）：不改训练模型，只在评估阶段把 SID collision 展开，重新计算更接近 item-level 真值的指标。
- ZCR（Zero-Collision Reassignment）：在保留 tokenizer 层级结构的前提下，只对末级编码做最小代价重分配，构造 zero-collision SID，再重新训练生成模型。

它的重点不是发明新的召回或排序模型，而是先把 tokenizer 比较的标准校正回来。

**实验结果**

- 论文报告多个 SID tokenizer 都存在明显碰撞，最高 collision rate 可达 30.5%。
- 只看 SID-level 指标会出现非常夸张的虚高，文中报告 Hit@10 最高可被高估 103.36%。
- CCE 可以在不重训模型的情况下把评估拉回 item-level 真实表现，ZCR 则进一步提供零碰撞 tokenizer 作为更严格对照。

**工程价值与风险**

这篇论文最大的价值是提醒我们，在做 Semantic ID、tokenizer 或生成式推荐评估时，要先修尺子再修模型。如果离线指标本身有偏，后续的 tokenizer 选择、模型比较乃至线上实验节奏都会被误导。CCE 接入成本低，适合优先纳入现有评估平台；ZCR 更彻底，但要配合 tokenizer 重建和模型重训，落地成本会高一些。

**一句话总结**

在生成式推荐里，先把 SID 评估校正到 item-level，再谈 tokenizer 或模型优劣，否则很多结论都可能是被 collision 撑出来的。
