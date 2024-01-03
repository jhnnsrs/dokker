from pydantic import BaseModel, Field
import logging


class Logger(BaseModel):
    """ A logger that prints all logs to a logger"""
    logger: logging.Logger = Field(default_factory=lambda: logging.getLogger(__name__))
    log_level: int = logging.INFO

    def on_pull(self, log: str)->None:
        """ A method for logs 
        
        Parameters
        ----------
        log : str
            The log to print
        """
        self.logger.log(self.log_level, log)

    def on_up(self, log: str)->None:
        """ A method for logs 
        
        Parameters
        ----------
        log : str
            The log to print
        """
        self.logger.log(self.log_level, log)

    def on_stop(self, log: str)->None:
        """ A method for logs 
        
        Parameters
        ----------
        log : str
            The log to print
        """
        self.logger.log(self.log_level, log)

    def on_logs(self, log: str)->None:
        """ A method for logs 
        
        Parameters
        ----------
        log : str
            The log to print
        """
        self.logger.log(self.log_level, log)

    def on_down(self, log: str)->None:
        """ A method for logs 
        
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
