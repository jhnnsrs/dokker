from pydantic import BaseModel

LogTuple = tuple[str, str]


class VoidLogger(BaseModel):
    """A logger that omits all logs"""

    def on_pull(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """

        pass

    def on_up(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass

    def on_stop(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass

    def on_logs(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass

    def on_down(self, log: LogTuple) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass
