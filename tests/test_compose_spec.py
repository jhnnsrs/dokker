"""Unit tests for ``ComposeSpec`` parsing and lookups.

The spec is how callers discover where a service is reachable. When a lookup
fails it should raise a specific, typed dokker error with an actionable message
(what was asked for, and what is actually available).
"""

import pytest

from dokker.compose_spec import ComposeSpec
from dokker.errors import (
    LabelNotFoundError,
    PortNotFoundError,
    ServiceNotFoundError,
)


def _spec() -> ComposeSpec:
    return ComposeSpec(
        services={
            "web": {
                "image": "nginx",
                "ports": [{"target": 80, "published": 8080}],
                "labels": {"role": "frontend"},
            },
            "db": {"image": "postgres"},
        }
    )


def test_find_service_by_name():
    service = _spec().find_service("web")
    assert service.image == "nginx"


def test_find_service_default_returns_first():
    service = _spec().find_service()
    assert service.image is not None


def test_find_missing_service_raises_with_available_names():
    with pytest.raises(ServiceNotFoundError) as excinfo:
        _spec().find_service("does-not-exist")
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "web" in message and "db" in message


def test_find_service_on_empty_spec_raises():
    with pytest.raises(ServiceNotFoundError):
        ComposeSpec(services={}).find_service("web")


def test_get_port_for_internal():
    port = _spec().find_service("web").get_port_for_internal(80)
    assert port.published == 8080


def test_get_port_for_internal_missing_lists_available_ports():
    with pytest.raises(PortNotFoundError) as excinfo:
        _spec().find_service("web").get_port_for_internal(443)
    message = str(excinfo.value)
    assert "443" in message
    assert "80" in message


def test_get_port_for_internal_no_ports():
    with pytest.raises(PortNotFoundError):
        _spec().find_service("db").get_port_for_internal(80)


def test_get_label():
    assert _spec().find_service("web").get_label("role") == "frontend"


def test_get_label_missing_lists_available_labels():
    with pytest.raises(LabelNotFoundError) as excinfo:
        _spec().find_service("web").get_label("missing")
    assert "role" in str(excinfo.value)


def test_get_label_no_labels():
    with pytest.raises(LabelNotFoundError):
        _spec().find_service("db").get_label("role")
