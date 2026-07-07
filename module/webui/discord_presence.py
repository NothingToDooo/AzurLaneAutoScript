import asyncio
import time

from pypresence import AioPresence


class DiscordPresence:
    def __init__(self) -> None:
        self.client: AioPresence | None = None
        self.task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        assert self.client is not None
        await self.client.connect()
        await self.client.update(state="Alas is playing Azurlane", start=time.time(), large_image="alas")

    def init(self) -> None:
        self.client = AioPresence("929437173764223057")
        self.task = asyncio.create_task(self.run())

    def close(self) -> None:
        client = self.client
        task = self.task
        try:
            if client is not None:
                client.send_data(2, {"v": 1, "client_id": client.client_id})
                client.sock_writer.close()
        finally:
            if task is not None:
                task.cancel()
            self.client = None
            self.task = None


DISCORD_PRESENCE = DiscordPresence()


def init_discord_rpc() -> None:
    DISCORD_PRESENCE.init()


def close_discord_rpc() -> None:
    DISCORD_PRESENCE.close()
