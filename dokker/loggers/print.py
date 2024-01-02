from pydantic import BaseModel, Field


class PrintLogger(BaseModel):
    should_print: bool = True

    def on_pull(self, log: str):
        print(log)

    def on_up(self, log: str):
        print(log)

    def on_stop(self, log: str):
        print(log)

    def on_logs(self, log: str):
        print(log)

    def on_down(self, log: str):
        print(log)
