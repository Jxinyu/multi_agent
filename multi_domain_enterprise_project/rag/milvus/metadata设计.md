好的，我重新整理一份更实用的 Metadata 设计方案，按功能分类，每个字段都有明确的中文说明，方便你在实际项目中参考落地。

---

## 一、Metadata 设计总览

| 分类 | 字段名 | 类型 | 必填 | 中文说明 | 示例值 |
|------|--------|------|------|----------|--------|
| **系统标识** | `id` | string | 是 | 切片唯一标识，通常由 `file_id` + 序号生成，用于精确追溯和删除操作 | `file_abc123_003` |
| | `file_id` | string | 是 | 原始文件的全局唯一标识，关联文件存储或数据库中的文件记录 | `file_abc123` |
| | `source_type` | string | 是 | 文档来源类型，用于区分不同渠道导入的内容（如 `pdf`、`word`、`confluence`、`slack`） | `confluence` |
| | `created_at` | timestamp | 是 | 切片入库时间，用于时间范围过滤或数据清理 | `2026-03-20T10:30:00Z` |
| | `version` | string | 否 | 文档版本号，支持知识库版本管理与回滚 | `v2.1.0` |
| **权限与租户** | `tenant_id` | string | 是 | 租户标识，多租户 SaaS 场景下必填，用于物理或逻辑隔离租户数据 | `tenant_acme` |
| | `org_id` | string | 否 | 组织/部门 ID，用于企业内部的部门级数据隔离 | `org_finance` |
| | `team_id` | string | 否 | 团队 ID，更细粒度的权限划分 | `team_tax` |
| | `owner_id` | string | 是 | 上传者或所有者的用户 ID，用于个人数据隔离 | `user_zhangshan` |
| | `visibility` | string | 是 | 可见性范围：`private`（仅自己）、`team`（团队）、`org`（部门）、`public`（全租户公开） | `team` |
| | `acl` | array | 否 | 访问控制列表，存储允许访问的用户 ID 或用户组 ID，用于动态权限 | `["user_lisi", "group_finance_mgr"]` |
| **业务分类** | `knowledge_base_id` | string | 否 | 知识库 ID，当系统中有多个知识库（如“产品手册”、“内部政策”）时，用于限定检索范围 | `kb_product_manual` |
| | `category` | string | 否 | 内容大类，如 `contract`（合同）、`policy`（制度）、`faq`（常见问题）、`technical`（技术文档） | `contract` |
| | `tags` | array | 否 | 自定义标签列表，支持灵活的分类与检索 | `["annual_report", "tax", "2025"]` |
| | `language` | string | 否 | 文档语言，用于多语言知识库的精确检索 | `zh-CN` |
| | `status` | string | 否 | 文档生命周期状态：`draft`（草稿）、`published`（已发布）、`archived`（已归档） | `published` |
| **文档属性** | `title` | string | 否 | 文档标题，可在检索结果中直接展示，提升可读性 | `2025年度税务合规报告.pdf` |
| | `author` | string | 否 | 文档作者，用于溯源 | `张山` |
| | `created_date` | date | 否 | 文档原始创建日期，非切片入库时间 | `2025-12-01` |
| | `updated_date` | date | 否 | 文档最后更新日期，可用于“仅检索最新内容”的逻辑 | `2026-02-15` |
| | `department` | string | 否 | 归属部门，便于按部门维度统计和检索 | `财务部` |
| | `confidentiality` | string | 否 | 密级：`public`（公开）、`internal`（内部）、`confidential`（保密）、`top_secret`（绝密） | `confidential` |
| **扩展与增强** | `parent_chunk_id` | string | 否 | 父子切片场景中，指向父切片的 ID，用于检索到子切片时返回完整的父切片内容 | `file_abc123_001` |
| | `ext` | map | 否 | 扩展字段，存储业务自定义的、不参与过滤的属性，避免频繁修改 schema | `{"project_code":"PJ123","region":"APAC"}` |

---