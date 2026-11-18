# 《再等一班》镜头清单

M1 咖啡馆场次四镜（`15a`–`15d`）共 15 秒，当前全部为 `pending`。`project.yaml` 与 `shots.yaml` 统一采用标准 YAML 写法，由 `PyYAML`（`yaml.safe_load`）读取。资产路径相对仓库根目录并记录 `sha256`；候选媒体与审片记录（`selected.review`）路径相对项目目录。`dialogue.at`/`end` 相对选用片段入点，当前为预估值，生成候选后按原片校正。原片放 `input/`，中间产物放 `build/`，导出成片放 `output/`；`prompts/` 与 `reviews/` 在 T1.1 及首次审片落盘时创建。
