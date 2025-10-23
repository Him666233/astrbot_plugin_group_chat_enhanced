# AstrBot 群聊增强版插件 (astrbot_plugin_group_chat_enhanced)

> **二次创作版本** - 基于astrbot_plugin_group_chat 和 astrbot_plugin_reply_directly插件进行功能增强

一个**功能全面**的群聊交互插件，基于 astrbot_plugin_group_chat 和 astrbot_plugin_reply_directly 二次创作，融合了沉浸式对话和主动插话功能，并修复了一些astrbot_plugin_group_chat 和 astrbot_plugin_reply_directly插件的问题。

## 📋 项目信息

- **当前版本作者**: Him666233
- **当前项目地址**: https://github.com/Him666233/astrbot_plugin_group_chat_enhanced
- **astrbot_plugin_group_chat插件作者**: qa296
- **astrbot_plugin_group_chat插件项目地址**: https://github.com/qa296/astrbot_plugin_group_chat
- **astrbot_plugin_reply_directly插件作者**: qa296
- **astrbot_plugin_reply_directly插件项目地址**: https://github.com/qa296/astrbot_plugin_reply_directly
- **插件类型**: 二次创作版本（基于 astrbot_plugin_group_chat 和 astrbot_plugin_reply_directly 插件功能增强）

> 💡 **支持原作者**: 如果您觉得这个插件有用，请考虑支持原版插件的作者 qa296！

## 🌟 核心特性

### 🚀 先进的AI算法（来自原版 astrbot_plugin_group_chat 群聊插件）
- **多维度活跃度分析**：基于时间窗口、用户参与度、消息质量、话题持续性等多重因素
- **语义相关性检测**：采用结构化特征分析、上下文一致性、用户行为模式等智能方法
- **动态人格关键词**：从机器人人格系统中智能提取关键词，实现个性化@检测
- **历史数据驱动**：基于实际聊天记录进行学习和优化

### 🎯 智能回复决策系统
- **读空气功能**：使用LLM判断聊天氛围，智能决定是否回复
- **多因素意愿计算**：综合用户印象、群活跃度、疲劳度、连续对话等因素
- **心流算法**：能量系统管理回复节奏，动态调整阈值和冷却时间
- **自适应阈值**：根据历史表现动态调整决策参数
- **疲劳保护机制**：防止过度回复，保持自然交互节奏

### 💬 高级交互模式
- **专注聊天模式**：支持与特定用户的深度对话
- **观察模式**：在低活跃度群组中自动进入观察状态
- **连续对话奖励**：智能识别和奖励连续对话
- **消息质量评估**：基于长度、互动性、情感表达等维度评估消息价值

### 🔄 沉浸式对话功能（来自 astrbot_plugin_reply_directly 连续回复插件）
- **沉浸式对话**：机器人回答后，无需@机器人，用户可直接追问，机器人会基于完整上下文继续回复
- **主动插话功能**：机器人发言后，监听后续聊天内容，若LLM判断话题相关，则主动发表意见

### 🖼️ 图片处理功能（新增）
- **智能图片识别**：支持处理群聊消息中的图片内容
- **多模式处理**：提供direct（直接传递）、caption（文字描述）、ignore（忽略）三种处理模式
- **LLM视觉理解**：在direct模式下，直接将图片URL传递给LLM进行视觉理解
- **图片转文字**：在caption模式下，将图片转换为文字描述后再传递给LLM
- **无缝集成**：图片处理功能已集成到回复生成和"读空气"决策流程中

## 📦 安装与部署

### 快速安装
```bash
- 在astrbot插件市场搜索本插件，点击下载按钮，随后即可自动安装，

- 或者进入本项目地址: https://github.com/Him666233/astrbot_plugin_group_chat_enhanced
- 下载你想要的源码版本后，在Astrbot平台的根目录下的data/plugins下进行解压，随后重启Astrbot
```

### 原版astrbot_plugin_reply_directly插件安装（推荐支持原作者）
```bash
# 如果您想使用astrbot_plugin_reply_directly原版插件，请安装原版：
# 1. 克隆仓库
git clone https://github.com/qa296/astrbot_plugin_reply_directly.git

# 2. 放入插件目录
cp -r astrbot_plugin_reply_directly  YOUR_ASTRBOT_DIR/data/plugins/

# 3. 重启 AstrBot
./restart.sh   # 或你喜欢的启动方式

```

### 原版astrbot_plugin_group_chat插件安装（推荐支持原作者）
```bash
# 1. 克隆插件到AstrBot插件目录
cd AstrBot/data/plugins
git clone https://github.com/qa296/astrbot_plugin_group_chat.git

# 2. 安装依赖（如果有）
cd astrbot_plugin_group_chat
pip install -r requirements.txt

# 3. 重启AstrBot并在WebUI中启用插件

```

## ⚙️ 配置详解

### 🎛️ 核心配置
```json
{
  "enable_plugin": true,                    // 插件总开关
  "bot_qq_number": "123456789",           // 机器人QQ号（必填）
  "bot_name": "",                         // 机器人名字（选填）
  "enable_immersive_chat": true,           // 启用沉浸式对话功能
  "immersive_chat_timeout": 120,           // 沉浸式对话等待超时（秒）
  "enable_proactive_reply": true,          // 启用主动插话功能
  "proactive_reply_delay": 8,              // 主动插话延迟时间（秒）
  "list_mode": "blacklist",               // 名单模式：blacklist/whitelist
  "groups": [],                           // 群组名单列表
  "base_probability": 0.3,                // 基础回复概率 (0.0-1.0)
  "willingness_threshold": 0.5,            // 回复意愿阈值 (0.0-1.0)
  "max_consecutive_responses": 3,          // 最大连续回复次数
  "air_reading_enabled": true,             // 启用读空气功能
  "air_reading_no_reply_marker": "[DO_NOT_REPLY]", // 读空气不回复标记
  "focus_chat_enabled": true,              // 启用专注聊天
  "min_interest_score": 0.6,               // 最小兴趣度分数
  "focus_timeout_seconds": 300,            // 专注聊天超时时间（秒）
  "focus_max_responses": 10,               // 专注聊天最大回复次数
  "fatigue_enabled": true,                 // 启用疲劳系统
  "fatigue_threshold": 5,                  // 疲劳阈值
  "fatigue_decay_rate": 0.5,               // 疲劳度衰减率（每小时衰减的比例）
  "fatigue_reset_interval": 6,             // 疲劳度重置间隔（小时）
  "memory_enabled": false,                 // 启用记忆系统（需要memora_connect）
  "max_memories_recall": 10,               // 最大回忆记忆数量
  "impression_enabled": false,             // 启用印象系统（需要memora_connect）
  "observation_mode_threshold": 0.2,       // 观察模式阈值（群活跃度低于此值时进入观察）
  "heartbeat_threshold": 0.55,             // 主动心跳触发门槛（0-1，越低越容易触发）
  "at_boost_value": 0.5,                   // 被@时一次性增强幅度（0-1）
  "heartbeat_interval": 30,                // 主动心跳检查间隔（秒）
  "cooldown_seconds": 10,                  // 触发主动回复后的冷却时间（秒）
  "enable_detailed_logging": false,        // 启用详细日志输出
  "image_processing": {                    // 🖼️ 图片处理配置
    "enable_image_processing": false,       // 启用图片处理功能
    "image_mode": "ignore",                // 普通图片的处理模式：direct/caption/ignore
    "enable_at_image_caption": false,       // 启用@消息图片转文字功能
    "at_image_caption_provider_id": "",    // @消息图片转文字服务提供商ID
    "at_image_caption_prompt": "",         // @消息图片转文字提示词
    "image_caption_provider_id": "",       // 普通图片的转文字服务提供商ID
    "image_caption_prompt": "请直接简短描述这张图片", // 普通图片的转文字提示词
    "enable_detailed_logging": false        // 启用详细日志输出
  }
}
```

### 📋 配置项详细说明

#### 🔧 基础控制
- **enable_plugin**: 插件总开关，关闭后所有功能失效，建议在调试或临时禁用时使用
- **bot_qq_number**: 机器人QQ号（必填），只有当@消息中明确@此QQ号时，才会触发强制回复、@消息处理和沉浸式模式。此配置项必须填写才能正常工作
- **bot_name**: 机器人名字（选填），用于检测@符号后紧挨着机器人名字或隔一个空格的情况。当QQ平台@消息不包含机器人QQ号时，此配置可增强@消息检测能力。支持格式：@机器人名字 或 @ 机器人名字
- **enable_detailed_logging**: 启用详细日志输出，调试时开启可查看决策过程，正常使用时关闭减少日志量

#### 💬 对话功能
- **enable_immersive_chat**: 启用沉浸式对话，机器人回复后限时等待用户后续消息，让对话更连贯自然
- **immersive_chat_timeout**: 沉浸式对话等待超时（60-300秒），太短易中断对话，太长占用资源
- **enable_proactive_reply**: 启用主动插话，机器人发言后根据后续聊天内容判断是否主动插话
- **proactive_reply_delay**: 主动插话延迟（5-30秒），太短打断节奏，太长错过时机

#### 📊 回复控制
- **base_probability**: 基础回复概率（0.1-0.5），值越高机器人越活跃
- **willingness_threshold**: 回复意愿阈值（0-1），值越高回复越谨慎
- **max_consecutive_responses**: 最大连续回复次数（2-5次），防止刷屏
- **air_reading_enabled**: 启用读空气功能，分析对话氛围判断是否适合插话
- **air_reading_no_reply_marker**: 读空气不回复标记，LLM返回此内容时不回复

#### 🎯 专注聊天
- **focus_chat_enabled**: 启用专注聊天，与特定用户深入对话时优先回复
- **min_interest_score**: 最小兴趣度分数（0-1），值越高需要更强兴趣才进入专注模式
- **focus_timeout_seconds**: 专注聊天超时时间，避免长时间占用对话资源
- **focus_max_responses**: 专注聊天最大回复次数，达到限制后自动结束

#### 😴 疲劳系统
- **fatigue_enabled**: 启用疲劳系统，根据对话频率自动调整回复意愿
- **fatigue_threshold**: 疲劳阈值，短时间内回复次数达到此值进入疲劳状态
- **fatigue_decay_rate**: 疲劳度衰减率（0.3-0.7），值越高恢复越快
- **fatigue_reset_interval**: 疲劳度重置间隔（4-12小时），完全重置疲劳度

#### 🧠 记忆与印象
- **memory_enabled**: 启用记忆系统，需要安装astrbot_plugin_memora_connect插件
- **max_memories_recall**: 最大回忆记忆数量（5-20），值越大回忆内容越多但响应时间增加
- **impression_enabled**: 启用印象系统，需要安装astrbot_plugin_memora_connect插件

#### 📈 活跃度控制
- **observation_mode_threshold**: 观察模式阈值（0-1），群活跃度低于此值进入观察模式
- **heartbeat_threshold**: 主动心跳触发门槛（0.4-0.7），值越低越容易主动发言
- **at_boost_value**: 被@时增强幅度（0.3-0.8），值越高被@时回复意愿越强
- **heartbeat_interval**: 主动心跳检查间隔（20-60秒），值越大回复频率越低
- **cooldown_seconds**: 主动回复冷却时间（5-30秒），避免连续刷屏

#### 📋 群组管理
- **list_mode**: 名单模式，blacklist（黑名单）或 whitelist（白名单）
- **groups**: 群组名单列表，格式为字符串数组，如["123456789", "987654321"]

#### 🖼️ 图片处理配置
- **enable_image_processing**: 启用图片处理功能，关闭时所有图片相关功能禁用
- **image_mode**: 普通图片处理模式：direct（直接处理）、caption（转文字描述）、ignore（忽略）
- **enable_at_image_caption**: 启用@消息图片转文字功能，此功能优先于普通图片处理
- **at_image_caption_provider_id**: @消息图片转文字服务提供商ID，留空使用默认服务商
- **at_image_caption_prompt**: @消息图片转文字提示词，留空直接转图片不给提示词
- **image_caption_provider_id**: 普通图片转文字服务提供商ID，需要支持图片识别功能
- **image_caption_prompt**: 普通图片转文字提示词，可自定义描述格式和内容
- **enable_detailed_logging**: 启用详细日志输出，调试图片功能时开启

## 🚀 工作原理

### 📊 活跃度分析算法
```
活跃度分数 = 时间窗口权重 × 消息密度 + 用户参与度 × 多样性 + 消息质量 × 价值 + 话题持续性 × 连贯性
```

- **时间窗口分析**：1分钟(40%) + 5分钟(30%) + 30分钟(20%) + 1小时(10%)
- **用户参与度**：活跃用户数 / 10（标准化到0-1）
- **消息质量评估**：基于长度、标点密度、互动性、情感表达
- **话题持续性**：分析用户交互模式和对话连贯性

### 🎯 语义相关性检测
采用五维智能分析：

1. **结构化特征分析**：长度、标点密度、@提及、疑问句特征
2. **上下文一致性分析**：用户交互模式、消息长度模式、时间间隔
3. **用户行为模式分析**：互动频率、活跃度、响应模式
4. **对话流分析**：对话节奏、话题连贯性
5. **时间相关性分析**：消息间隔模式分析

### 🔄 沉浸式对话流程
```
机器人回复 → 启动沉浸式对话状态 → 监听用户后续消息 → LLM判断是否继续对话 → 保持对话连贯性
```

### 💬 主动插话流程
```
机器人发言 → 启动主动插话监听 → 收集后续聊天内容 → LLM判断话题相关性 → 主动发表意见
```

## 📁 架构说明

### 🏗️ 核心组件
```
astrbot_plugin_group_chat_enhanced/
├── main.py                    # 🎯 主插件入口（融合功能）
├── _conf_schema.json         # ⚙️ 配置模式定义
├── metadata.yaml             # 📋 插件元数据
├── src/
│   ├── __init__.py           # 📁 包初始化
│   ├── active_chat_manager.py    # 🎮 主动聊天管理器
│   ├── context_analyzer.py       # 🔍 上下文分析器
│   ├── fatigue_system.py         # 😴 疲劳系统
│   ├── focus_chat_manager.py     # 🎯 专注聊天管理器
│   ├── frequency_control.py      # 📊 频率控制（历史数据驱动）
│   ├── group_list_manager.py     # 📋 群组名单管理器
│   ├── impression_manager.py     # 👤 印象管理器
│   ├── interaction_manager.py    # 💬 交互模式管理器
│   ├── memory_integration.py     # 🧠 记忆集成
│   ├── response_engine.py        # 💬 回复引擎
│   ├── state_manager.py          # 💾 状态管理器
│   ├── utils.py                  # 🛠️ 工具函数
│   └── willingness_calculator.py # 🧮 意愿计算器（多维度分析+心流算法）
│   └── image_processor.py         # 🖼️ 图片处理器（新增）
└── README.md                 # 📖 本文档
```

### 🔄 数据流
```
消息接收 → 上下文分析 → 活跃度计算 → 意愿评估 → 相关性检测 → 回复决策 → 状态更新
```

## 🎮 使用示例

### 基础使用
1. **自动激活**：插件启动后自动开始监控活跃群组
2. **智能回复**：根据计算的意愿值自动决定是否回复
3. **疲劳保护**：自动控制回复频率避免过度打扰

### 沉浸式对话示例
```
用户A：帮我规划一下今天的学习计划
机器人：好的，建议上午复习数学，下午学习编程
用户A：下午学Python具体学什么内容？
机器人：可以从基础语法开始，然后学习函数和面向对象编程
（无需@机器人，对话自然继续）
```

### 主动插话示例
```
机器人：今天天气真不错
用户B：要不要去打球？
用户C：去哪儿打比较好？
机器人：我知道新开的球场，需要地址吗？
（机器人主动参与话题讨论）
```

### 图片处理示例
```
用户A：[发送一张风景图片]
机器人：这张风景图片真美！我看到有蓝天白云和绿色的山脉，很适合户外活动。
（在direct模式下，机器人直接理解图片内容）

用户B：[发送一张美食图片]
机器人：看起来是一道美味的意大利面，配料很丰富！
（在caption模式下，机器人基于图片描述进行回复）
```

### 状态查询命令
- **群聊主动状态**：在群聊中发送此命令可查看当前群的详细状态信息

## 📈 版本历史

### v2.0.3 (增强版) - 2025年10月23日
- 🔧 **改进整体代码结构强度** -改进整体代码结构样式，使代码结构更加规范，可读性增强，可扩展性提高
- 🤖 **新增机器人名字检测功能** - 添加机器人名字配置选项，支持检测@符号后紧挨着机器人名字或隔一个空格的情况，增强@消息检测能力
- 🛠️ **改进@消息检测逻辑** - 在原有QQ号检测基础上增加机器人名字检测，解决qq平台有时@消息不包含机器人QQ号的问题
- 📝 **完善上下文系统** - 确保每次对话都能联系联系上下文发给AI进行对话，并且保存至官方文件中，就算官方文件失败，有备用保存方式至临时文件中，实现双重保障
- ✨ **优化智能判断** - 优化AI主动对话智能判断，使主动插话对话能够更好的插入对话主题中

### v2.0.2 (增强版) - 2025年10月23日
- 🛠️ **修复强制回复总是被调用的问题** - 添加机器人QQ号配置选项，只当真正@机器人的时候才会触发强制回复

### v2.0.1 (增强版) - 2025年10月22日
- 🖼️ **修复@消息图片识别逻辑** - 确保所有包含图片的@消息都能正确转入图片转文字处理
- 🔧 **修复@消息图片检测逻辑** - 确保只有在@消息中确实包含图片时才进行图片转文字处理
- ✅ **双重图片检查机制** - 先检查文本中的图片标识，再检查消息事件中的实际图片
- 💻 **重构整个代码结构** - 减少屎山代码，代码更规范
- 📝 **优化日志输出** - 更清晰地记录图片检测和处理过程
- 🛠️ **增强错误处理** - 改进异常捕获和错误信息记录

### v2.0.0 (增强版) - 2025年10月21日
- ✨ **二次创作版本** - 基于原版astrbot_plugin_group_chat 和 astrbot_plugin_reply_directly群聊插件功能增强
- 🖼️ 新增图片处理功能，支持三种模式：direct/caption/ignore
- 🤖 集成LLM视觉理解能力，智能识别图片内容
- 📝 支持图片转文字描述，增强对话上下文理解
- 🔄 无缝集成到回复生成和"读空气"决策流程


## 📞 技术支持

- **个人BiliBili视频平台主页(可私信)**: https://space.bilibili.com/355329359?spm_id_from=333.1007.0.0
- **AstrBot社区**: https://github.com/AstrBotDevs/AstrBot

---

**⭐ 如果这个插件对你有帮助，请给项目一个Star！**

---

## 🔄 功能对比

| 功能特性 | 原版astrbot_plugin_group_chat插件 | 原版astrbot_plugin_reply_directly插件 | 增强版插件 |
|---------|-------------|-------------|-----------|
| 智能活跃度分析 | ✅ | ❌ | ✅ |
| 多维度意愿计算 | ✅ | ❌ | ✅ |
| 心流算法 | ✅ | ❌ | ✅ |
| 读空气功能 | ✅ | ❌ | ✅ |
| 专注聊天模式 | ✅ | ❌ | ✅ |
| 沉浸式对话 | ❌ | ✅ | ✅ |
| 主动插话 | ❌ | ✅ | ✅ |
| 状态查询命令 | ✅ | ❌ | ✅ |
| 疲劳保护系统 | ✅ | ❌ | ✅ |
| **图片处理功能** | ❌ | ❌ | ✅ |

增强版插件**完整保留**了原版astrbot_plugin_group_chat插件的所有智能算法，同时**新增**了astrbot_plugin_reply_directly插件的沉浸式对话和主动插话功能，提供最全面的群聊交互体验。