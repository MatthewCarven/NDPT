"""An asyncio loop on its own thread, so a GUI can run sessions without freezing."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class LoopThread:
    """Runs an event loop on a daemon thread. The GUI submits sessions to it and
    hears back through listeners that post to the GUI thread (Qt signals)."""

    def __init__(self, name: str = "ndpt-loop") -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._main, name=name, daemon=True)

    def start(self) -> LoopThread:
        self._thread.start()
        return self

    def submit(self, coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        """Run `coro` on the loop; the returned future can be waited on from any thread."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call(self, fn: Callable[..., object], *args: object) -> None:
        """Call `fn(*args)` on the loop's thread, e.g. `call(session.stop)`."""
        self.loop.call_soon_threadsafe(fn, *args)

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread.is_alive():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout)

    def __enter__(self) -> LoopThread:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _main(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self.loop)
            for task in tasks:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            # Reverse-DNS lookups can sit in the default executor for seconds; don't wait them out.
            self.loop.run_until_complete(self.loop.shutdown_default_executor(timeout=1.0))
            self.loop.close()
