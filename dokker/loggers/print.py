from pydantic import BaseModel, ConfigDict
from typing import Callable

LogTuple = tuple[str, str]


class PrintLogger(BaseModel):
    """A logger that prints all logs to stdout"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    should_print: bool = True
    print_function: Callable[[LogTuple], None] = print

    def on_pull(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_up(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_stop(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_logs(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)

    def on_down(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        self.print_function(log)
