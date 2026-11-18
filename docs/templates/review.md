---
schema_version: 1
reviewer: ""
reviewed_at: ""
output_file: ""
output_sha256: ""
edl_file: ""
edl_sha256: ""
manifest_commit: ""
decisions:
  "15a":
    candidate: c1
    status: pending
---

# 场次审片

顶部 YAML frontmatter 供 `tools/validate.py` 校验，须与下方人工审片记录保持一致：

- `reviewer`：人工审片人姓名或账号（必填，禁止填写 agent / bot / ai 等自动程序标识）。
- `reviewed_at`：审片日期（`YYYY-MM-DD` 或带时区 ISO 8601 时间）。
- `decisions.<shot_id>`：记录所审候选 `candidate` 与结论 `status`（`approved` 通过 / `reshoot` 补拍 / `reselect` 换候选 / `pending` 待审）。

## 审片对象

- 成片文件与 sha256：待填写
- 镜头清单提交号：待填写
- EDL 路径与 sha256：待填写
- 镜号范围与候选版本：待填写

## 开声检查

核对台词归属、漏词、口型同步、音色连续、停顿、闭口倾听反应，以及房间底声与动作拟音是否服从画面。

## 静音检查

核对动作因果、视线方向、男左女右站位、杯子与车票等道具状态、服装与人脸跨镜一致性。

## 逐镜结论

| 镜号 | 候选 | 成片时间点 | 结论（approved / reshoot / reselect） | 问题与依据 |
|---|---|---|---|---|
| 15a | c1 | 待填写 | pending | 待填写 |

## 人工结论

登记人工审片人对具体版本的实际结论后，再将通过镜头的 `shots.yaml` 状态更新为 `approved`，并在 `selected.review` 指向本记录文件。单镜补拍或替换后须复查前后切镜衔接并更新回归结论。
