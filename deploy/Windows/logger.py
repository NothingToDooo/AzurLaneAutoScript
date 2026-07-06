import logging
import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), "../../"))

logger = logging.getLogger("deploy")
_logger = logger

formatter = logging.Formatter(fmt="%(message)s")
hdlr = logging.StreamHandler(stream=sys.stdout)
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)


def hr(title, level=3):
    if logger is not _logger:
        return logger.hr(title, level)

    title = str(title).upper()
    if level == 0:
        middle = "|" + " " * 20 + title + " " * 20 + "|"
        border = "+" + "-" * (len(middle) - 2) + "+"
        logger.info(border)
        logger.info(middle)
        logger.info(border)
    if level == 1:
        logger.info("=" * 20 + " " + title + " " + "=" * 20)
    if level == 2:
        logger.info("-" * 20 + " " + title + " " + "-" * 20)
    if level == 3:
        logger.info(f"<<< {title} >>>")


def attr(name, text):
    print(f"[{name}] {text}")


logger.hr = hr
logger.attr = attr


class Percentage:
    def __init__(self, progress):
        self.progress = progress

    def __call__(self, *args, **kwargs):
        logger.info(f"Process: [ {self.progress}% ]")


class Progress:
    Start = Percentage(0)
    ShowDeployConfig = Percentage(10)

    AdbReplace = Percentage(80)
    AdbConnect = Percentage(95)

    # Must have a 100%
    Finish = Percentage(100)
