from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.exception import ScriptError
from module.handler.assets import GET_MISSION
from module.logger import logger
from module.os.globe_operation import GlobeOperation
from module.os.globe_zone import ZoneManager
from module.os_handler import assets as os_assets
from module.ui.scroll import Scroll

SCROLL_STORAGE = Scroll(os_assets.STORATE_SCROLL, color=(247, 211, 66))
UNKNOWN_STORAGE_ITEM_TEMPLATE = "Unknown storage item: {item}"


class StorageHandler(GlobeOperation, ZoneManager):
    def is_in_storage(self):
        return self.appear(os_assets.STORAGE_CHECK, offset=(20, 20))

    def storage_enter(self):
        """
        Pages:
            in: is_in_map, STORAGE_ENTER
            out: STORAGE_CHECK
        """
        logger.info("Storage enter")
        for _ in self.loop():
            # End
            if self.is_in_storage():
                break

            if self.appear_then_click(os_assets.STORAGE_ENTER, offset=(200, 5), interval=3):
                continue
            # A game bug that AUTO_SEARCH_REWARD from the last cleared zone popups
            if self.appear_then_click(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
            if self.handle_map_event():
                continue

        self.handle_info_bar()

    def storage_quit(self):
        """
        Pages:
            in: STORAGE_CHECK
            out: is_in_map
        """
        logger.info("Storage quit")
        self.ui_back(os_assets.STORAGE_ENTER, offset=(200, 5), skip_first_screenshot=True)

    def _storage_item_use(self, button):
        """
        Args:
            button (Button): Item

        Pages:
            in: STORAGE_CHECK
            out: STORAGE_CHECK
        """
        success = False
        get_mission_counter = 0
        self.interval_clear(os_assets.STORAGE_CHECK)
        self.interval_clear(os_assets.STORAGE_USE)
        self.interval_clear(GET_ITEMS_1)
        self.interval_clear(GET_ITEMS_2)
        self.interval_clear(os_assets.GET_ADAPTABILITY)
        self.interval_clear(GET_MISSION)

        for _ in self.loop():
            # Accidentally clicked on an item, having popups for its info
            if self.appear(GET_MISSION, offset=True, interval=2):
                logger.info(f"_storage_item_use item info -> {GET_MISSION}")
                self.device.click(GET_MISSION)
                self.interval_reset(os_assets.STORAGE_CHECK)
                get_mission_counter += 1
                if get_mission_counter >= 3:
                    logger.warning("Possibly stuck on energy storage device, redetecting logger items.")
                    break
                continue
            # Item rewards
            if self.appear_then_click(os_assets.STORAGE_USE, offset=(180, 30), interval=5):
                self.interval_reset(os_assets.STORAGE_CHECK)
                continue
            if self.appear_then_click(GET_ITEMS_1, interval=5):
                self.interval_reset(os_assets.STORAGE_CHECK)
                success = True
                continue
            if self.appear_then_click(GET_ITEMS_2, interval=5):
                self.interval_reset(os_assets.STORAGE_CHECK)
                success = True
                continue
            if self.appear(os_assets.GET_ADAPTABILITY, offset=5, interval=2):
                self.device.click(os_assets.CLICK_SAFE_AREA)
                success = True
                continue
            # Use item
            if self.appear(os_assets.STORAGE_CHECK, offset=(20, 20), interval=5):
                self.device.click(button)
                continue

            # End
            if success and self.appear(os_assets.STORAGE_CHECK, offset=(20, 20)):
                break

    def storage_logger_use_all(self):
        """
        Pages:
            in: STORAGE_CHECK
            out: STORAGE_CHECK, scroll to bottom
        """
        logger.hr("Storage logger use all")
        for _ in self.loop():
            if SCROLL_STORAGE.appear(main=self):
                SCROLL_STORAGE.set_bottom(main=self, skip_first_screenshot=True)

            image = rgb2gray(self.device.image)
            items = os_assets.TEMPLATE_STORAGE_LOGGER.match_multi(image, similarity=0.5)
            logger.attr("Storage_logger", len(items))

            if len(items):
                self._storage_item_use(items[0])
                continue
            logger.info("All loggers in storage have been used")
            break

    def storage_sample_use_all(self):
        """
        Pages:
            in: STORAGE_CHECK
            out: STORAGE_CHECK, scroll to bottom
        """
        sample_types = [
            os_assets.TEMPLATE_STORAGE_OFFENSE,
            os_assets.TEMPLATE_STORAGE_SURVIVAL,
            os_assets.TEMPLATE_STORAGE_COMBAT,
            os_assets.TEMPLATE_STORAGE_QUALITY_OFFENSE,
            os_assets.TEMPLATE_STORAGE_QUALITY_SURVIVAL,
            os_assets.TEMPLATE_STORAGE_QUALITY_COMBAT,
        ]
        for sample_type in sample_types:
            for _ in self.loop():
                image = rgb2gray(self.device.image)
                items = sample_type.match_multi(image, similarity=0.75)
                logger.attr("Storage_sample", len(items))

                if len(items):
                    self._storage_item_use(items[0])
                else:
                    break
        logger.info("All samples in storage have been used")

    def tuning_sample_use(self):
        logger.hr("Turning sample use")
        self.storage_enter()
        self.storage_sample_use_all()
        self.storage_quit()

    def _storage_coordinate_checkout(self, button, types=("OBSCURE",)):
        """
        Args:
            button (Button): Item
            types (tuple[str]):

        Pages:
            in: STORAGE_CHECK
            out: is_in_map, in an obscure zone.
        """
        self.interval_clear([os_assets.STORAGE_CHECK, os_assets.STORAGE_COORDINATE_CHECKOUT])
        self.popup_interval_clear()
        for _ in self.loop():
            if self.appear(os_assets.STORAGE_CHECK, offset=(30, 30), interval=5):
                self.device.click(button)
                continue
            if self.appear_then_click(os_assets.STORAGE_COORDINATE_CHECKOUT, offset=(30, 30), interval=5):
                self.interval_reset(os_assets.STORAGE_CHECK)
                continue
            if self.handle_popup_confirm("STORAGE_CHECKOUT"):
                # Submarine popup
                continue

            # End
            if self.is_zone_pinned():
                break

        self.zone_type_select(types)
        self.globe_enter(zone=self.name_to_zone(72))

    @staticmethod
    def _storage_item_to_template(item):
        """
        Args:
            item (str): 'OBSCURE' or 'ABYSSAL'.

        Returns:
            Template:
        """
        if item == "OBSCURE":
            return os_assets.TEMPLATE_STORAGE_OBSCURE
        if item == "ABYSSAL":
            return os_assets.TEMPLATE_STORAGE_ABYSSAL
        message = UNKNOWN_STORAGE_ITEM_TEMPLATE.format(item=item)
        raise ScriptError(message)

    def storage_checkout_item(self, item):
        """
        Args:
            item (str): 'OBSCURE' or 'ABYSSAL'.

        Returns:
            bool: If checkout

        Pages:
            in: STORAGE_CHECK
            out: is_in_map, in an obscure/abyssal zone if checkout.
                 is_in_map, in previous zone if no more obscure/abyssal coordinates.
        """
        logger.hr(f"Storage checkout item {item}")
        if SCROLL_STORAGE.appear(main=self):
            SCROLL_STORAGE.set_top(main=self)

        confirm_timer = Timer(0.6, count=2).start()
        for _ in self.loop():
            image = rgb2gray(self.device.image)
            items = self._storage_item_to_template(item).match_multi(image, similarity=0.75)
            logger.attr(f"Storage_{item}", len(items))

            if len(items):
                self._storage_coordinate_checkout(items[0], types=(item,))
                return True
            if confirm_timer.reached():
                logger.info(f"No more {item} items in storage")
                self.storage_quit()
                return False
        return False

    def storage_get_next_item(self, item, use_logger=True):
        """
        Args:
            item (str): 'OBSCURE' or 'ABYSSAL'.
            use_logger: If use all loggers.

        Returns:
            bool: If checkout

        Pages:
            in: in_map
            out: is_in_map, in an obscure/abyssal zone if checkout.
                 is_in_map, in previous zone if no more obscure/abyssal coordinates.
        """
        logger.hr("OS get next obscure")
        self.storage_enter()
        if use_logger:
            self.storage_logger_use_all()

        return self.storage_checkout_item(item)
