from pydantic import BaseModel, Field


class VoidLogger(BaseModel):
    should_print: bool = True

    def on_pull(self, log: str):
        pass

    def on_up(self, log: str):
        pass

    def on_stop(self, log: str):
        pass

    def on_logs(self, log: str):
        pass

    def on_down(self, log: str):
        pass
