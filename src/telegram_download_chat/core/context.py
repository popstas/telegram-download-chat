import inspect


class DownloaderContext:
    """Async context manager for :class:`TelegramChatDownloader`."""

    def __init__(
        self, downloader: "TelegramChatDownloader", *, cli: bool = False
    ) -> None:
        self.downloader = downloader
        self.cli = cli

    async def __aenter__(self) -> "TelegramChatDownloader":
        await self.downloader.connect(cli=self.cli)
        return self.downloader

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.downloader.close()
        cleanup = self.downloader.cleanup_stop_file
        if inspect.iscoroutinefunction(cleanup):
            await cleanup()
        else:
            cleanup()

    def stop(self) -> None:
        self.downloader.stop()
