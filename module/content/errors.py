class ContentValidationError(ValueError):
    """内容契约输入无效。"""


class ContentCatalogError(ContentValidationError):
    """内容目录违反内部不变量。"""


class UnknownPackError(LookupError):
    """内容目录中不存在指定内容包。"""


class UnknownStageError(LookupError):
    """内容目录中不存在指定关卡。"""


class LegacyStageReferenceError(ContentValidationError):
    """历史关卡引用不能安全映射到 Python 模块。"""


class LegacyStageContractError(TypeError):
    """历史关卡模块没有满足装载契约。"""
