# 软件兼容性知识

条目是数据，不含自动执行脚本。`entries/*.json` 由 `rungic-suggestions --validate-knowledge` 校验，随软件包发布。版本采用精确匹配，不把历史测试外推到新版本；`policy` 保留有意选择，永远不自动生成优化提示。`research` 与 `superseded` 不生成已验证建议。

新条目须包含 schema=1、稳定 id、title、kind（issue/optimization/policy）、status（verified/research/superseded）、reviewed、explanation、match.package、match.versions 和非空 evidence。policy 可留空版本，表示仅作调查原则参考，不证明任何版本兼容、不生成优化提示。可选 match.environment 与本机发布记录字段逐项相等，否则不匹配。每项事实分别说明研究、离线和实机证据；原始设备资料仍放 `.work/`。

维护流程：读取现有条目与来源 → 最小复现 → 明确适用范围 → 生成知识变更 → 验证后纳入发布。实际补丁仍在 `packages/`，调查报告仍在 `docs/`。`upstreams.json` 是对外协作入口与规则记录，不授予自动提交权限。

设备上 `rungic-suggestions feedback ID` 只生成内部事实材料；`rungic-suggestions update ID '{"upstream":{"state":"submitted","url":"https://…"}}'` 记录维护者实际核对的外部状态，不执行提交。`merged` 不会将本机问题标为已解决。未知项目先定位责任边界，再核对当前贡献规则。
