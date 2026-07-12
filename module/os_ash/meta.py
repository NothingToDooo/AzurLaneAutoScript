import re
from enum import Enum
from typing import TYPE_CHECKING, Literal

from module.base.button import Button
from module.base.timer import Timer
from module.combat.assets import BATTLE_PREPARATION
from module.logger import logger
from module.meta_reward.meta_reward import MetaReward
from module.ocr.ocr import Digit, DigitCounter
from module.os_ash import assets as ash_assets
from module.os_ash.ash import AshCombat
from module.os_handler.map_event import MapEventHandler
from module.ui.assets import BACK_ARROW
from module.ui.page import page_reward
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.type_alias import Area
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

type MetaCategory = Literal["beacon", "dossier", "undefined"]


class MetaState(Enum):
    INIT = "no meta begin"
    ATTACKING = "a meta under attack"
    COMPLETE = "reward to be collected"
    UNDEFINED = "a undefined page"


OCR_BEACON_TIER = Digit(ash_assets.BEACON_TIER, name="OCR_ASH_TIER")
OCR_META_DAMAGE = Digit(ash_assets.META_DAMAGE, name="OCR_META_DAMAGE")


class MetaDigitCounter(DigitCounter):
    @staticmethod
    def normalize_text(result: str) -> str:
        result = DigitCounter.normalize_text(result)

        # 00/200 -> 100/200
        if result.startswith("00/"):
            result = "100/" + result[3:]

        # 23 -> 2/3
        if re.match(r"^[0123]3$", result):
            result = f"{result[0]}/{result[1]}"

        # 1/40/1400 -> 140/1400
        for suffix in ["/1400", "/200"]:
            if result.endswith(suffix):
                point = result[: -len(suffix)]
                point = point.replace("/", "")
                result = point + suffix

        return result


class Meta(UI, MapEventHandler):
    def digit_ocr_point_and_check(self, button: Button | Area, check_number: int) -> bool:
        if isinstance(button, Button):
            region = button
        else:
            if len(button) != 4:
                message = "META point OCR area must contain four coordinates"
                raise ValueError(message)
            region = (button[0], button[1], button[2], button[3])
        point_ocr = MetaDigitCounter(region, letter=(235, 235, 235), threshold=160, name="POINT_OCR")
        point, _, _ = point_ocr.ocr(self.device.image)
        return point >= check_number

    def handle_map_event(self) -> str:
        event = super().handle_map_event()
        if event:
            return event
        if self.appear_then_click(ash_assets.META_AUTO_CONFIRM, offset=(20, 20), interval=2):
            logger.info("Find auto attack complete")
            return "meta_auto_confirm"
        if self.appear(ash_assets.HELP_CONFIRM, offset=(30, 30), interval=2):
            logger.info("Accidentally click HELP_ENTER")
            self.device.click(BACK_ARROW)
            return "help_confirm"
        if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
            logger.info("Wrong click into battle preparation page")
            self.device.click(BACK_ARROW)
            return "battle_preparation"
        if self.handle_popup_cancel("META"):
            return "meta_popup_cancel"
        clicked = self.appear_then_click(ash_assets.META_ENTRANCE, offset=(20, 300), interval=2)
        return "meta_entrance" if clicked else ""


class OpsiAshBeacon(Meta):
    def __init__(
        self,
        config: AzurLaneConfig | str,
        device: Device | str | None = None,
        task: str | None = None,
    ) -> None:
        self._meta_receive: list[MetaCategory] = []
        self._meta_category: MetaCategory = "undefined"
        super().__init__(config, device=device, task=task)

    def _handle_attacking_meta_state(self) -> None:
        if not self._pre_attack():
            return
        if self._satisfy_attack_condition():
            self._make_an_attack()

    def _set_completed_meta_category(self) -> None:
        if self.appear(ash_assets.BEACON_LIST, offset=(20, 20)):
            self._meta_category = "beacon"
        elif self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20)):
            self._meta_category = "dossier"

    def _handle_completed_meta_state(self) -> None:
        self._set_completed_meta_category()
        self._handle_ash_beacon_reward()
        if self._meta_category not in self._meta_receive:
            self._meta_receive.append(self._meta_category)
        self.config.check_task_switch()

    def _attack_meta(self, *, skip_first_screenshot: bool = True) -> None:
        """处理 META 攻击事件，页面保持在 META。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_map_event():
                continue
            state = self._get_state()
            logger.info("Meta state:" + state.name)
            if state == MetaState.UNDEFINED:
                continue
            if state == MetaState.INIT:
                if not self._begin_meta():
                    break
                continue
            if state == MetaState.ATTACKING:
                self._handle_attacking_meta_state()
                continue
            if state == MetaState.COMPLETE:
                self._handle_completed_meta_state()
                continue

    def _make_an_attack(self) -> None:
        """从 ASH_START 发起 META 战斗，结束于 META、ASH_START 或奖励页。"""
        logger.hr("Begin meta combat", level=2)

        def expected_end() -> bool:
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                logger.info("Wrong click into battle preparation page")
                self.device.click(BACK_ARROW)
                return False
            if self.appear(ash_assets.HELP_CONFIRM, offset=(30, 30), interval=3):
                logger.info("Wrong click into HELP_CONFIRM")
                self.device.click(ash_assets.HELP_ENTER)
                return False
            if self._in_meta_page():
                logger.info("Meta combat finished and in correct page.")
                return True

            return False

        combat = AshCombat(config=self.config, device=self.device)
        combat.combat(expected_end=expected_end, emotion_reduce=False)

    def _handle_ash_beacon_reward(self, *, skip_first_screenshot: bool = True) -> None:
        """从奖励页领取 META 奖励，结束于 META 页面。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.appear(ash_assets.BEACON_REWARD, offset=(30, 30)) and self._in_meta_page():
                break

            if self.appear_then_click(ash_assets.BEACON_REWARD, offset=(30, 30), interval=2):
                logger.info("Reap meta rewards")
                continue
            if self.handle_map_event():
                continue
            # 误入主页面时返回奖励页。
            if self.ui_main_appear_then_click(page_reward, interval=2):
                continue
            if self.appear(ash_assets.META_ENTRANCE, offset=(20, 300), interval=2):
                continue

    def _satisfy_attack_condition(self) -> bool:
        """
        检查当前 META 是否可以攻击。

        信标：
            启用 OneHitMode 且已经攻击过时，不允许继续攻击。
        档案：
            启用自动攻击且正在自动攻击时，不允许手动攻击。
        """
        if self.appear(ash_assets.BEACON_LIST, offset=(20, 20)) and self.config.OpsiAshBeacon_OneHitMode:
            damage = self._get_meta_damage()
            if damage > 0:
                logger.info("Enable OneHitMode and meta damage is " + str(damage) + ", check after 30 minutes")
                self.config.task_delay(minute=30)
                self.config.task_stop()
        if self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20)) and self.appear(
            ash_assets.META_AUTO_ATTACKING, offset=(20, 20)
        ):
            logger.info("This meta is auto attacking, check after 15 minutes")
            self.config.task_delay(minute=15)
            self.config.task_stop()
        return True

    def _get_meta_damage(self) -> int:
        self._ensure_meta_inner_page_damage()
        return OCR_META_DAMAGE.ocr_single(self.device.image)

    def _ensure_meta_inner_page_damage(self, *, skip_first_screenshot: bool = True) -> None:
        """从 META 详情切到伤害页；调用前须位于 META 或 ASH_START。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.match_template_color(ash_assets.META_INNER_PAGE_DAMAGE, offset=(20, 20)):
                logger.info("Already in meta damage page")
                break
            if self.match_template_color(ash_assets.META_INNER_PAGE_NOT_DAMAGE, offset=(20, 20)):
                logger.info("In meta details page, should switch to damage page")
                self.appear_then_click(ash_assets.META_INNER_PAGE_NOT_DAMAGE, offset=(20, 20), interval=2)
                continue

    def _pre_attack(self) -> bool:
        """攻击前请求信标支援；档案仅在国服和英语服启用自动攻击。"""
        if self.appear(ash_assets.BEACON_LIST, offset=(20, 20)):
            needs_assist = self.config.OpsiAshBeacon_OneHitMode or self.config.OpsiAshBeacon_RequestAssist
            return not needs_assist or self._ask_for_help()
        if self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20)):
            if self.config.OpsiAshBeacon_DossierAutoAttackMode and self.appear(
                ash_assets.META_AUTO_ATTACK_START, offset=(5, 5)
            ):
                return self._dossier_auto_attack()
            return True
        return False

    def _ask_for_help(self) -> bool:
        """在 META 页请求三类支援；请求后目标已被击杀时返回 False。"""
        self._enter_help_page()
        self._send_help_requests()
        return self._confirm_help_request()

    def _enter_help_page(self) -> None:
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(ash_assets.HELP_CONFIRM, offset=(20, 20)):
                break
            if self.appear_then_click(ash_assets.HELP_ENTER, offset=(20, 20), interval=3):
                continue
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue

    def _send_help_requests(self) -> None:
        # 简单点击即可，漏点几次也不影响最终确认。
        self.device.click(ash_assets.HELP_3)
        self.device.sleep((0.1, 0.3))
        self.device.click(ash_assets.HELP_2)
        self.device.sleep((0.1, 0.3))
        self.device.click(ash_assets.HELP_1)

    def _confirm_help_request(self) -> bool:
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 有时支援弹窗没有黑色模糊背景，HELP_CONFIRM 和 HELP_ENTER 会同时出现。
            if not self.appear(ash_assets.HELP_CONFIRM, offset=(30, 30)):
                if self.appear(ash_assets.HELP_ENTER, offset=(30, 30)):
                    return True
                if self.appear(ash_assets.BEACON_REWARD, offset=(30, 30)):
                    logger.info("META finished just after calling assist, ignore meta assist")
                    return False
            if self.appear_then_click(ash_assets.HELP_CONFIRM, offset=(30, 30), interval=3):
                continue
        return False

    def _dossier_auto_attack(self) -> bool:
        """在尚未自动攻击的 META 页面启动档案自动攻击，并返回是否成功。"""
        timeout = Timer(10, count=20).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(ash_assets.META_AUTO_ATTACKING, offset=(5, 5)):
                return True
            if timeout.reached():
                logger.warning("Run _dossier_auto_attack timeout, probably because META_AUTO_ATTACK_START was missing")
                return False
            if self.appear(ash_assets.BEACON_REWARD, offset=(30, 30)):
                return False

            if self.appear_then_click(ash_assets.META_AUTO_ATTACK_CONFIRM, offset=(5, 5), interval=3):
                continue
            if self.appear_then_click(ash_assets.META_AUTO_ATTACK_START, offset=(5, 5), interval=3):
                continue
            # 误入战斗准备页时返回。
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue
        return False

    def _begin_meta_from_main_page(self) -> bool | None:
        if not self.appear(ash_assets.ASH_SHOWDOWN, offset=(30, 30), interval=2):
            return None
        if self._check_beacon_point():
            self.device.click(ash_assets.META_MAIN_BEACON_ENTRANCE)
            logger.info("Select beacon entrance into")
            return True
        if self.config.OpsiAshBeacon_AttackMode == "current_dossier" and self._check_dossier_point():
            if self.appear_then_click(ash_assets.META_MAIN_DOSSIER_ENTRANCE, offset=(20, 20), interval=2):
                logger.info("Select dossier entrance into")
                return True
            logger.info("None dossier has been selected")
        return False

    def _begin_meta_from_beacon_page(self) -> bool | None:
        if not self.appear(ash_assets.BEACON_LIST, offset=(20, 20), interval=2):
            return None
        if self._check_beacon_point():
            self.device.click(ash_assets.META_BEGIN_ENTRANCE)
            logger.info("Begin a beacon")
        return True

    def _begin_meta_from_dossier_page(self) -> bool | None:
        if not self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20), interval=2):
            return None
        if self.config.OpsiAshBeacon_AttackMode == "current_dossier" and self._check_dossier_point():
            if self.appear_then_click(ash_assets.META_BEGIN_ENTRANCE, offset=(20, 20), interval=2):
                logger.info("Begin a dossier")
                return True
            logger.info("None dossier has been selected")
        self.appear_then_click(ash_assets.ASH_QUIT, offset=(10, 10), interval=2)
        return True

    def _begin_meta(self) -> bool:
        """根据当前 META 页面选择或开始一个目标。

        META 主页会按配置进入信标或档案；信标页和档案页会尝试开始目标，
        没有可用目标时回到 META 主页或结束任务。
        """
        for handler in (
            self._begin_meta_from_main_page,
            self._begin_meta_from_beacon_page,
            self._begin_meta_from_dossier_page,
        ):
            result = handler()
            if result is not None:
                return result
        return True

    def _check_beacon_point(self) -> bool:
        if self.appear(ash_assets.META_BEACON_FLAG, offset=(180, 20)):
            ash_assets.META_BEACON_DATA.load_offset(ash_assets.META_BEACON_FLAG)
            return self.digit_ocr_point_and_check(ash_assets.META_BEACON_DATA.button, 100)
        return False

    def _check_dossier_point(self) -> bool:
        if self.appear(ash_assets.META_DOSSIER_FLAG, offset=(180, 20)):
            ash_assets.META_DOSSIER_DATA.load_offset(ash_assets.META_DOSSIER_FLAG)
            return self.digit_ocr_point_and_check(ash_assets.META_DOSSIER_DATA.button, 100)
        return False

    def _get_state(self) -> MetaState:
        if not self._in_meta_page():
            return MetaState.UNDEFINED
        if self.appear(ash_assets.BEACON_LIST, offset=(20, 20)) or self.appear(
            ash_assets.DOSSIER_LIST, offset=(20, 20)
        ):
            if self.appear(ash_assets.HELP_ENTER, offset=(30, 30)):
                return MetaState.ATTACKING
            if self.appear(ash_assets.BEACON_REWARD, offset=(20, 20)):
                return MetaState.COMPLETE
            return MetaState.INIT
        if self.appear(ash_assets.ASH_SHOWDOWN, offset=(30, 30)):
            return MetaState.INIT
        return MetaState.UNDEFINED

    def _in_meta_page(self) -> bool:
        return (
            self.appear(ash_assets.ASH_SHOWDOWN, offset=(30, 30))
            or self.appear(ash_assets.BEACON_LIST, offset=(20, 20))
            or self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20))
        )

    def _ensure_meta_page(self, *, skip_first_screenshot: bool = True) -> bool:
        logger.info("Ensure beacon attack page")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._in_meta_page():
                logger.info("In meta page")
                return True
            if self.handle_map_event():
                continue
            if self.appear_then_click(ash_assets.META_ENTRANCE, offset=(20, 300), interval=2):
                continue
        return False

    def ensure_dossier_page(self, *, skip_first_screenshot: bool = True) -> bool:
        self.ui_ensure(page_reward)
        self._ensure_meta_page()
        logger.info("Ensure dossier meta page")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20)):
                logger.info("In dossier page")
                return True
            if self.handle_map_event():
                continue
            if self.appear(ash_assets.ASH_SHOWDOWN, offset=(30, 30)):
                self.device.click(ash_assets.META_MAIN_DOSSIER_ENTRANCE)
                continue
        return False

    def _begin_beacon(self) -> None:
        logger.hr("Meta Beacon Attack")
        self._ensure_meta_page()
        self._attack_meta()

    def run(self) -> None:
        self.ui_ensure(page_reward)
        self._begin_beacon()

        with self.config.multi_set():
            for meta in self._meta_receive:
                MetaReward(self.config, self.device).run(category=meta)
            self._meta_receive = []
            self.config.task_delay(server_update=True)


class AshBeaconAssist(Meta):
    def _attack_meta_assist(self, *, skip_first_screenshot: bool = True) -> bool:
        timeout = Timer(3, count=9).start()
        appeared = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not appeared and timeout.reached():
                logger.info("No meta beacon found, delay task OpsiAshAssist")
                break

            if self.handle_map_event():
                continue
            if self.appear(ash_assets.ASH_START, offset=(20, 20)):
                appeared = True
                remain_times = self.digit_ocr_point_and_check(ash_assets.BEACON_REMAIN, 1)
                if remain_times:
                    self._ensure_meta_level()
                    self._make_an_attack()
                else:
                    logger.info("No enough assist times, complete")
                    break

        return appeared

    def _make_an_attack(self) -> None:
        """在 META 支援页完成一次支援战斗，结束后仍在支援页。"""
        logger.hr("Begin meta assist combat", level=2)

        def expected_end() -> bool:
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                logger.info("Wrong click into battle preparation page")
                self.device.click(BACK_ARROW)
                return False
            # 支援结束后游戏可能跳到未完成的己方信标，需要切回支援页。
            if self.appear_then_click(ash_assets.BEACON_LIST, offset=(-20, -5, 300, 5), interval=2):
                return False
            if self.appear(ash_assets.ASH_SHOWDOWN, offset=(30, 30), interval=2):
                logger.info("Meta combat finished at ASH_SHOWDOWN.")
                self.device.click(ash_assets.META_MAIN_BEACON_ENTRANCE)
            if self._in_meta_assist_page():
                logger.info("Meta combat finished and in correct page.")
                return True

            return False

        combat = AshCombat(config=self.config, device=self.device)
        combat.combat(expected_end=expected_end, emotion_reduce=False)

    def _ensure_meta_level(self) -> None:
        """等待信标等级加载后选择满足配置等级的目标。"""
        # 刚进入信标列表时等级不会立即显示。
        tier = self.config.OpsiAshAssist_Tier
        logger.info("Begin find a level " + str(tier) + " meta")
        for n in range(10):
            if self.image_color_count(ash_assets.BEACON_TIER, color=(0, 0, 0), threshold=221, count=50):
                break

            self.device.screenshot()
            if n >= 9:
                logger.warning("Waiting for beacon tier timeout")
        current = -1
        for _ in range(5):
            current = OCR_BEACON_TIER.ocr_single(self.device.image)
            if current >= tier:
                break
            self.device.click(ash_assets.BEACON_NEXT)
            self.device.sleep((0.3, 0.5))
            self.device.screenshot()
        if current < tier:
            logger.info(f"Tier {tier} beacon not found after 5 trial, use current beacon")
        logger.info("Find a beacon in level:" + str(current))

    def _in_meta_assist_page(self) -> bool:
        return self.appear(ash_assets.BEACON_MY, offset=(20, 20))

    def _ensure_meta_assist_page(self, *, skip_first_screenshot: bool = True) -> bool:
        logger.info("Ensure beacon assist page")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._in_meta_assist_page():
                logger.info("In beacon assist page")
                return True
            if self.handle_map_event():
                continue
            if self.appear_then_click(ash_assets.META_ENTRANCE, offset=(20, 300), interval=2):
                continue
            if self.appear(ash_assets.ASH_SHOWDOWN, offset=(20, 20), interval=2):
                self.device.click(ash_assets.META_MAIN_BEACON_ENTRANCE)
                logger.info("In meta page main")
                continue
            if self.appear_then_click(ash_assets.BEACON_LIST, offset=(300, 20), interval=2):
                continue
            if self.appear_then_click(ash_assets.DOSSIER_LIST, offset=(20, 20), interval=2):
                logger.info("In meta page dossier")
                continue
        return False

    def _begin_meta_assist(self) -> bool:
        logger.hr("Meta Beacon Assist")
        self._ensure_meta_assist_page()
        return self._attack_meta_assist(skip_first_screenshot=False)

    def run(self) -> None:
        self.ui_ensure(page_reward)

        if self._begin_meta_assist():
            MetaReward(self.config, self.device).run()
            self.config.task_delay(server_update=True)
        else:
            self.config.task_delay(minute=(10, 20))
