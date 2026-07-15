from uuid import uuid4

from module.logger import logger
from module.notify.configuration import SmtpNotificationConfig
from module.notify.notify import SmtpNotificationSender

_MAX_ATTEMPTS = 2


def _send_recipient(
    sender: SmtpNotificationSender,
    *,
    recipient: str,
    title: str,
    content: str,
    idempotency_key: str,
) -> bool:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            sender.send(
                recipient=recipient,
                title=title,
                content=content,
                idempotency_key=idempotency_key,
            )
        except Exception as error:  # noqa: BLE001 - 通知失败不能改变任务结果。
            if attempt + 1 < _MAX_ATTEMPTS:
                logger.warning(
                    "SMTP notify failed, retry once "
                    f"recipient={recipient!r} error_type={type(error).__name__!r} error={str(error)!r}"
                )
                continue
            logger.exception(error)
            return False
        return True
    return False


def send_notification(config: SmtpNotificationConfig, *, title: str, content: str) -> bool:
    """同步发送给全部收件人；每人最多重试一次，任一失败时返回 False。"""

    if not isinstance(config, SmtpNotificationConfig):
        message = "config must be an SmtpNotificationConfig"
        raise TypeError(message)
    if not isinstance(title, str):
        message = "title must be a string"
        raise TypeError(message)
    if not isinstance(content, str):
        message = "content must be a string"
        raise TypeError(message)

    sender = SmtpNotificationSender(config)
    notification_id = uuid4().hex
    succeeded = True
    for index, recipient in enumerate(config.recipients):
        delivered = _send_recipient(
            sender,
            recipient=recipient,
            title=title,
            content=content,
            idempotency_key=f"direct:{notification_id}:{index}",
        )
        succeeded = delivered and succeeded

    if succeeded:
        logger.info("SMTP notify success")
    return succeeded
