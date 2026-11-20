# 项目规则

## 沟通

- 所有回复和 commit message 用中文。

## 改动约束

- 每次改动前，先说明打算做什么，等确认后再动。
- 不确定技术选型时，给出 2-3 个方案让用户选。
- 不要一次改超过 3 个文件。
- 不要删除用户手动添加的中文文档（如 .md 文件）。

## 测试

- agent-service 的测试：在 agent-service 目录下运行 `python -m pytest tests/ -v`。
- 改动后必须跑测试，通过才允许提交。

## 版本迭代

- 不要直接在 main 上做大改动，先开分支。
- 每完成一个功能，写一条 commit message 说明改了什么。

## 项目结构

- `agent-service/`：Python 后端 agent 服务
- `backend/`：后端 API
- `frontend/`：前端
- `start-all.bat`：一键启动脚本
- `架构方案.md`、`README.md`：项目文档
