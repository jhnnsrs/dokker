from pydantic import BaseModel


class VoidLogger(BaseModel):
    """A logger that omits all logs"""

    should_print: bool = True

    def on_pull(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """

        pass

    def on_up(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass

    def on_stop(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass

    def on_logs(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass

    def on_down(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        pass
