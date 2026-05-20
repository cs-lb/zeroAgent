---
name: fs-explorer
description: 在工作区里浏览/读取文件，回答与项目结构或文件内容相关的问题
when_to_use: 用户问 "项目里 X 在哪 / 这个文件写了什么 / 列一下目录" 等需要看文件系统的问题
---

# Skill: fs-explorer

## 工具

- `list_dir(path)`：列出目录条目（限制在 workspace 内）
- `fs_read(path, max_bytes?)`：读文件文本，**默认上限 64KB**
- `fs_write(path, content)`：写文件（**写操作会触发用户审批**，仅在用户明确要求改文件时使用）

## 步骤

1. 先 `list_dir(".")` 看一眼根目录，确认布局
2. 按文件名缩小范围；不要一次读太多
3. 大文件优先看头部（前 200 行）+ 关键 grep 结果，必要时再分段读
4. 报告时**给出相对 workspace 的路径**，不要拼绝对路径

## 限制

- 不要尝试访问 workspace 之外的路径（fs_read 会拒）
- 写文件前必须复述将要写入的完整内容并征得用户确认
