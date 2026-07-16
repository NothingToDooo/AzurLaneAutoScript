from module.logger import logger
from module.notify.configuration import SmtpNotificationConfig
from module.notify.notify import SmtpNotificationSender


def send_notification(config: SmtpNotificationConfig, *, title: str, content: str) -> bool:
    """同步发送给全部收件人；任一失败时返回 False。"""

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
    succeeded = True
    for recipient in config.recipients:
        try:
            sender.send(recipient=recipient, title=title, content=content)
        except Exception as error:  # noqa: BLE001 - 通知失败不能改变任务结果。
            logger.error(f"SMTP notify failed for {recipient}: {type(error).__name__}: {error}")
            succeeded = False

    if succeeded:
        logger.info("SMTP notify success")
    return succeeded
