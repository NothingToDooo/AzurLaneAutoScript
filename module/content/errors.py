class ContentValidationError(ValueError):
    """内容契约输入无效。"""


class ContentCatalogError(ContentValidationError):
    """内容目录违反内部不变量。"""


class UnknownPackError(LookupError):
    """内容目录中不存在指定内容包。"""


class UnknownStageError(LookupError):
    """内容目录中不存在指定关卡。"""


class UnknownActivityError(LookupError):
    """内容目录中不存在指定活动玩法。"""


class ActivityKindError(ContentValidationError):
    """内容包声明的活动玩法与调用方要求的类型不一致。"""
