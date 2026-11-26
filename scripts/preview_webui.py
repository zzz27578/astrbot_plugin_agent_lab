#!/usr/bin/env python3
"""Zero-AstrBot interactive local preview server for Agent Lab v1.0.0 WebUI.

Usage:
    python scripts/preview_webui.py [--port 8799] [--host 127.0.0.1] [--reset]

Seeds rich Chinese sample data in `data_preview/` covering:
- 2 Bot identities (QQ私聊 & WebChat) with Persona info
- 3 Projects with SUMMARY.md and sharing settings
- 4 Tasks covering running/pending-approval+question, unknown-call reconciliation,
  completed archive, and readonly_research plan review
- 3 Profiles + 5 realistic plugin cards with Chinese labels and risk tags
- 3 Fernet-encrypted vault items (2 `secret` + 1 `personal` note; plaintext never exposed in API/state)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from agent_lab.engine import TaskEngine
from agent_lab.models import (
    ApprovalRequest,
    BudgetConfig,
    ContinuityConfig,
    ExecutionSettings,
    Profile,
    Project,
    QuestionItem,
    SummarySharingConfig,
    TaskMeta,
    TaskStep,
    UsageTotals,
    now_iso,
)
from agent_lab.permissions import call_signature
from agent_lab.store import AgentLabStore
from agent_lab.webui_api import StandaloneWebUIServer, WebUIController, _preview_plugins_catalog


def seed_preview_data(store: AgentLabStore, *, reset: bool = False) -> None:
    """Populate `data_preview/` with rich realistic sample data if fresh or `--reset`."""
    if reset and store.root.exists():
        shutil.rmtree(store.root, ignore_errors=True)
        store = AgentLabStore(store.root)

    if store.list_projects() and not reset:
        return

    umo_qq = "aiocqhttp:FriendMessage:demo_admin"
    umo_web = "webchat:FriendMessage:demo_reviewer"

    # 1. Preferences & 2 Bot Identities
    store.update_preferences(
        default_bot="aiocqhttp",
        webui_theme="classic",
        progress={
            "enabled": True,
            "min_interval_seconds": 30,
            umo_qq: {"enabled": True, "min_interval_seconds": 30},
            umo_web: {"enabled": True, "min_interval_seconds": 15},
        },
    )
    store._write_json(
        store.registry_dir / "identities.json",
        [
            {
                "umo": umo_qq,
                "platform_id": "aiocqhttp",
                "platform_name": "QQ私聊",
                "name": "Agent Lab · QQ私聊",
                "display_name": "Agent Lab · QQ私聊",
                "type": "aiocqhttp",
                "label": "Agent Lab · QQ私聊",
                "persona_id": "persona_demo_dev",
                "persona_name": "全栈开发助手 (演示人设)",
                "persona_preview": "严谨全栈工程师，擅长系统架构、安全防护与自动化回归测试。",
            },
            {
                "umo": umo_web,
                "platform_id": "webchat",
                "platform_name": "WebChat",
                "name": "审计助手 · WebChat",
                "display_name": "审计助手 · WebChat",
                "type": "webchat",
                "label": "审计助手 · WebChat",
                "persona_id": "persona_demo_audit",
                "persona_name": "安全审计助手 (演示人设)",
                "persona_preview": "架构审计助手，专注权限审计、只读代码核查与交付验证。",
            },
        ],
    )

    # 2. 3 Profiles (ensure rich realistic settings)
    store.save_profile(
        Profile(
            profile_id="default",
            name="标准开发方案",
            description="常规任务默认方案：先只读探索出计划，审批后在授权目录内读写与测试，高危操作自动请示。",
            is_default=True,
            permission_mode="standard",
            plugin_blacklist=[],
            disabled_tools=[],
            authorized_credentials=["cred_github_preview"],
            budget=BudgetConfig(max_total_tokens=200_000, max_total_ticks=40, max_total_seconds=1800, native_steps=24),
            continuity=ContinuityConfig(context_tokens=100_000, context_percent=55, summary_chars=5000, ingress_cap_bytes=14_336),
        ).to_dict()
    )
    store.save_profile(
        Profile(
            profile_id="readonly_research",
            name="只读调研方案",
            description="仅开放读取、搜索与只读命令，严禁写入文件或执行破坏性操作，适合代码审计与资料调研。",
            is_default=False,
            permission_mode="readonly",
            plugin_blacklist=["astrbot_plugin_gitlink"],
            disabled_tools=["astrbot_file_write_tool", "astrbot_file_edit_tool", "astrbot_execute_shell"],
            task_prompt="本方案为只读模式：专注信息搜集、代码审计与结构化结论，不做任何文件修改。",
            budget=BudgetConfig(max_total_tokens=120_000, max_total_ticks=25, max_total_seconds=900, native_steps=20),
            continuity=ContinuityConfig(context_tokens=80_000, context_percent=55, summary_chars=4500, ingress_cap_bytes=12_288),
        ).to_dict()
    )
    store.save_profile(
        Profile(
            profile_id="full_autonomous",
            name="全权限高效方案",
            description="在授权工作区内放宽常规操作限制，保留禁令工具与高危破坏性操作拦截，适合复杂长周期工程。",
            is_default=False,
            permission_mode="full",
            plugin_blacklist=[],
            disabled_tools=[],
            authorized_credentials=["cred_github_preview", "cred_ssh_preview"],
            budget=BudgetConfig(max_total_tokens=500_000, max_total_ticks=80, max_total_seconds=3600, native_steps=32),
            continuity=ContinuityConfig(context_tokens=128_000, context_percent=55, summary_chars=6000, ingress_cap_bytes=16_384),
        ).to_dict()
    )

    # 2b. 5 Realistic Plugin Cards
    store._write_json(
        store.registry_dir / "plugins_catalog.json",
        _preview_plugins_catalog(),
    )

    # 3. 3 Fernet-Encrypted Vault Items (2 secret + 1 personal; never exposed in plaintext)
    store.save_credential(
        {
            "credential_id": "cred_github_preview",
            "label": "GitHub 访问令牌",
            "kind": "secret",
            "provider": "github",
            "env_var": "GITHUB_TOKEN",
            "inject_mode": "env",
            "scope": "global",
            "share_with_tasks": False,
            "note": "仅用于预览环境测试：通过子进程环境变量安全注入，严禁在日志或前端泄露。",
            "value": "mock_gh_token_PreviewSecretTokenValue_9981_DoNotLeak",
        }
    )
    store.save_credential(
        {
            "credential_id": "cred_ssh_preview",
            "label": "部署 SSH 密钥口令",
            "kind": "secret",
            "provider": "ssh",
            "env_var": "SSH_KEY_PASS",
            "inject_mode": "env",
            "scope": "project",
            "authorized_projects": ["proj_async_queue"],
            "share_with_tasks": False,
            "note": "部署节点 SSH 私钥口令，仅授权给异步消息队列与重试优化项目。",
            "value": "ssh-passphrase-preview-4412-secret",
        }
    )
    store.save_credential(
        {
            "credential_id": "cred_git_identity_preview",
            "label": "常用 Git 提交身份",
            "kind": "personal",
            "provider": "personal",
            "env_var": "",
            "inject_mode": "reference",
            "scope": "global",
            "share_with_tasks": True,
            "note": "Git 提交邮箱与署名备忘",
            "value": "demo-maintainer <demo@example.com>",
        }
    )

    # 4. 3 Projects (portable demo workspace paths)
    ws_agent_lab = "/workspace/agent-lab-demo"
    ws_async_queue = "/workspace/async-queue-demo"
    ws_security_audit = "/workspace/security-audit-demo"
    proj_1 = store.save_project(
        Project(
            project_id="proj_agentlab_v1",
            title="astrbot_plugin_agent_lab 重构",
            category="核心架构",
            source_umo=umo_qq,
            platform_id="aiocqhttp",
            profile_id="default",
            sharing=SummarySharingConfig(share_with_daily=False, share_with_tasks=True, task_summary_chars=3000),
            execution_settings=ExecutionSettings(
                mode="standard",
                roots=[ws_agent_lab],
                warnings=["审批:*git push*", "审批:*rm *"],
                authorized_credentials=["cred_github_preview"],
                budget=BudgetConfig(max_total_tokens=100_000, max_total_ticks=40, max_total_seconds=1800),
                continuity=ContinuityConfig(context_tokens=100_000, context_percent=55),
            ),
        ).to_dict(),
        select_for_umo=umo_qq,
    )
    proj_2 = store.save_project(
        Project(
            project_id="proj_async_queue",
            title="异步消息队列与重试优化",
            category="后端服务",
            source_umo=umo_qq,
            platform_id="aiocqhttp",
            profile_id="full_autonomous",
            sharing=SummarySharingConfig(share_with_daily=True, daily_summary_chars=600, share_with_tasks=True),
            execution_settings=ExecutionSettings(
                mode="full",
                roots=[ws_async_queue],
                authorized_credentials=["cred_ssh_preview"],
                budget=BudgetConfig(max_total_tokens=300_000, max_total_ticks=60, max_total_seconds=2400),
            ),
        ).to_dict()
    )
    proj_3 = store.save_project(
        Project(
            project_id="proj_security_audit",
            title="权限守卫与日志审计",
            category="安全合规",
            source_umo=umo_web,
            platform_id="webchat",
            profile_id="readonly_research",
            sharing=SummarySharingConfig(share_with_daily=False, share_with_tasks=True),
            execution_settings=ExecutionSettings(
                mode="readonly",
                roots=[ws_security_audit],
            ),
        ).to_dict(),
        select_for_umo=umo_web,
    )

    # 5. Task 1: 运行中/待审批 + 待回答任务 (task_a1b2c3d4e5f6)
    t1_id = "task_a1b2c3d4e5f6"
    t1_ws = ws_agent_lab
    push_args = {"command": "git push origin feat/v1-webui-unified && rm -rf ./build_cache"}
    push_sig = call_signature("astrbot_execute_shell", push_args, t1_ws, 2)
    t1 = TaskMeta(
        task_id=t1_id,
        umo=umo_qq,
        project_id=proj_1.project_id,
        profile_id="default",
        goal="完成 Agent Lab v1.0.0 统一 WebUI 后端、权限引擎与加密凭证库集成测试",
        brief="替换旧版画布冗余接口，合并原生面板与独立 Quart 服务鉴权，并验证凭证零泄露。",
        status="paused",
        phase="executing",
        wait_reason="need_tool_approval",
        completion_conditions=[
            "webui_api.py 所有 GET/POST 接口通过鉴权与状态码校验",
            "凭证测试确认 state 与 events.jsonl 不含任何明文密钥",
            "pytest 核心回归测试全量通过",
        ],
        constraints=[
            "不得修改宿主 AstrBot 核心源码",
            "禁止在任何日志或提示词中打印 GITHUB_TOKEN",
        ],
        guidance=[
            {"time": now_iso(), "text": "错误响应必须返回真实 HTTP 400/404/409 状态码，不要假 200。"},
        ],
        steps=[
            TaskStep(id="s1", title="梳理 models/store/engine 接口契约", status="completed", stage="探索", summary="确认 TaskMeta/Profile/CredentialMeta 字段与方法签名"),
            TaskStep(id="s2", title="实现 WebUIController 与 @admin_api 鉴权", status="completed", stage="开发", summary="已完成 23 个 workspace actions 及方案/凭证端点"),
            TaskStep(id="s3", title="运行端到端集成测试并验证脱敏", status="running", stage="验证", summary="正在执行本地预览与脱敏检查"),
            TaskStep(id="s4", title="推送分支并清理临时构建缓存", status="pending", stage="发布"),
            TaskStep(id="s5", title="生成项目 SUMMARY.md 并交付", status="pending", stage="交付"),
        ],
        current_step_id="s3",
        current_summary="已完成 WebUI 后端与鉴权守卫改造，正在等待推送/清理高危操作审批及架构确认。",
        version=2,
        approved_version=2,
        authorization_version=2,
        input_revision=3,
        scope_roots=[t1_ws],
        authorized_scope_roots=[t1_ws],
        session_workspace_root=t1_ws,
        execution_cwd=t1_ws,
        execution_settings=ExecutionSettings(
            mode="standard",
            roots=[t1_ws],
            warnings=["审批:*git push*", "审批:*rm *"],
            authorized_credentials=["cred_github_preview"],
            budget=BudgetConfig(max_total_tokens=100_000, max_total_ticks=40, max_total_seconds=1800, native_steps=24),
            continuity=ContinuityConfig(context_tokens=100_000, context_percent=55, summary_chars=5000, ingress_cap_bytes=14_336),
        ),
        questions=[
            QuestionItem(
                question_id="q_webui_mode",
                question="独立 Quart WebUI 未配置访问令牌时，建议采用哪种安全启动策略？",
                options=[
                    "token 为空时拒绝启动独立端口，仅保留 AstrBot 原生插件面板（推荐）",
                    "token 为空时仅绑定 127.0.0.1 无鉴权启动",
                    "自动生成随机临时 token 并输出到插件日志",
                ],
                recommendation="推荐选项 1：避免公网误暴露，同时 AstrBot Dashboard 面板始终可用。",
            )
        ],
        approvals=[
            ApprovalRequest(
                approval_id="apr_plan_v1",
                approval_type="task_plan",
                operation="初始执行计划审批",
                reason="初始执行计划（5 个步骤）",
                status="approved",
                decision="approved",
                plan_version=1,
                workspace_root=t1_ws,
                resolved_at=now_iso(),
            ),
            ApprovalRequest(
                approval_id="apr_push_clean",
                approval_type="tool_batch",
                operation="推送远程分支并清理 build_cache 目录",
                reason="命中自定义审批规则「*git push*」及递归清理命令",
                impact="将把 feat/v1-webui-unified 推送至 origin，并删除本地 ./build_cache 目录。",
                rollback="远程分支可通过 git push -f 回退；本地 build_cache 可重新构建恢复。",
                message="集成测试已全部通过，申请批准执行远程推送与缓存清理。",
                status="pending",
                plan_version=2,
                workspace_root=t1_ws,
                calls=[
                    {
                        "tool_name": "astrbot_execute_shell",
                        "arguments": push_args,
                        "signature": push_sig,
                        "call_signature": push_sig,
                        "execution_status": "pending",
                        "status": "pending",
                    }
                ],
            ),
        ],
        usage=UsageTotals(
            prompt_tokens=31_200,
            completion_tokens=11_600,
            total_tokens=42_800,
            llm_calls=14,
            tool_calls=19,
            ticks_used=6,
            last_context_chars=28_400,
            last_estimated_tokens=9_600,
            handoff_count=1,
            last_handoff_chars=3_850,
            last_handoff_tokens=1_280,
        ),
    )
    store.save_task(t1, active=True)

    # Save real tool_results files for preview modal
    p_call1 = store.save_tool_result(
        umo_qq,
        t1_id,
        "call_001_pytest",
        (
            "=== Agent Lab v1.0.0 回归测试报告 ===\n"
            "测试目录: tests/\n"
            "collected 42 items\n\n"
            "tests/test_permissions.py ........ [ 19%]\n"
            "tests/test_store_redaction.py ...... [ 33%]\n"
            "tests/test_engine_fences.py .......... [ 57%]\n"
            "tests/test_context_handoff.py ........ [ 76%]\n"
            "tests/test_webui_api.py .......... [100%]\n\n"
            "42 passed in 1.84s\n"
            "SECRET_CHECK: GITHUB_TOKEN=******** (已脱敏，未检测到明文泄露)\n"
        ),
    )
    p_call2 = store.save_tool_result(
        umo_qq,
        t1_id,
        "call_002_tree",
        (
            "astrbot_plugin_agent_lab/\n"
            "├── main.py (501 lines)\n"
            "├── agent_lab/\n"
            "│   ├── models.py\n"
            "│   ├── store.py\n"
            "│   ├── permissions.py\n"
            "│   ├── guards.py\n"
            "│   ├── context_engine.py\n"
            "│   ├── bridge.py\n"
            "│   ├── engine.py\n"
            "│   └── webui_api.py\n"
            "└── scripts/preview_webui.py\n"
        ),
    )
    store.append_event(
        umo_qq,
        t1_id,
        "journal",
        {
            "call_id": "call_002_tree",
            "tool_name": "astrbot_list_directory",
            "arguments": {"directory": t1_ws},
            "status": "completed",
            "step_id": "s1",
            "output_bytes": p_call2.stat().st_size,
            "result_path": str(p_call2.relative_to(store.root)).replace("\\", "/"),
        },
    )
    store.append_event(
        umo_qq,
        t1_id,
        "journal",
        {
            "call_id": "call_001_pytest",
            "tool_name": "astrbot_execute_shell",
            "arguments": {"command": "pytest -q tests/"},
            "status": "completed",
            "step_id": "s3",
            "output_bytes": p_call1.stat().st_size,
            "result_path": str(p_call1.relative_to(store.root)).replace("\\", "/"),
        },
    )
    for m_kind, m_text in (
        ("stage", "阶段切换：已通过初始计划审批，由只读探索阶段（planning）进入隔离执行阶段（executing）。"),
        ("progress", "步骤 s2 完成：WebUIController 与 StandaloneWebUIServer 已实现，支持 Modern/Classic 双主题偏好持久化。"),
        ("progress", "已完成上下文自动交接（Handoff #1）：累计 42,800 / 100,000 tokens，上下文压缩至 3,850 字符。"),
        ("question", "❓ 需要您的确认：独立 Quart WebUI 未配置访问令牌时，建议采用哪种安全启动策略？"),
        ("approval", "🔐 请求操作审批（1 项）：推送远程分支并清理 build_cache 目录。原因：命中规则 `*git push*` 及递归清理命令。"),
    ):
        store.append_event(
            umo_qq,
            t1_id,
            "message",
            {"direction": "outbound", "msg_kind": m_kind, "delivery": "sent", "text": m_text},
        )
    store.append_event(
        umo_qq,
        t1_id,
        "usage",
        {"prompt_tokens": 18200, "completion_tokens": 6400, "total_tokens": 24600, "cumulative_tokens": 24600, "reported": True},
    )
    store.append_event(
        umo_qq,
        t1_id,
        "usage",
        {"prompt_tokens": 13000, "completion_tokens": 5200, "total_tokens": 18200, "cumulative_tokens": 42800, "reported": True},
    )

    # 6. Task 2: 异常待核对任务 (task_b2c3d4e5f6a7)
    t2_id = "task_b2c3d4e5f6a7"
    t2 = TaskMeta(
        task_id=t2_id,
        umo=umo_qq,
        project_id=proj_2.project_id,
        profile_id="full_autonomous",
        goal="压测异步消息队列并发消费并定位偶发 120s 投递超时根因",
        status="paused",
        phase="executing",
        wait_reason="unknown_call",
        steps=[
            TaskStep(id="s1", title="采集近期消息队列消费 P95/P99 延时分布", status="completed", stage="诊断"),
            TaskStep(id="s2", title="复现并发排队阻塞并抓取连接池快照", status="running", stage="压测"),
            TaskStep(id="s3", title="调整连接复用与指数退避重试参数", status="pending", stage="优化"),
        ],
        current_step_id="s2",
        current_summary="压测脚本执行超过单次 180s 超时阈值，系统已将其标记为 unknown 并安全暂停，等待管理员核对实际执行结果。",
        version=1,
        approved_version=1,
        authorization_version=1,
        scope_roots=[ws_async_queue],
        authorized_scope_roots=[ws_async_queue],
        session_workspace_root=ws_async_queue,
        execution_cwd=ws_async_queue,
        usage=UsageTotals(prompt_tokens=12_400, completion_tokens=3_900, total_tokens=16_300, llm_calls=5, tool_calls=6, ticks_used=3),
    )
    store.save_task(t2, active=False)
    store.append_event(
        umo_qq,
        t2_id,
        "journal",
        {
            "call_id": "call_timeout_01",
            "tool_name": "astrbot_execute_shell",
            "arguments": {"command": "python scripts/bench_async_queue.py --concurrency 8 --rounds 20"},
            "status": "unknown",
            "step_id": "s2",
            "error": "timeout after 180.0s: subprocess did not exit before deadline",
        },
    )
    store.append_event(
        umo_qq,
        t2_id,
        "message",
        {
            "direction": "outbound",
            "msg_kind": "alert",
            "delivery": "sent",
            "text": "⚠️ 工具 `astrbot_execute_shell` (`call_timeout_01`) 执行超时，结果状态未知，任务已暂停等待对账。",
        },
    )

    # 7. Task 3: 已完成归档任务 (task_c3d4e5f6a7b8)
    t3_id = "task_c3d4e5f6a7b8"
    t3_summary = (
        "已完成 Agent Lab v1.0.0 存储层与权限守卫模块重构：\n"
        "1. 将旧版单体超大 JSON 拆分为轻量 meta.json (<5KB) 与 O(1) 追加写 events.jsonl；\n"
        "2. 落地不可变终态栅栏 ended/<task_id>.json 与 Fernet 凭证加密保险库；\n"
        "3. 实现只读规划期工具隔离、越界路径检测及防环境变量外泄 AST/Shell 检查。"
    )
    t3 = TaskMeta(
        task_id=t3_id,
        umo=umo_qq,
        project_id=proj_1.project_id,
        profile_id="default",
        goal="重构存储引擎与权限守卫模块，消除旧版性能与安全隐患",
        status="completed",
        phase="completed",
        wait_reason="",
        steps=[
            TaskStep(id="s1", title="设计 meta.json + events.jsonl 分离存储", status="completed", stage="架构"),
            TaskStep(id="s2", title="实现 Fernet 加密凭证库与多编码脱敏", status="completed", stage="安全"),
            TaskStep(id="s3", title="补充单元测试并核验交付", status="completed", stage="验证"),
        ],
        current_step_id="s3",
        current_summary=t3_summary,
        final_summary=t3_summary,
        version=1,
        approved_version=1,
        authorization_version=1,
        scope_roots=[ws_agent_lab],
        authorized_scope_roots=[ws_agent_lab],
        session_workspace_root=ws_agent_lab,
        execution_cwd=ws_agent_lab,
        usage=UsageTotals(prompt_tokens=21_000, completion_tokens=7_450, total_tokens=28_450, llm_calls=9, tool_calls=15, ticks_used=4),
        ended_at=now_iso(),
    )
    store.mark_ended(t3, "completed", "agent")
    store.save_task(t3, active=False, allow_terminal=True)
    store.save_project_summary(proj_1.project_id, t3_summary, task_id=t3_id, auto=True)
    store.append_event(
        umo_qq,
        t3_id,
        "message",
        {"direction": "outbound", "msg_kind": "delivery", "delivery": "sent", "text": f"🎉 任务 `{t3_id}` 已完成交付：\n{t3_summary}"},
        allow_terminal=True,
    )

    # 8. Task 4: 只读调研任务 (task_d4e5f6a7b8c9)
    t4_id = "task_d4e5f6a7b8c9"
    t4 = TaskMeta(
        task_id=t4_id,
        umo=umo_web,
        project_id=proj_3.project_id,
        profile_id="readonly_research",
        goal="只读审计 WebUI 静态资源与路由鉴权覆盖率，输出风险清单",
        status="paused",
        phase="planning",
        wait_reason="need_plan_approval",
        constraints=["严格只读模式：禁止修改任何代码或配置文件"],
        steps=[
            TaskStep(id="s1", title="扫描所有 WebUI API 路由与装饰器使用情况", status="pending", stage="审计"),
            TaskStep(id="s2", title="核查前端 DOM 渲染是否存在 XSS 拼接风险", status="pending", stage="审计"),
            TaskStep(id="s3", title="输出分级安全审计报告（仅只读报告，不改动源码）", status="pending", stage="报告"),
        ],
        current_step_id="s1",
        current_summary="已基于 readonly_research 方案完成初步目录摸底，提交 3 步只读审计计划等待确认。",
        version=1,
        approved_version=0,
        authorization_version=0,
        scope_roots=[ws_security_audit],
        authorized_scope_roots=[ws_security_audit],
        session_workspace_root=ws_security_audit,
        execution_cwd=ws_security_audit,
        approvals=[
            ApprovalRequest(
                approval_id="apr_audit_plan",
                approval_type="task_plan",
                operation="初始计划审批",
                reason="初始只读审计执行计划（共 3 步）",
                message="本任务采用只读调研方案，全程仅读取文件并生成审计结论。",
                status="pending",
                plan_version=1,
                workspace_root=ws_security_audit,
            )
        ],
        usage=UsageTotals(prompt_tokens=4_800, completion_tokens=1_250, total_tokens=6_050, llm_calls=2, tool_calls=3, ticks_used=1),
    )
    store.save_task(t4, active=True)
    store.append_event(
        umo_web,
        t4_id,
        "message",
        {
            "direction": "outbound",
            "msg_kind": "approval",
            "delivery": "sent",
            "text": "📋 任务 `task_d4e5f6a7b8c9` 提交计划 v1（初始计划审批）：等待确认后开始只读审计。",
        },
    )


async def run_preview(host: str, port: int, data_dir: Path, *, reset: bool) -> None:
    store = AgentLabStore(data_dir)
    seed_preview_data(store, reset=reset)
    engine = TaskEngine(store, context=None, config={})
    controller = WebUIController(store, engine, context=None, config={}, preview_mode=True)
    static_dir = PLUGIN_ROOT / "pages" / "agent-lab"
    server = StandaloneWebUIServer(
        controller=controller,
        static_dir=static_dir,
        host=host,
        port=port,
        token="",
        preview_mode=True,
    )

    await server.start()
    print("=" * 64)
    print("Agent Lab v1.0.0 本地交互式 WebUI 预览已启动")
    print(f"  访问地址 : http://{host}:{port}")
    print(f"  健康检查 : http://{host}:{port}/api/health")
    print(f"  状态接口 : http://{host}:{port}/api/state")
    print(f"  静态目录 : {static_dir}")
    print(f"  预览数据 : {data_dir}")
    print("  按 Ctrl+C 停止预览服务器")
    print("=" * 64)

    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await server.stop()
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Lab v1.0.0 本地 WebUI 交互式预览服务器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8799, help="监听端口（默认 8799）")
    parser.add_argument(
        "--data-dir",
        default=str(PLUGIN_ROOT / "data_preview"),
        help="预览示例数据目录（默认 ./data_preview）",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="清空并重新生成示例预览数据",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_preview(args.host, args.port, Path(args.data_dir), reset=args.reset))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
