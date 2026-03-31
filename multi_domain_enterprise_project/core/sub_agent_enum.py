from enum import Enum


class SubAgentEnum(Enum):
    FINANCE = ("finance", "财务代理: 解答差旅报销规则、预算申请流程、采购 SOP 等问题。")
    TECH = ("tech", "技术代理： 负责解答 API 文档、内部系统架构、代码规范、项目Wiki等问题。")
    LEGAL = ('legal', "法律代理： 解答保密协议、数据保护法、合同模板等企业内合规问题。")
    HR = ('hr', "HR代理: 专门解答员工手册、请假制度、入职流程、福利政策等问题。")

    def __new__(cls, code, description):
        obj = object.__new__(cls)
        obj._value_ = code          # 将值设为 code
        obj.description = description  # 附加描述
        return obj


if __name__ == '__main__':
    try:
        o = SubAgentEnum("hr")
    except:
        print("不存在")

    print(SubAgentEnum.HR.value)
    print(SubAgentEnum.HR.description)
    print([i for i in SubAgentEnum])
