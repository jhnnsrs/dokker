from pydantic import BaseModel


class PrintLogger(BaseModel):
    """A logger that prints all logs to stdout"""

    should_print: bool = True

    def on_pull(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        print(log)

    def on_up(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        print(log)

    def on_stop(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        print(log)

    def on_logs(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        print(log)

    def on_down(self, log: str) -> None:
        """A method for logs

        Parameters
        ----------
        log : str
            The log to print
        """
        print(log)
