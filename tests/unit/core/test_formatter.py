"""Unit tests for the core formatter port."""

from archcare.core.formatter import DefaultFormatter

# ---------------------------------------------------------------------------
# DefaultFormatter
# ---------------------------------------------------------------------------


class TestDefaultFormatter:
    def test_formats_each_key_value_pair(self):
        output = "\n".join(DefaultFormatter().format({"foo": "bar", "count": 3}))

        assert "foo: bar" in output
        assert "count: 3" in output

    def test_skips_keys_starting_with_underscore(self):
        output = "\n".join(
            DefaultFormatter().format({"_internal": "hidden", "visible": "shown"})
        )

        assert "hidden" not in output
        assert "shown" in output
