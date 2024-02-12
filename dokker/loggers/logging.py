from pydantic import BaseModel, Field
import logging
from rich import console


class LoggingHelper:
    def __init__(self, logger: logging.Logger, log_level: int,  status: str):
        self.logger = logger
        self.status = status
        self.log_level = log_level

    async def __aenter__(self):
        self.logger.log(self.log_level, f"Start... {self.status}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.logger.log(self.log_level, f"Done... {self.status}")
        pass

    async def alog(self, log: str) -> None:
        self.logger.log(self.log_level, f"{self.status} - {log}")

    async def ainfo(self, log: str):
        self.logger.log(self.log_level, f"{self.status} - {log}")

    async def aerror(self, log: str):
        self.logger.log(self.log_level, f"{self.status} - {log}")

    async def awarning(self, log: str):
        self.logger.log(self.log_level, f"{self.status} - {log}")

    async def adebug(self, log: str):
        self.logger.log(self.log_level, f"{self.status} - {log}")

   


class RichHelper:
    def __init__(self, logger: logging.Logger, log_level: int,  status: str):
        self.status = status
        self.log_level = log_level
        self.console = console.Console()

    async def __aenter__(self):
        self.context = self.console.status(f"{self.status}")
        self.context.__enter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.context.__exit__(exc_type, exc_val, exc_tb)
        pass

    async def alog(self, log: str) -> None:
        self.console.print(f"{log}")

    async def alog(self, log: str) -> None:
        self.console.print(f"{self.status} - {log}")

    async def ainfo(self, log: str):
        self.console.print(f"{self.status} - {log}")

    async def aerror(self, log: str):
        self.console.print(f"{self.status} - {log}")

    async def awarning(self, log: str):
        self.console.print(f"{self.status} - {log}")

    async def adebug(self, log: str):
        self.console.print(f"{self.status} - {log}")

class LoggingLogger(BaseModel):
    """A logger that prints all logs to a logger"""

    logger: logging.Logger = Field(default_factory=lambda: logging.getLogger(__name__))
    log_level: int = logging.INFO

    def status(self, status: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        return RichHelper(self.logger, self.log_level, status)
    



    class Config:
        """pydantic config class"""

        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
