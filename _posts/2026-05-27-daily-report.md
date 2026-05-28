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
topics:
  - "cs.IR"
---

## 今日概述

推荐系统正从“预测下一次点击”转向更本质的问题：如何评估和优化模型在开放世界中的长期表现。两篇工作共同触及当前范式的裂缝——其一是训练目标短视，仅盯着即时反馈，忽略了对远期兴趣的探索与不确定性校准；其二是生成式推荐大热之下，语义ID的评测方式本身可能并不可靠，热门tokenizer的比较结论需要被重新审视。

工业界最值得关注的是**远期兴趣建模与不确定性引导**，以及**生成式推荐的评测体系反思**。前者直接关系到用户长期留存和跨会话体验，若能落地，将帮助模型在短期转化之外学会“放

## 论文列表（共 2 篇）

### 1. Looking Farther with Confidence: Uncertainty-Guided Future Learning for Sequential Recommendation

<div class="paper-card">
<div class="paper-authors">Ziqiang Cui、Xing Tang、Peiyang Liu 等7人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2605.28493v1" target="_blank">arXiv:2605.28493v1</a> · 2026-05-27</div>
</div>

**论文定位**  
该论文面向**序列推荐（Sequential Recommendation）**场景，核心痛点是**训练信号稀疏、模型只看单步 immediate next item 导致“模型短视”**——无法捕捉长期兴趣演化，且容易受短期噪声干扰。与已有利用未来交互的工作（如 DSSRec、FENRec）相比，**核心差异**在于：UFRec 不再对所有样本均匀施加未来监督，而是基于模型对主任务（下一项预测）的**不确定度（Uncertainty）动态调整未来监督的强度**——模型对当前状态越有信心，才越多地“看向更远的未来”；当模型本身对下一刻都预测不准时，则弱化未来信号，防止不可靠信息损伤主任务表征学习。

**核心架构**  
整体是一个**仅在训练期生效的辅助学习框架**，可插拔于主流序列推荐 backbone（论文以 SASRec 的 Transformer 架构为代表）。  
**数据流**：输入是用户历史交互子序列 \( \mathcal{S}_{1:t}^u \)，经 item embedding 与 position embedding 相加后，送入 \( L \) 层 Transformer，取最后位置输出作为用户当前状态表示 \( \mathbf{h} \)。主任务用 \( \mathbf{h} \) 直接做 softmax 预测下一项 \( v_{t+1}^u \)，产生交叉熵损失 \( \mathcal{L}_M \)。  
在此基础上，**两条纯训练分支**：  
1. **并行多步投影**：从 \( \mathbf{h} \) 通过 \( K-1 \) 个轻量线性投影头 \( \phi_k(\cdot) \) 并行映射出 \( \mathbf{h}^{(k)} \)，预测 \( t+k \) 时刻的未来交互项。  
2. **未来轨迹池化**：将真实未来序列 \( [v_{t+1},…,v_{t+K}] \) 通过池化得到全局未来表征 \( \mathbf{z} \)，再将 \( \mathbf{h} \) 通过另一个投影头映射为 \( \mathbf{h}^z \)，进行对比学习，使当前表征与自己的未来 horizon 一致，而与其它用户的未来拉开距离。最终损失为 \( \mathcal{L} = \mathcal{L}_M + \omega \cdot \mathcal{L}_{FS} + \lambda \cdot \mathcal{L}_{FC} \)。推理时丢弃所有辅助模块，**无额外计算开销**。

**关键机制拆解**  
1. **不确定性引导的未来监督权重 \( \omega \)**  
   对未来 \( k \) 步预测损失直接加权求和会导致：模型在不确定状态下被迫学习远距离 item，引入噪声。UFRec 使用主任务预测分布 \( \hat{\mathbf{y}} \) 的**香农熵 \( \mathcal{H}(\hat{\mathbf{y}}) \)** 量化不确定度，再通过指数衰减函数 \( \omega = \exp(-\mathcal{H}/\tau) \) 映射到 (0,1] 作为未来监督损失的乘性权重。  
   **有效原因**：当模型对 \( v_{t+1} \) 的预测已经很确信（低熵），说明对用户当前偏好有较好把握，此时让模型多看几步未来，可以强化长期偏好模式；反之高熵时主任务本身不可靠，未来信号反而会误导模型，衰减其权重相当于自适应地做了“难例挖掘”的反向操作。**代价**：需要计算全局 item 分布熵，在 item 数量极大时计算量较大，但因其只在训练期执行，且与多步投影共享同一个 softmax 计算图，工程上可接受。

2. **未来感知对比学习（Future-Aware Contrastive Learning）**  
   与逐点预测未来 item 不同，该模块将未来 \( K \) 步视为一个整体序列，通过池化（如 mean pooling）得到一个“未来 horizon”表示 \( \mathbf{z} \)，并将其作为正样本，与当前状态投影 \( \mathbf{h}^z \) 拉近，其它用户的未来 horizon 作为负样本推开。**设计价值**：直接预测未来每一步容易落入局部细节，而对比整体未来趋势可以捕捉“偏好方向”的结构性信息，且对偶然点击等噪声更鲁棒；训练时此模块也共享底层表示，推理时同样不需要。

**实验结果**  
论文在 **四个真实世界基准数据集**上评估（具体名称未在提供文本中列出，常见设定多为 Amazon Beauty/Sports/Toys 及 Yelp），对比了包括 SASRec、BERT4Rec、S\(^3\)-Rec、CL4SRec、DuoRec、FENRec 等 SOTA 序列推荐方法。**核心指标**（HR@k, NDCG@k）有显著提升；消融实验证明不确定度调制和对比模块均有正向贡献；框架对不同 backbone（SASRec、BERT4Rec）都有效；对短序列用户的提升相对更明显。**论文未附具体数值表格**，只给出了定性结论和消融/超参数分析的趋势描述。

**工程挑战与落地建议**  
- **训练开销**：需额外计算多步未来预测与对比损失，且熵计算依赖全量 item 分布，大物品库下 softmax 是瓶颈；可采用采样 softmax 或分塔设计降低复杂度。  
- **线上延迟**：推理完全走原 backbone，无任何辅助结构，延迟无增加，这是工业落地的重要加分项。  
- **冷启动**：方法利用用户已有序列中的未来交互，对交互极少的全新用户不直接适用，但对新 item 可能受益于未来信号增强整体表示质量。  
- **长序列与效率**：多步预测的步数 \( K \) 需权衡；过大会引入噪声，且未来 item 可能超出序列实际长度，需做 padding/截断，实现上需要处理变长问题。  
- **落地最有价值的建议**：工业界可以在**已经上线的序列模型训练流程**中，

### 2. How Reliable Are Semantic-ID Tokenizer Comparisons in Generative Recommendation?

<div class="paper-card">
<div class="paper-authors">Qian Zhang、Lech Szymanski、Haibo Zhang 等4人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2605.25330v1" target="_blank">arXiv:2605.25330v1</a> · 2026-05-25</div>
</div>

**论文定位**  
这篇论文聚焦 Semantic‑ID（SID）生成式推荐中的 tokenizer 评测可靠性问题，属于序列建模与评估协议的范畴。已有工作默认用 SID‑level 的 Hit@K、NDCG@K 来比较不同 tokenizer，并隐含假设「生成的 SID 序列会唯一映射到一个物品」。作者指出这一假设在真实数据上不成立：因为量化压缩，多个语义相似但协同信号不同的物品常常共享同一个 SID 序列（SID collision），碰撞率最高可达 30.52%。因此 SID‑level 指标会系统性高估物品级别的推荐效果（Hit@10 膨胀可达 103.36%），而且碰撞率越高的 tokenizer 越容易被误判为更好。与已有方法的差异在于，**本文没有提出新 tokenizer，而是严格拆解了 SID collision 对评测的影响，并给出两样工具：碰撞修正的 item‑level 指标（CCE）和以最小代价消除碰撞的后处理方法（ZCR）**，让 tokenizer 的比较回归到忠于「推荐物品」这一目标。

**核心架构**  
数据流基于常规的 SID 生成式推荐 pipeline：  
1. **Item → SID 映射**：由给定 tokenizer（如 RQ‑VAE、RK‑Means 等）离线将每个物品映射到长度 L=4、码本大小 V=256 的固定长度离散序列，形成 item‑to‑SID 查找表。  
2. **生成模型训练与推理**：用户交互历史被转换为 SID 序列后，用一个自回归模型预测下一项对应的 SID 序列，推理时用 beam search 返回 top‑K 个 SID 序列。  
3. **碰撞感知的评测修正**：作者不改变训练和推理过程，只在评测阶段介入。将 beam search 产生的每个 SID 序列按其碰撞组（同一 SID 对应的物品集合）展开成物品列表，为组内每个物品分配 1/组大小 的分数，计算 ItemHit@K 和 ItemNDCG@K（CCE）。  
4. **零碰撞 SID 重分配（ZCR）**：为了进一步消除 tokenizer 自身的碰撞差异，ZCR 保持每个物品的前 L‑1 个 SID 码不变，仅在最后一层码本中用最小代价（基于残差到码向量的平方距离）为每个前缀组指派互不相同的最后一层码字，从而得到零碰撞的 SID 分配，用于重新训练生成模型并比较不同 tokenizer 在统一无碰撞条件下的表现。

**关键机制拆解**  
最值得关注的设计是 **Collision‑Corrected Evaluation（CCE）**。它彻底摒弃了将 SID 匹配等同于命中物品的做法。具体做法是：对于一次 beam search 结果，按顺序展开每个 SID 的碰撞组，得到一个物品排名。目标物品所在的碰撞组大小为 g，排名起始位置为 p，那么位于 top‑K 内的目标组物品个数 m = min(g, max(0, K − p + 1))，ItemHit@K = m/g，ItemNDCG@K 也对 m 个物品按标准折损求和再除以 g。这个设计的有效性在于：**当 SID 无法唯一区分物品时，分数自然降到 1/g，不会给 tokenizer “虚高”的奖励**，且不需要重新训练模型，只需保存 beam search 结果。代价是评测计算略为复杂，并且无法改变模型在训练阶段已经学到的碰撞 SID 作为监督信号这一事实。

另一个亮点是 **Zero‑Collision Reassignment（ZCR）的优化形式**。ZCR 限定只修改最后一层 SID 码，基于两个理由保证了可行性和最优性：一是固定前 L‑1 码使碰撞仅发生在前缀组内，各前缀组问题独立；二是实验中的最大前缀组大小远小于 V=256，满足所有物品都能在组内获得互不相同的最后一层码字的容量条件。对于每个前缀组，求解带约束的最小代价二分匹配（匈牙利算法），使得恰好有 ρ（需要变化的最小码字数）个物品改变码字，且全体物品码字互异。这一做法**以最小改动将任意 tokenizer 的 SID 转为零碰撞版本**，代价是必须知道 tokenizer 的残差和码本向量，且不支持改变前 L‑1 层的分配（否则会破坏前缀组分解并改变残差意义）。

**实验结果**  
论文在四个数据集（Scientific、Cell、Beauty、Yelp）上评测了五种代表性 tokenizer，包括 RK‑Means、RQ‑VAE、PPMI‑SVD 等。  
- SID collision 普遍存在：列出的 RK‑Means 和 RQ‑VAE 碰撞率分别为 8.52%~30.52% 和 8.52%~20.42%，最大碰撞组规模可达 65 个物品。  
- **指标膨胀量化（RQ1）**：SID‑level Hit@10 相对于 item‑level ItemHit@10 最高被高估 103.36%，且通货膨胀率随碰撞率上升。  
- **Tokenzier 排名翻转（RQ2）**：在原有 SID‑level 评测下占优的 tokenizer，当改用 item‑level 的 CCE 指标后，排名发生改变，某些高碰撞率 tokenizer 排名下移。  
- **ZCR 的有效性（RQ3）**：在零碰撞 SID 下重新训练生成模型后，item‑level 指标成为唯一公平项，且 ZCR 能以很小的重分配代价消除碰撞，案例显示某些碰撞组只需改变少数最后一层码字即可区分类似物品。  
- 进一步分析包含将协同信号融入 PPMI‑SVD 嵌入的协作融合实验，以及文本空间与协同空间碰撞组可视化，这些作为补充分析展示碰撞来源。

**工程挑战与落地建议**  
工业界落地需要注意以下几点：  
- **特征接入与计算开销**：ZCR 需要 tokenizer 产生的量化残差和码本向量，这在实际离线流程中是可得的（通过残差量化器），且匈牙利算法复杂度 O(|𝒫|² V) 在 N ≤ 5 万时微不足道，可以用 FAISS 批量算距离矩阵，不会成为瓶颈。  
- **线上延迟影响**：CCE 仅改变离线评测，生成模型在线服务完全不变；ZCR 只替换了物品到 SID 的映射表，线上推理时仍是标准自回归生成，没有额外延迟。  
- **冷启动与更新**：论文未专门讨论冷启动物品如何获得 SID。但 ZCR 的思路可以扩展：新物品入录后先通过 tokenizer 得到原始 SID，然后在其前缀组内用最小代价分配一个未被占用的最后一层码字，避免引入新碰撞。操作可批量定期执行。  
- **局限与边界**：ZCR 只能在最后一层码本容量足够的前提下使用；当某个前缀组物品数超过 V（如极端密集头部类目），该方法会失效，需考虑更多层改动或放弃最小代价约束。此外，ZCR 不改变 tokenizer 本身的语义压缩能力，仅是后处理，tokenizer 本身的设计缺陷（如将协同差异大的物品压入同一前缀）仍会影响最终效果。  
- **一句话建议**：从业者在对生成式推荐做 tokenizer 选型时，应当**用 ItemHit@K/ItemNDCG@K 作为主要指标，并至少在离线评估中对 SID 做一次碰撞率检查**；若想公平对比 tokenizer，可选 ZCR 构建零碰撞版本再训练和评测。

**一句话总结**  
揭示 SID 碰撞导致指标虚
