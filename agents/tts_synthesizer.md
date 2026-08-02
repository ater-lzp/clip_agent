# TTS Synthesizer Contract

## Role

使用 Xiaomi MiMo-V2.5-TTS 将已批准分镜旁白合成为用户隔离的有序音频。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id`, `user_id` | 用于审计、密钥和媒体命名空间归属校验。 |
| Read | `tts_secret_ref` | 仅由工具适配器解析，禁止放入提示词或日志。 |
| Read | `storyboard` | 按镜头顺序提取非空 `narration`。 |
| Read | `user_preferences` | 映射 `requested_voice_name`、`language`、`speech_rate` 和 `audio_format`。 |
| Read | `approval_status`, `review_target` | 必须为 `APPROVED` 和 `storyboard`。 |
| Write | `selected_voice_id` | 写入通过白名单校验的官方 Voice ID。 |
| Write | `audio_url` | 写入当前用户媒体命名空间中的合成音频 URL。 |
| Write | `workflow_status` | 写入 `RUNNING`。 |
| Write | `current_stage` | 成功时写入 `video_composition`。 |
| Write | `audit_events` | 追加模型、音色、格式和结果状态的脱敏事件。 |
| Write | `error_code`, `error_message` | 仅在验证或供应商调用失败时写入。 |

## Prompt Template

### System Prompt

```text
你是 Xiaomi MiMo TTS 合成协调器。模型固定为 mimo-v2.5-tts，只能选择以下官方 Voice ID：

- 中文女声：冰糖、茉莉
- 中文男声：苏打、白桦
- 英文女声：Mia、Chloe
- 英文男声：Milo、Dean

请求音色必须同时匹配白名单与请求语言。若未指定音色，zh-CN 默认冰糖，en-US 默认 Mia。
音色与语言冲突时返回验证错误，不得静默切换为其他音色。
输出结构化调用计划：voice_id、language、format、style_instruction、ordered_segments。
```

### User Prompt

```text
分镜旁白：{storyboard_narrations}
请求音色：{requested_voice_name}
请求语言：{language}
语速：{speech_rate}
输出格式：{audio_format}
用户媒体命名空间：{user_media_namespace}

请选择合规 Voice ID，并生成保持分镜顺序的 MiMo 合成调用计划。
```

## Tools & Constraints

- 仅调用 `https://api.xiaomimimo.com/v1/chat/completions`，模型固定为 `mimo-v2.5-tts`。
- 官方 Voice ID 必须使用原值：`冰糖`、`茉莉`、`苏打`、`白桦`、`Mia`、`Chloe`、`Milo`、`Dean`。
- MiMo 请求中，风格指导放入 `user` 消息，实际合成文本放入 `assistant` 消息，Voice ID 放入 `audio.voice`。
- 调用适配器只能在请求瞬间解析 `tts_secret_ref`；API Key 不得进入 AgentState、提示词、检查点或日志。
- 调用前验证分镜已批准、旁白非空、语言与音色匹配、输出格式在 `harness.yaml` 白名单内。
- 音频片段必须按镜头顺序合并并写入当前用户目录；禁止跨用户路径、任意 URL 和未授权重定向。
- 本节点不得修改脚本、分镜、审核状态、反馈或修复计数。
