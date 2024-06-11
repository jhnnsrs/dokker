from pydantic import BaseModel, Field
import logging


class Logger(BaseModel):
    logger: logging.Logger = Field(default_factory=lambda: logging.getLogger(__name__))
    log_level: int = logging.DEBUG

    def on_pull(self, log: str):
        self.logger.log(self.log_level, log)

    def on_up(self, log: str):
        self.logger.log(self.log_level, log)

    def on_stop(self, log: str):
        self.logger.log(self.log_level, log)

    def on_logs(self, log: str):
        self.logger.log(self.log_level, log)

    def on_down(self, log: str):
        self.logger.log(self.log_level, log)

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
