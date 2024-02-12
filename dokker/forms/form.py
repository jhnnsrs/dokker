import typing as t
from string import Template
from typing import  List,  Type, TypeVar

from pydantic import BaseModel
from pydantic.fields import  ModelField
from rich import get_console
from rich_click import confirm, prompt
from .effects import Effect

T = TypeVar("T", bound=BaseModel)

def prompt_list(
    inner_annotation: Type,
    field: ModelField,
    skip_fields=None,
    prompt_required: bool = True,
    level=0,
    prefix="|--",
    prefix_prepender="---",
    flags=None,
    **kwargs,
) -> t.Any:

    values = []

    list_prompt = field.field_info.extra.get(
        "prompt_text", f"Do you want to add another item to the list of {field.name}"
    )

    another_prompt = field.field_info.extra.get(
        "item_prompt_text", "Do you want to add another?"
    )

    if level == 0:
        prefixed_prelude = list_prompt
    else:
        prefixed_prelude = prefix_prepender * (level - 1) + prefix + list_prompt

    while confirm(prefixed_prelude, default=True) is True:
        if issubclass(inner_annotation, BaseModel):
            values.append(
                form(
                    inner_annotation,
                    level=level + 1,
                    skip_fields=skip_fields,
                    prompt_required=prompt_required,
                    prefix=prefix,
                    prefix_prepender=prefix_prepender,
                    flags=flags or [],
                    **kwargs,
                )
            )
        elif getattr(field, "_name", None) == "List":
            values.append(
                prompt_list(
                    field.annotation.__args__[0],
                    level=level + 1,
                    skip_fields=skip_fields,
                    prompt_required=prompt_required,
                    prefix=prefix,
                    prefix_prepender=prefix_prepender,
                    flags=flags or [],
                    **kwargs,
                )
            )

        elif getattr(field, "_name", None) == "Dict":
            values.append(
                prompt_dict(
                    field.annotation.__args__[1],
                    level=level + 1,
                    skip_fields=skip_fields,
                    prompt_required=prompt_required,
                    prefix=prefix,
                    prefix_prepender=prefix_prepender,
                    flags=flags or [],
                    **kwargs,
                )
            )
        else:
            if inner_annotation == bool:
                values.append = confirm(
                    text="The Item",
                )
            else:
                values.append(prompt(text="The Item"))

        prefixed_prelude = prefix_prepender * (level) + prefix + another_prompt

    return values


def prompt_dict(
    inner_annotation: Type,
    field: ModelField,
    skip_fields=None,
    prompt_required: bool = True,
    level=0,
    prefix="|--",
    prefix_prepender="---",
    flags=None,
    **kwargs,
) -> t.Any:

    values = {}

    list_prompt = field.field_info.extra.get(
        "prompt_text", f"Do you want to add another item to the list of {field.name}"
    )

    another_prompt = field.field_info.extra.get(
        "item_prompt_text", "Do you want to add another?"
    )

    key_prompt = field.field_info.extra.get(
        "key_prompt_text", "What should be the Key?"
    )

    key_factory = field.field_info.extra.get("key_default_factory", None)

    if level == 0:
        prefixed_prelude = list_prompt
    else:
        prefixed_prelude = prefix_prepender * (level - 1) + prefix + list_prompt

    while confirm(prefixed_prelude, default=True) is True:
        if key_factory:
            default = key_factory()
        else:
            default = None

        key = prompt(prefix_prepender * (level) + prefix + key_prompt, default=default)

        if issubclass(inner_annotation, BaseModel):
            values[key] = form(
                inner_annotation,
                level=level + 1,
                skip_fields=skip_fields,
                prompt_required=prompt_required,
                prefix=prefix,
                prefix_prepender=prefix_prepender,
                flags=flags or [],
                **kwargs,
            )

        elif getattr(field, "_name", None) == "List":
            values[key] = prompt_list(
                field.annotation.__args__[0],
                level=level + 1,
                skip_fields=skip_fields,
                prompt_required=prompt_required,
                prefix=prefix,
                prefix_prepender=prefix_prepender,
                flags=flags or [],
                **kwargs,
            )

        elif getattr(field, "_name", None) == "Dict":
            values[key] = prompt_dict(
                field.annotation.__args__[1],
                level=level + 1,
                skip_fields=skip_fields,
                prompt_required=prompt_required,
                prefix=prefix,
                prefix_prepender=prefix_prepender,
                flags=flags or [],
                **kwargs,
            )

        else:
            if inner_annotation == bool:
                values[key] = confirm(
                    text="The Item",
                )
            else:
                values[key] = prompt(text="The Item")

        prefixed_prelude = prefix_prepender * (level) + prefix + another_prompt

    return values


def form(
    cls: Type[T],
    skip_fields=None,
    prompt_required: bool = True,
    level=0,
    prefix="|--",
    prefix_prepender="---",
    flags=None,
    doc_is_prelude=True,
) -> T:
    assert issubclass(cls, BaseModel), "Needs to be a basemodel"
    values = {}

    console = get_console()

    prelude = getattr(
        cls,
        "_prelude",
        (
            cls.__doc__
            if doc_is_prelude and cls.__doc__
            else f"Prompting {cls.__name__}..."
        ),
    )

    if level == 0:
        prelude_prefix = ""
    else:
        prelude_prefix = prefix_prepender * (level - 1) + prefix

    prefixed_prelude = prelude_prefix + prelude

    field_prefix = prefix_prepender * level + prefix

    first_iteration_run = False

    for field in cls.__fields__.values():
        if not first_iteration_run:
            console.print(prefixed_prelude)
            first_iteration_run = True

        try:

            extras = field.field_info.extra

            value = (
                field.default_factory()
                if field.default_factory is not None
                else field.default
            )

            prompt_text = extras.get("prompt_text", field.name)
            forced_prompt = extras.get("prompt", value is None and field.required)

            effects: List[Effect] = extras.get("effects", [])

            if not isinstance(effects, list):
                effects = [effects]

            should_prompt = forced_prompt or (
                all(
                    effect.should_prompt(value, values, flags or [])
                    for effect in effects
                )
                if effects
                else False
            )

            if not should_prompt:
                try:
                    for effect in effects:
                        value = effect.validate_prompt(value, values)
                except Exception as e:
                    console.print(field_prefix + "Incorrect Value", str(e))
                    should_prompt = True

            while should_prompt:

                if (
                    field.annotation
                    and getattr(field.annotation, "_name", None) == "List"
                ):
                    value = prompt_list(
                        field.annotation.__args__[0],
                        field,
                        level=level + 1,
                        skip_fields=skip_fields,
                        prompt_required=prompt_required,
                        prefix=prefix,
                        prefix_prepender=prefix_prepender,
                        flags=flags or [],
                        doc_is_prelude=doc_is_prelude,
                    )

                elif (
                    field.annotation
                    and getattr(field.annotation, "_name", None) == "Dict"
                ):
                    value = prompt_dict(
                        field.annotation.__args__[1],
                        field,
                        level=level + 1,
                        skip_fields=skip_fields,
                        prompt_required=prompt_required,
                        prefix=prefix,
                        prefix_prepender=prefix_prepender,
                        flags=flags or [],
                        doc_is_prelude=doc_is_prelude,
                    )

                elif issubclass(field.type_, BaseModel):
                    value = form(
                        field.type_,
                        level=level + 1,
                        skip_fields=skip_fields,
                        prompt_required=prompt_required,
                        prefix=prefix,
                        prefix_prepender=prefix_prepender,
                        flags=flags or [],
                        doc_is_prelude=doc_is_prelude,
                    )

                else:
                    if field.type_ == bool:
                        value = confirm(
                            field_prefix + prompt_text,
                            default=value,
                            err=extras.get("err", False),
                            show_default=extras.get("show_default", True),
                        )
                    else:
                        set_confirmation_prompt = extras.get(
                            "confirmation_prompt", None
                        )
                        if set_confirmation_prompt:
                            if isinstance(set_confirmation_prompt, str):
                                confirmation_prompt = (
                                    field_prefix
                                    + prefix_prepender
                                    + set_confirmation_prompt
                                )
                            else:
                                confirmation_prompt = (
                                    field_prefix + prefix_prepender + "Confirm Input"
                                )
                        else:
                            confirmation_prompt = None

                        value = prompt(
                            text=field_prefix + prompt_text,
                            hide_input=extras.get("hide_input", False),
                            confirmation_prompt=confirmation_prompt,
                            type=extras.get("type", field.type_),
                            value_proc=extras.get("value_proc", None),
                            prompt_suffix=extras.get("prompt_suffix", ": "),
                            show_default=extras.get("show_default", True),
                            err=extras.get("err", False),
                            show_choices=extras.get("show_choices", True),
                            default=value,
                        )

                try:
                    for effect in effects:
                        value = effect.validate_prompt(value, values)

                    should_prompt = False
                except Exception as e:
                    console.print(field_prefix + "Incorrect Value", str(e))
                    should_prompt = True

            values[field.name] = value

        except Exception as e:
            raise Exception(
                f"Error when trying to prompt for field {field.name} of {cls.__name__}"
            ) from e

    happy = True
    _confirm = getattr(cls, "_confirm", None)
    if _confirm is not None:
        if isinstance(_confirm, str):
            t = Template(_confirm)
            happy = confirm(
                prelude_prefix + t.substitute(values),
                default=True,
            )
        else:
            happy = confirm(
                prelude_prefix + "Are you happy with the creation of this model",
                default=True,
            )
    if not happy:
        console.print(prelude_prefix + "Retrying")
        return form(
            cls,
            level=level,
            skip_fields=skip_fields,
            prompt_required=prompt_required,
            prefix=prefix,
            prefix_prepender=prefix_prepender,
            flags=flags,
        )

    return cls(**values)