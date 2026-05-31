# Agent Lab WebUI Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $superpower-subagents (recommended) or $superpower-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking via update_plan.

**Goal:** Make Agent Lab's standalone console usable for real task-mode configuration, entry/exit operation, global-vs-entry application choice, and visual workflow editing.

**Architecture:** Keep the existing standalone Quart WebUI and AgentSpec persistence. Add explicit configuration fields for application scope and entry channel, reshape the Canvas into a task-mode cockpit with a real workflow board, and make the Tasks page start tasks from the selected AgentSpec without forcing users to understand raw UMO first.

**Tech Stack:** AstrBot plugin, Python dataclasses/storage, Quart routes, vanilla HTML/CSS/JS standalone console, existing smoke tests.

---

### Task 1: Persist Task-Mode Scope And Entry Settings

**Files:**
- Modify: `agent_lab/models.py`
- Modify: `scripts/smoke_test.py`
- Modify: `scripts/runtime_smoke_test.py`

- [ ] **Step 1: Add AgentSpec fields**

Add `application_scope: str = "entry"` and `entry_channel: str = "command"` to `AgentSpec`. Valid `application_scope` values are `global` and `entry`; valid `entry_channel` values are `command`, `natural`, and `webui`.

- [ ] **Step 2: Preserve legacy specs**

Rely on `AgentSpec.from_dict()` existing key filtering so older JSON files load with defaults. Do not add a migration file.

- [ ] **Step 3: Assert defaults**

In `scripts/smoke_test.py`, assert a default AgentSpec has `application_scope == "entry"` and `entry_channel == "command"`.

### Task 2: Rebuild Canvas As The Primary Configuration Cockpit

**Files:**
- Modify: `webui/app.js`
- Modify: `webui/style.css`

- [ ] **Step 1: Add user-facing labels**

Add helpers for trigger mode, memory mode, approval mode, heartbeat mode, application scope, entry channel, workflow kind, and saved/unsaved state text.

- [ ] **Step 2: Add explicit entry controls**

In `renderCanvas()`, replace the dense form-first layout with: selected Agent header, application scope segmented controls, entry channel controls, trigger/memory/approval/heartbeat selectors, task start controls, and save/default actions.

- [ ] **Step 3: Add visual workflow board**

Replace the current grid of cards plus raw edge text with a board containing columns for entry, planning/state, execution/tool, guard, checkpoint, and archive. Render edge chips between nodes and keep the inspector for editing selected node title/kind/description.

- [ ] **Step 4: Make raw JSON secondary**

Keep workflow JSON in an advanced details block only. Editing nodes and edges through controls remains the default path.

### Task 3: Make Task Entry And Exit Operable From WebUI

**Files:**
- Modify: `webui/app.js`
- Modify: `webui/style.css`

- [ ] **Step 1: Add selected-Agent task start controls**

Add `canvas-umo`, `canvas-goal`, `canvas-completion`, `canvas-brief`, `canvas-start-heartbeat`, and `canvas-risk-level` controls. Starting a task posts to `/api/task/start` with the selected `agent_id`.

- [ ] **Step 2: Improve Tasks page wording**

Rename task actions to enter, tick, heartbeat, finish/archive, and cancel/archive. Show that private chat commands are the normal entry path, while WebUI entry is an operator/debug path.

- [ ] **Step 3: Add cancellation action in Tasks page**

Expose cancel/archive alongside finish/archive so entry and exit can both be verified without jumping to Monitor.

### Task 4: Fix API Route Mismatches And Validation

**Files:**
- Modify: `agent_lab/webui_server.py`
- Modify: `webui/app.js`
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Add standalone route alias**

Register `/api/modules` as an alias to `owner.api_modules`, matching the existing front-end button and AstrBot Dashboard route naming.

- [ ] **Step 2: Keep front-end endpoint consistent**

Use `/api/modules` for manifest import. Keep `/api/integrations` for state/listing compatibility.

- [ ] **Step 3: Test the alias**

Extend `smoke_webui_server()` to GET or POST `/api/modules` with the token and expect HTTP 200.

### Task 5: Verify End To End

**Files:**
- Run-only verification.

- [ ] **Step 1: Compile Python**

Run `python -m compileall -q .`; expected: no output and exit 0.

- [ ] **Step 2: Run repository smoke test**

Run `python scripts/smoke_test.py`; expected: `Agent Lab smoke test passed.`

- [ ] **Step 3: Run runtime smoke test**

Run `python scripts/runtime_smoke_test.py`; expected: `Agent Lab runtime smoke test passed.`

- [ ] **Step 4: Visual WebUI check**

Open the standalone/mocked WebUI and verify Canvas shows explicit global-vs-entry choice, entry channel, selected Agent task entry, workflow node editing, edge add/delete, save/default buttons, and no overlapping text at desktop and mobile widths.

