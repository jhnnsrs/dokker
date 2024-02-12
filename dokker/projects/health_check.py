from typing import Optional
from pydantic import BaseModel, Field
from ssl import SSLContext
import aiohttp
import ssl
import certifi
from dokker.types import LogHelper
import asyncio

class HealthCheck(BaseModel):
    name: str
    url: str
    service: str
    max_retries: int = 3
    timeout: int = 3
    error_with_logs: bool = True
    headers: Optional[dict] = Field(
        default_factory=lambda: {"Content-Type": "application/json"}
    )
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        description="SSL Context to use for the request",
    )

    async def acheck(self, helper: LogHelper, retry: int = 0) -> bool:
        """Check the health of a service.


        Parameters
        ----------
        logger : LogHelper
            The logger to use for the check.
        retry : int, optional
            The number of retries to use for the check, by default 0
        """
        try:
            async with aiohttp.ClientSession(
                headers=self.headers,
                connector=aiohttp.TCPConnector(ssl=self.ssl_context),
            ) as session:
                # get json from endpoint
                async with session.get(self.url) as resp:
                    assert resp.status == 200
                    text= await resp.text()
                    await helper.ainfo(f"Health check for {self.service} passed")
                    await helper.adebug(text)
                    return True
        except Exception as e:
            if retry < self.max_retries:
                await helper.awarning(f"Retrying health check for {self.service}")
                await asyncio.sleep(self.timeout)
                return await self.acheck(helper, retry=retry + 1)
            else:
                await helper.aerror(f"Failed to check health of {self.service}")
                if self.error_with_logs:
                    await helper.aerror(e)
                raise e

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True