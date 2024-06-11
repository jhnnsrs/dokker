from pydantic import BaseModel
from typing import Callable


class PrintLogger(BaseModel):
    """A logger that prints all logs to stdout"""

    should_print: bool = True
    print_function: Callable[[str], None] = print

    def on_pull(self, log: tuple[str, str]) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_up(self, log: tuple[str, str]) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_stop(self, log: tuple[str, str]) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_logs(self, log: tuple[str, str]) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_down(self, log: tuple[str, str]) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    class Config:
        arbitrary_types_allowed = True
