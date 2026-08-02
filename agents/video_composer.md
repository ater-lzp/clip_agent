# Video Composer Contract

## Role

将已批准分镜、合成音频和授权素材安全组合为当前用户可访问的最终短视频。

## State Input/Output

| Direction | AgentState field | Contract |
| --- | --- | --- |
| Read | `request_id`, `user_id` | 用于审计和输出目录归属校验。 |
| Read | `storyboard` | 提供镜头顺序、时长、画面和素材引用。 |
| Read | `audio_url` | 必须是当前用户命名空间内已验证的音频。 |
| Read | `authorized_asset_refs` | 所有素材必须属于该白名单。 |
| Read | `user_preferences` | 映射 `aspect_ratio` 和目标时长。 |
| Read | `approval_status`, `review_target` | 必须保持 `APPROVED` 和 `storyboard`。 |
| Write | `video_url` | 写入当前用户导出目录中的最终视频 URL。 |
| Write | `workflow_status` | 成功时写入 `COMPLETED`。 |
| Write | `current_stage` | 成功时写入 `completed`。 |
| Write | `audit_events` | 追加合成参数、素材数量和结果状态的脱敏事件。 |
| Write | `error_code`, `error_message` | 仅在输入、编码或产物验证失败时写入。 |

## Prompt Template

### System Prompt

```text
你是短视频合成规划器。根据已批准分镜、音频元数据和授权素材生成确定性的合成清单。

清单必须保持镜头顺序，包含每个镜头的素材引用、裁切策略、持续时间、旁白时间段和转场。
只能使用授权素材引用，不得生成 shell 字符串、任意文件路径、网络 URL 或发布操作。
输出结构化 JSON 合成清单，不输出可直接执行的命令行文本。
```

### User Prompt

```text
分镜：{storyboard}
音频元数据：{audio_metadata}
授权素材引用：{authorized_asset_refs}
目标画幅：{aspect_ratio}
目标时长（秒）：{target_duration_seconds}
输出命名空间：{user_export_namespace}

请生成可由视频工具适配器执行的结构化合成清单。
```

## Tools & Constraints

- 使用结构化清单校验器、受控 FFmpeg 适配器和用户隔离的媒体存储工具。
- FFmpeg 必须使用参数数组调用，禁止 shell 拼接、用户提供的过滤器表达式和任意输出路径。
- 执行前验证音频、素材和输出路径均属于当前 `user_id`，并拒绝符号链接或路径穿越。
- 校验镜头总时长、音频时长、画幅和编码结果；只有产物存在且可读取时才能写入 `video_url`。
- 本节点不得发布视频、修改审核结论、回写脚本或访问密钥。
