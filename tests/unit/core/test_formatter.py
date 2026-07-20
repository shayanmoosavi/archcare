"""Unit tests for the core formatter port."""

from dataclasses import dataclass

from archcare.core.formatter import DefaultFormatter


@dataclass(frozen=True)
class MockTaskDetails:
    foo: str = "bar"
    count: int = 3
    visible: str = "shown"
    _internal: str = "hidden"


# ---------------------------------------------------------------------------
# DefaultFormatter
# ---------------------------------------------------------------------------


class TestDefaultFormatter:
    def test_formats_each_key_value_pair(self):
        output = "\n".join(DefaultFormatter().format(MockTaskDetails()))

        assert "foo: bar" in output
        assert "count: 3" in output

    def test_skips_keys_starting_with_underscore(self):
        output = "\n".join(DefaultFormatter().format(MockTaskDetails()))

        assert "hidden" not in output
        assert "shown" in output
