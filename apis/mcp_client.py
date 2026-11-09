import asyncio
import json
import sys
import threading
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config.settings import settings


class MCPBankingClient:
    def __init__(self, command: str = sys.executable, args: Optional[List[str]] = None):
        self.params = StdioServerParameters(
            command=command,
            args=args or ["-m", "apis.mcp_banking_server"],
            cwd=str(settings.BASE_DIR),
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[ClientSession] = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._stop: Optional[asyncio.Event] = None
        self._startup_error: Optional[BaseException] = None
        self.tools: List[str] = []

    def _ensure_started(self, timeout: float = 20.0) -> None:
        with self._lock:
            if self._session is not None:
                return
            self._ready.clear()
            self._startup_error = None
            threading.Thread(target=self._thread_main, name="mcp-client", daemon=True).start()
            if not self._ready.wait(timeout):
                raise TimeoutError("MCP server did not start in time.")
            if self._startup_error:
                raise RuntimeError(f"MCP server failed to start: {self._startup_error}")

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as e:
            self._startup_error = e
        finally:
            self._session = None
            self._ready.set()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.tools = [t.name for t in (await session.list_tools()).tools]
                self._session = session
                self._ready.set()
                await self._stop.wait()

    def call_tool(self, name: str, arguments: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        self._ensure_started()
        fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, arguments), self._loop)
        try:
            result = fut.result(timeout=timeout)
        except TimeoutError:
            fut.cancel()
            raise
        if getattr(result, "is_error", False):
            text = " ".join(getattr(c, "text", "") for c in result.content)
            raise RuntimeError(f"MCP tool {name} failed: {text}")
        text = next((c.text for c in result.content if getattr(c, "text", None)), "{}")
        return json.loads(text)

    def close(self) -> None:
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)


mcp_banking_client = MCPBankingClient()
