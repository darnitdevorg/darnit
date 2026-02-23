"""Tests for TemplateConfig validation (content vs file mutual exclusivity)."""

import pytest
from pydantic import ValidationError

from darnit.config.framework_schema import TemplateConfig


class TestTemplateConfigValidation:
    """TemplateConfig must have exactly one of content or file."""

    def test_content_only_is_valid(self):
        t = TemplateConfig(content="# Hello")
        assert t.content == "# Hello"
        assert t.file is None

    def test_file_only_is_valid(self):
        t = TemplateConfig(file="templates/hello.tmpl")
        assert t.file == "templates/hello.tmpl"
        assert t.content is None

    def test_both_set_raises(self):
        with pytest.raises(ValidationError, match="not both"):
            TemplateConfig(content="# Hello", file="templates/hello.tmpl")

    def test_neither_set_raises(self):
        with pytest.raises(ValidationError, match="must have either"):
            TemplateConfig()

    def test_description_preserved_with_content(self):
        t = TemplateConfig(content="# Hello", description="A greeting")
        assert t.description == "A greeting"

    def test_description_preserved_with_file(self):
        t = TemplateConfig(file="templates/hello.tmpl", description="A greeting")
        assert t.description == "A greeting"
