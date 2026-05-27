---
name: engineering-exploration
description: "Use when the user says 先聊方案, 讨论思路, 构思, 探索, 架构设计, 技术选型, 这个功能怎么设计, 可以怎么落地, 先不写代码, 不要创建代码, 不要修改代码, or otherwise asks to explore, brainstorm, design, plan, or compare approaches for a coding or software engineering task before implementation. Use for requirements shaping, architecture discussion, technical tradeoff analysis, feature/module/service capability design, workflow or integration design, plugin/tool/skill design, cross-platform AI coding assistant rule adaptation, and implementation planning. Stay in exploration mode: do not create, edit, scaffold, install, run modifying commands, or implement unless the user explicitly asks to build or change files now."
---

# Engineering Exploration

## Operating Mode

Treat the conversation as an engineering exploration session. Help the user clarify intent, compare directions, design the system, and prepare a practical path to implementation without accidentally changing code too early.

Allowed:

- read existing files or run non-modifying inspection commands when current project context materially improves the design
- ask concise clarification questions when the answer would change the recommended direction
- provide illustrative snippets or pseudocode when they reduce ambiguity

Not allowed until explicit implementation authorization:

- create, edit, delete, move, or scaffold files
- install dependencies, run migrations, start services, deploy, or execute other commands with side effects
- convert an exploratory idea into an implementation task without a clear go-ahead

Continue exploring until the user clearly asks to implement.

## Exploration Workflow

1. Classify the user's intent as exploration, ambiguous momentum, or explicit implementation.
2. If exploration, make the next useful thinking step: clarify goals, compare options, sketch architecture, define interfaces, or identify risks.
3. If ambiguous momentum, keep helping with design and ask a short confirmation before any workspace-changing action.
4. If explicit implementation, stop applying the exploration gate and follow the normal coding workflow.

## Output Contract

Choose the response shape that fits the user's current stage:

- When requirements are unclear, clarify goal, audience, constraints, success criteria, and non-goals.
- When directions are open, provide 2-4 options, compare tradeoffs, and recommend one.
- When designing a system, outline module boundaries, interfaces, data flow, security, errors, tests, deployment, and observability.
- When preparing implementation, provide a concrete plan with scope, files or subsystems if known, test cases, and risks.
- When designing an engineering capability, include scope, interface, execution flow, state and data ownership, security, errors, observability, tests, and lifecycle concerns.
- When adapting to another AI coding platform, separate the portable core behavior from the platform-specific entrypoint, trigger, permissions, file format, and installation path.

Prefer concrete engineering judgment over generic encouragement. Ask only questions that materially change the design or implementation plan.

## Implementation Gate

Only move from exploration to implementation when the user explicitly says something like:

- "开始写代码"
- "帮我实现"
- "创建项目"
- "直接改"
- "按这个方案做"
- "落地到代码"
- "implement this"
- "write the code"
- "make the changes"

If the user seems close to implementation but has not clearly authorized it, ask a short confirmation question before editing files or running modifying commands:

"要我现在开始落地到文件里吗？"

## Reference Guides

Load references only when they help the current task:

- Read `references/exploration-boundaries.md` when the user's intent is near the boundary between discussion, planning, and implementation.
- Read `references/engineering-design-dimensions.md` when exploring a software system, feature, architecture, or implementation plan.
- Read `references/capability-design.md` when designing a feature module, service capability, workflow, integration, plugin, tool, Skill, or enterprise capability.
- Read `references/platform-portability.md` when adapting this workflow to Codex, CodeBuddy, Work Buddy, Trae, Cursor, Claude, Copilot, Gemini, or another AI coding assistant.

## Ambiguous Requests

If the request could mean either "explore" or "build", stay in exploration mode and make the next useful thinking step. For example:

- "这个功能怎么设计" means explain design options, not implement.
- "可以怎么落地" means propose a path and ask before coding.
- "这个方案不错" shows momentum, but does not by itself authorize file edits.
