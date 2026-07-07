from datetime import timedelta

from module.config.utils import server_time_offset


def test_cn_personal_branch_uses_local_time_as_server_time() -> None:
    assert server_time_offset() == timedelta()
