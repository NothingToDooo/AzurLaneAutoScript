from collections.abc import Mapping
from typing import TYPE_CHECKING

import onepush.core
import requests
import yaml
from onepush import get_notifier
from onepush.exceptions import OnePushException
from onepush.providers.custom import Custom
from requests import Response

from module.logger import logger

if TYPE_CHECKING:
    from onepush.core import Provider

onepush.core.log = logger


def _load_notify_config(raw_config: str) -> dict:
    config = {}
    for item in yaml.safe_load_all(raw_config):
        if item is None:
            continue
        if not isinstance(item, Mapping):
            raise TypeError(f"OnePush config item must be a mapping, got {type(item).__name__}")
        config.update(item)
    return config


def handle_notify(_config: str, **kwargs) -> bool:
    try:
        config = _load_notify_config(_config)
    except (TypeError, yaml.YAMLError) as e:
        logger.error(f"Fail to load onepush config, skip sending: {e}")
        return False
    try:
        provider_name: str = config.pop("provider", None)
        if provider_name is None:
            logger.info("No provider specified, skip sending")
            return False
        notifier: Provider = get_notifier(provider_name)
        required: list[str] = notifier.params["required"]
        config.update(kwargs)

        # pre check
        for key in required:
            if key not in config:
                logger.warning(f"Notifier {notifier.name} require param '{key}' but not provided")

        if isinstance(notifier, Custom):
            if "method" not in config or config["method"] == "post":
                config["datatype"] = "json"
            if "data" not in config or not isinstance(config["data"], dict):
                config["data"] = {}
            if "title" in kwargs:
                config["data"]["title"] = kwargs["title"]
            if "content" in kwargs:
                config["data"]["content"] = kwargs["content"]

        if provider_name.lower() == "gocqhttp":
            access_token = config.get("access_token")
            if access_token:
                config["token"] = access_token

        resp = notifier.notify(**config)
        if isinstance(resp, Response):
            if resp.status_code != 200:
                logger.warning("Push notify failed!")
                logger.warning(f"HTTP Code:{resp.status_code}")
                return False
            if provider_name.lower() == "gocqhttp":
                return_data: dict = resp.json()
                if return_data["status"] == "failed":
                    logger.warning("Push notify failed!")
                    logger.warning(f"Return message:{return_data['wording']}")
                    return False
    except OnePushException:
        logger.error("Push notify failed")
        return False
    except (KeyError, TypeError, ValueError, requests.exceptions.RequestException) as e:
        # don't show any exceptions because exceptions contain variable traceback
        logger.error(e)
        return False

    logger.info("Push notify success")
    return True
