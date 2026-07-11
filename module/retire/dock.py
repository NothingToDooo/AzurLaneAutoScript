from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypedDict, Unpack

from module.base.button import Button, ButtonGrid, color_similar, get_color
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.equipment.equipment import Equipment
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.retire import assets as retire_assets
from module.ui.scroll import Scroll
from module.ui.setting import Setting
from module.ui.switch import Switch

if TYPE_CHECKING:
    from collections.abc import Callable

type DockFilterValue = str | list[str]
type DockCheck = Button | Callable[[], bool]

DOCK_SORTING = Switch("Dork_sorting")
DOCK_SORTING.add_state("Ascending", check_button=retire_assets.SORT_ASC, click_button=retire_assets.SORTING_CLICK)
DOCK_SORTING.add_state("Descending", check_button=retire_assets.SORT_DESC, click_button=retire_assets.SORTING_CLICK)

DOCK_FAVOURITE = Switch("Favourite_filter")
DOCK_FAVOURITE.add_state("on", check_button=retire_assets.COMMON_SHIP_FILTER_ENABLE)
DOCK_FAVOURITE.add_state("off", check_button=retire_assets.COMMON_SHIP_FILTER_DISABLE)

CARD_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 204), grid_shape=(7, 2), name="CARD"
)
CARD_RARITY_GRIDS = CARD_GRIDS.crop(area=(0, 0, 138, 5), name="RARITY")
CARD_LEVEL_GRIDS = CARD_GRIDS.crop(area=(77, 5, 138, 27), name="LEVEL")
CARD_EMOTION_GRIDS = CARD_GRIDS.crop(area=(23, 29, 48, 52), name="EMOTION")

DOCK_SCROLL = Scroll(retire_assets.DOCK_SCROLL, color=(247, 211, 66), name="DOCK_SCROLL")

OCR_DOCK_SELECTED = DigitCounter(retire_assets.DOCK_SELECTED, threshold=64, name="OCR_DOCK_SELECTED")
# 确认模板尚未随新版弹窗位置更新，先纵向放宽识别范围。
DOCK_FILTER_CONFIRM_OFFSET = (20, 60)


@dataclass(frozen=True, slots=True)
class DockFilterOptions:
    """船坞筛选值域。

    sort：rarity、level、total、join、intimacy、mood、stat。
    index：all、vanguard、main、dd、cl、ca、bb、cv、repair、ss、others、not_available。
    faction：all、eagle、royal、sakura、iron、dragon、sardegna、northern、iris、vichya、tulipa、pedreria、meta、tempesta、other、not_available。
    rarity：all、common、rare、elite、super_rare、ultra、not_available。
    extra：no_limit、has_skin、can_retrofit、enhanceable、can_limit_break、not_level_max、can_awaken、can_awaken_plus、special、oath_skin、unique_augment_module、wear_skin、oathed、not_available。
    """

    sort: DockFilterValue = "level"
    index: DockFilterValue = "all"
    faction: DockFilterValue = "all"
    rarity: DockFilterValue = "all"
    extra: DockFilterValue = "no_limit"
    wait_loading: bool = True


class DockFilterSettings(TypedDict, total=False):
    sort: DockFilterValue
    index: DockFilterValue
    faction: DockFilterValue
    rarity: DockFilterValue
    extra: DockFilterValue
    wait_loading: bool


def dock_filter_options(
    options: DockFilterOptions | None = None,
    settings: DockFilterSettings | None = None,
) -> DockFilterOptions:
    options = DockFilterOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class Dock(Equipment):
    def handle_dock_cards_loading(self, *, skip_first_screenshot: bool = True) -> None:
        # 这里不能用 confirm_timer，只能短暂等待卡片加载。
        timeout = Timer(1.2, count=1).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 船坞为空时可以立即退出。
            if self.appear(retire_assets.DOCK_EMPTY):
                logger.info("Dock empty")
                break
            # 否则固定等待 1.2 秒。
            if timeout.reached():
                break

    def dock_favourite_set(self, *, enable: bool = False, wait_loading: bool = True) -> None:
        if DOCK_FAVOURITE.set("on" if enable else "off", main=self) and wait_loading:
            self.handle_dock_cards_loading()

    def _dock_quit_check_func(self) -> bool:
        return not self.appear(retire_assets.DOCK_CHECK, offset=(20, 20))

    def dock_quit(self) -> None:
        self.ui_back(check_button=self._dock_quit_check_func, skip_first_screenshot=True)

    def dock_sort_method_dsc_set(self, *, enable: bool = True, wait_loading: bool = True) -> None:
        if DOCK_SORTING.set("Descending" if enable else "Ascending", main=self) and wait_loading:
            self.handle_dock_cards_loading()

    def dock_filter_enter(self) -> None:
        logger.info("Dock filter enter")
        self.interval_clear(retire_assets.DOCK_CHECK)
        for _ in self.loop():
            if self.appear(retire_assets.DOCK_FILTER_CONFIRM, offset=DOCK_FILTER_CONFIRM_OFFSET):
                break
            if self.appear(retire_assets.DOCK_CHECK, offset=(20, 20), interval=5):
                self.device.click(retire_assets.DOCK_FILTER)
                continue
            # 上一次退役留下的慢弹窗。
            if self.appear_then_click(retire_assets.EQUIP_CONFIRM, offset=(30, 30), interval=2):
                continue
            if self.appear_then_click(retire_assets.EQUIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.interval_clear(GET_ITEMS_1)
                continue
            # 获取物品弹窗。
            if self.appear(GET_ITEMS_1, offset=(30, 30), interval=2):
                self.device.click(retire_assets.GET_ITEMS_1_RETIREMENT_SAVE)
                continue

    def dock_filter_confirm(
        self,
        *,
        wait_loading: bool = True,
        skip_first_screenshot: bool = True,
    ) -> None:
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 有时筛选弹窗没有黑色模糊背景，会同时出现确认按钮和船坞检查点。
            if not self.appear(retire_assets.DOCK_FILTER_CONFIRM, offset=DOCK_FILTER_CONFIRM_OFFSET) and self.appear(
                retire_assets.DOCK_CHECK, offset=(20, 20)
            ):
                break
            if self.appear_then_click(retire_assets.DOCK_FILTER_CONFIRM, offset=DOCK_FILTER_CONFIRM_OFFSET, interval=3):
                continue

        if wait_loading:
            self.handle_dock_cards_loading()

    @cached_property
    def dock_filter(self) -> Setting:
        delta = (147 + 1 / 3, 57)
        button_shape = (139, 42)
        setting = Setting(name="DOCK", main=self)
        setting.add_setting(
            setting="sort",
            option_buttons=ButtonGrid(
                origin=(218, 36), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name="FILTER_SORT"
            ),
            # stat 多一格，当前无需额外适配。
            option_names=["rarity", "level", "total", "join", "intimacy", "mood", "stat"],
            option_default="level",
        )
        setting.add_setting(
            setting="index",
            option_buttons=ButtonGrid(
                origin=(218, 109), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name="FILTER_INDEX"
            ),
            option_names=[
                "all",
                "vanguard",
                "main",
                "dd",
                "cl",
                "ca",
                "bb",
                "cv",
                "repair",
                "ss",
                "others",
                "not_available",
                "not_available",
                "not_available",
            ],
            option_default="all",
        )
        setting.add_setting(
            setting="faction",
            option_buttons=ButtonGrid(
                origin=(218, 239), delta=delta, button_shape=button_shape, grid_shape=(7, 3), name="FILTER_FACTION"
            ),
            option_names=[
                "all",
                "eagle",
                "royal",
                "sakura",
                "iron",
                "dragon",
                "sardegna",
                "northern",
                "iris",
                "vichya",
                "tulipa",
                "pedreria",
                "meta",
                "tempesta",
                "other",
                "not_available",
                "not_available",
                "not_available",
                "not_available",
                "not_available",
                "not_available",
            ],
            option_default="all",
        )
        setting.add_setting(
            setting="rarity",
            option_buttons=ButtonGrid(
                origin=(218, 427), delta=delta, button_shape=button_shape, grid_shape=(7, 1), name="FILTER_RARITY"
            ),
            option_names=["all", "common", "rare", "elite", "super_rare", "ultra", "not_available"],
            option_default="all",
        )
        setting.add_setting(
            setting="extra",
            option_buttons=ButtonGrid(
                origin=(218, 499), delta=delta, button_shape=button_shape, grid_shape=(7, 2), name="FILTER_EXTRA"
            ),
            option_names=[
                "no_limit",
                "has_skin",
                "can_retrofit",
                "enhanceable",
                "can_limit_break",
                "not_level_max",
                "can_awaken",
                "can_awaken_plus",
                "special",
                "oath_skin",
                "unique_augment_module",
                "wear_skin",
                "oathed",
                "not_available",
            ],
            option_default="no_limit",
        )
        return setting

    def dock_filter_set(
        self,
        options: DockFilterOptions | None = None,
        **settings: Unpack[DockFilterSettings],
    ) -> None:
        """在船坞页应用 DockFilterOptions，settings 覆盖其中字段。"""
        options = dock_filter_options(options, settings)
        self.dock_filter_enter()
        self.dock_filter.set(
            sort=options.sort,
            index=options.index,
            faction=options.faction,
            rarity=options.rarity,
            extra=options.extra,
        )
        self.dock_filter_confirm(wait_loading=options.wait_loading)

    def dock_select_one(self, button: Button, *, skip_first_screenshot: bool = True) -> None:
        self.interval_clear(retire_assets.DOCK_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.dock_selected():
                break

            if self.appear(retire_assets.DOCK_CHECK, offset=(20, 20), interval=5):
                self.device.click(button)
                continue
            if self.handle_popup_confirm("DOCK_SELECT"):
                continue

    def dock_selected(self, *, skip_first_screenshot: bool = True) -> bool:
        """船坞计数为 1/1 时返回 True，0/1 时返回 False。"""
        current = 0
        timeout = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("Get dock_selected timeout, assume not selected")
                break

            current, _, total = OCR_DOCK_SELECTED.ocr_single(self.device.image)
            if total == 1:
                break

        return current > 0

    def dock_select_confirm(self, check_button: DockCheck, *, skip_first_screenshot: bool = True) -> None:
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_process_check_button(check_button):
                break

            if self.appear_then_click(retire_assets.SHIP_CONFIRM, offset=(200, 50), interval=5):
                continue
            if self.handle_popup_confirm("DOCK_SELECT_CONFIRM"):
                continue

    def dock_enter_first(
        self,
        *,
        non_npc: bool = True,
        skip_first_screenshot: bool = True,
    ) -> bool:
        """从船坞进入第一艘可用舰船的详情；non_npc 时跳过首格 NPC。

        船坞为空或只有一个 NPC 时返回 False。
        """
        logger.info("Dock enter first")
        self.interval_clear(retire_assets.DOCK_CHECK, interval=3)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(retire_assets.SHIP_DETAIL_CHECK, offset=(20, 20)):
                return True
            if self.appear(retire_assets.DOCK_EMPTY, offset=(20, 20)):
                logger.info("Dock empty")
                return False

            if self.appear(retire_assets.DOCK_CHECK, offset=(20, 20), interval=3):
                if non_npc:
                    # NPC 舰船不能进入常规详情。
                    if retire_assets.DOCK_FIRST_NPC.match_luma(self.device.image, offset=(20, 20)):
                        logger.info("First ship is NPC, select second")
                        button = CARD_GRIDS[(1, 0)]
                        # 检查第二格是否有舰船。
                        color = get_color(self.device.image, button.area)
                        if color_similar(color, (34, 34, 42)):
                            logger.info("Second ship empty, dock empty")
                            return False
                    else:
                        button = CARD_GRIDS[(0, 0)]
                else:
                    button = CARD_GRIDS[(0, 0)]
                self.device.click(button)
                continue
            if self.handle_game_tips():
                continue
        return False
