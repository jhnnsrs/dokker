# %%
import typing as t
from typing import List, Optional

import pydantic
from pydantic import BaseModel
from pydantic.fields import Field


@t.runtime_checkable
class Effect(t.Protocol):

    def should_prompt(
        self, default: t.Optional[t.Any], values: t.Dict[str, t.Any], flags: t.List[str]
    ) -> bool: ...

    def validate_prompt(self, value: t.Any, values: t.Dict[str, t.Any]) -> t.Any: ...


class BaseEffect(BaseModel):
    kind: str 


class PromptEffect(BaseEffect):

    def validate_prompt(self, value, values):
        return value


class StaticPromptEffect(PromptEffect):
    kind = "static_prompt"
    promptable: bool = True

    def should_prompt(self, default, values, flags) -> bool:str

class PromptIfFlagCheckEffect(PromptEffect):
    kind = "prompt_if_flags_set"
    needed_flags: t.Set[str]

    def should_prompt(
        self, default: t.Optional[t.Any], values: t.Dict[str, t.Any], flags: t.List[str]
    ) -> bool:
        should = self.needed_flags.issubset(flags)
        return should

    @pydantic.validator("needed_flags", pre=True)
    def validate_needed_flags(cls, value):
        if isinstance(value, str):
            return set([value])
        if isinstance(value, list):
            return value


class PromptIfValuesSetEffect(BaseEffect):
    kind = "prompt_if_values_set"
    key: str
    value: Optional[t.Any] = True

    def should_prompt(
        self, default: t.Optional[t.Any], values: t.Dict[str, t.Any], flags: t.List[str]
    ) -> bool:
        if "." in self.key:
            first_key, *rest = self.key.split(".")
            item = values.get(first_key)
            for i in rest:
                item = getattr(item, i, None)
            return item == self.value
        else:
            return values.get(self.key) == self.value


def prompt_if_flags(needed_flags: List[str]):
    return PromptIfFlagCheckEffect(needed_flags=needed_flags)


def value_set(key: str, expected_value: t.Any = True):
    return PromptIfValuesSetEffect(key=key, value=expected_value)


class ValidateEffect(BaseModel):
    func: t.Callable[[t.Any, t.Dict[str, t.Any]], t.Any] = Field(exclude=True)

    def should_prompt(self, *args, **kwargs) -> bool:
        return True

    def validate_prompt(self, value: t.Any, values: t.Dict[str, t.Any]) -> t.Any:
        return self.func(value, values)


def always_prompt(values, value):
    return Effect(prompt=True)


def validate(func):
    return ValidateEffect(func=func)
