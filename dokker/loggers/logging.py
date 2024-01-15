from pydantic import BaseModel, Field
import logging


class LoggingContext:
    def __init__(self, logger: logging.Logger, status: str):
        self.logger = logger
        self.status = status

    def __aenter__(self):
        self.logger.log("INFO", f"Start... {self.status}")
        return self

    def __aexit__(self, exc_type, exc_val, exc_tb):
        self.logger.log("INFO", f"Done... {self.status}")
        pass


class Logger(BaseModel):
    """A logger that prints all logs to a logger"""

    logger: logging.Logger = Field(default_factory=lambda: logging.getLogger(__name__))
    log_level: int = logging.INFO

    def status(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        return LoggingContext(self.logger, log)

    def log(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """

        self.logger.log(self.log_level, log)

    class Config:
        """pydantic config class"""

        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
