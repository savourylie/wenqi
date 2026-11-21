# Ticket Index

> **Last updated**: 2026-11-21
>
> Source: `zh_polish_skill_spec_v2.md`（wenqi v2.0.0 技術與理論規格）．Operation: Create．
> 分階段依規格 §8.2 路線圖：Milestone 1 基礎建設與 L0/L5 → Milestone 2 四層規則引擎 → Milestone 3 六個 Skills → Milestone 4 E2E Dogfooding。

## Summary

| Status | Count |
| --- | --- |
| ✅ Done | 11 |
| 🔧 In Progress | 0 |
| 📋 Pending | 5 |
| 🚫 Blocked | 2 |
| ⏸️ Deferred | 0 |

## Phase 1 — 基礎建設與 L0/L5（Milestone 1）

| # | Ticket | Status | Depends On | Notes |
| --- | --- | --- | --- | --- |
| 001 | [專案骨架與內建詞庫](./001-project-scaffold-and-default-lexicons.md) | `done` | — | 12 tests passed；PR #1 |
| 002 | [非侵入式狀態管理與 Content Hash 對齊](./002-state-manager-persistence.md) | `done` | #001 ✅ | 41 tests passed；PR #2 |
| 003 | [TokenizerAdapter 與 JiebaPosAdapter](./003-tokenizer-adapter.md) | `done` | #001 ✅ | 55 tests passed；PR #3 |
| 004 | [L0 預處理：Markdown 遮罩與的／地／得消歧義](./004-l0-normalizer.md) | `done` | #003 ✅ | 108 tests passed · PR #5 |
| 005 | [L5 預檢：疑似術語抽取與語體推測](./005-l5-preflight.md) | `done` | #002 ✅, #003 ✅ | 130 tests passed · PR #6 |
| 006 | [Scanner CLI 與 Diagnostic Payload 契約](./006-scanner-cli-payload-contract.md) | `done` | #002 ✅, #004 ✅, #005 ✅ | 143 tests passed · PR #7 |

## Phase 2 — 四層規則引擎（Milestone 2）

| # | Ticket | Status | Depends On | Notes |
| --- | --- | --- | --- | --- |
| 007 | [L1 規則引擎：詞性與語態重心](./007-l1-vitality-rules.md) | `done` | #006 ✅ | 合併驗收 323 項通過 · [PR #8](https://github.com/savourylie/wenqi/pull/8) |
| 008 | [L2 規則引擎：修飾與包孕結構](./008-l2-branching-rules.md) | `done` | #006 ✅ | 394 項通過 · 3 項預期失敗 · [PR #9](https://github.com/savourylie/wenqi/pull/9) |
| 009 | [L3 規則引擎：邏輯與銜接機制](./009-l3-logic-rules.md) | `done` | #006 ✅ | L3 回歸 137 項通過 · 盲測 20/20 · [PR #12](https://github.com/savourylie/wenqi/pull/12) |
| 010 | [L4 規則引擎：篇章呼吸與音律節奏](./010-l4-cadence-rules.md) | `done` | #006 ✅ | 809 項通過 · 外部題庫 64/64 · [PR #14](https://github.com/savourylie/wenqi/pull/14) |
| 011 | **[TEST: Checkpoint 1 — Golden Test Suite 全層整合驗證](./011-test-checkpoint-1-golden-suite.md)** | `done` | #007 ✅, #008 ✅, #009 ✅, #010 ✅ | 5 項 Golden 通過 · 814 項回歸 · [PR #15](https://github.com/savourylie/wenqi/pull/15) |

## Phase 3 — 六個 Agent Skills（Milestone 3）

| # | Ticket | Status | Depends On | Notes |
| --- | --- | --- | --- | --- |
| 012 | [Skill：zh-l5-guard 守門員](./012-skill-zh-l5-guard.md) | `pending` | #011 ✅ | |
| 013 | [Skills：zh-l1～zh-l4 單層正交技能](./013-skills-single-layer-l1-l4.md) | `pending` | #011 ✅ | 四份 SKILL.md 共用正交隔離與 Diff 規範 |
| 014 | [Skill：wenqi-all 總調度器](./014-skill-wenqi-all.md) | `blocked` | #012, #013 | |

## Phase 4 — 端到端驗收（Milestone 4）

| # | Ticket | Status | Depends On | Notes |
| --- | --- | --- | --- | --- |
| 015 | **[TEST: Checkpoint 2 — E2E Dogfooding 與詞庫微調](./015-test-checkpoint-2-e2e-dogfooding.md)** | `blocked` | #014 | Gate: 最終交付驗收；需使用者作者裁決 |

## Follow-up fixes

| # | Ticket | Status | Depends On | Notes |
| --- | --- | --- | --- | --- |
| 016 | [L0 消歧修正：名詞性時間詞組後的「的」](./016-l0-nominal-time-de-role.md) | `pending` | #004 ✅ | R-33，涉及 #007、#008 |
| 017 | [L2 左錨修正：名物化主語誤判為謂語](./017-l2-left-anchor-nominal-subject.md) | `pending` | #008 ✅ | N02 長前飾誤報，盲測跟進 |
| 018 | [L0 補語判定修正：程度副詞後的 vn](./018-l0-complement-degree-vn.md) | `pending` | #004 ✅ | N03 補語錯字漏報，盲測跟進 |

## Status Key

| Status | Meaning |
| --- | --- |
| `pending` | Ready to start; all dependencies met |
| `in-progress` | Currently being implemented |
| `done` | Implemented and verified |
| `blocked` | Waiting on a dependency |
| `deferred` | Intentionally postponed; reason noted |
