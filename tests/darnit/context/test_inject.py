from unittest.mock import patch, MagicMock
from darnit.context.inject import (
    inject_project_context,
    create_check_context_with_project,
    get_project_value,
    has_project_value,
)

class TestInject:
    @patch("darnit.context.inject.DotProjectMapper")
    def test_inject_project_context_success(self, mock_mapper_class):
        mock_mapper = mock_mapper_class.return_value
        mock_mapper.get_context.return_value = {"project.name": "test"}
        
        # We can just use a generic mock object for CheckContext
        context = MagicMock()
        context.owner = "test-org"
        context.local_path = "/tmp/repo"
        context.control_id = "test-control"
        
        inject_project_context(context)
        
        mock_mapper_class.assert_called_once_with("/tmp/repo", owner="test-org")
        assert context.project_context == {"project.name": "test"}

    @patch("darnit.context.inject.DotProjectMapper")
    def test_inject_project_context_no_owner(self, mock_mapper_class):
        mock_mapper = mock_mapper_class.return_value
        mock_mapper.get_context.return_value = {"project.name": "test"}
        
        context = MagicMock()
        context.owner = None
        context.local_path = "/tmp/repo"
        context.control_id = "test-control"
        
        inject_project_context(context)
        
        mock_mapper_class.assert_called_once_with("/tmp/repo", owner="")
        assert context.project_context == {"project.name": "test"}

    @patch("darnit.context.inject.DotProjectMapper")
    def test_inject_project_context_exception(self, mock_mapper_class):
        mock_mapper_class.side_effect = Exception("Failed to load")
        
        context = MagicMock()
        context.owner = "test-org"
        context.local_path = "/tmp/repo"
        context.control_id = "test-control"
        
        inject_project_context(context)
        
        # It should catch the exception and assign an empty dict
        assert context.project_context == {}

    @patch("darnit.context.inject.inject_project_context")
    @patch("darnit.sieve.models.CheckContext")
    def test_create_check_context_with_project(self, mock_check_context, mock_inject):
        mock_instance = mock_check_context.return_value
        
        result = create_check_context_with_project(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="c1",
        )
        
        mock_check_context.assert_called_once_with(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="c1",
            control_metadata={}
        )
        mock_inject.assert_called_once_with(mock_instance)
        assert result == mock_instance

    def test_get_project_value(self):
        context = MagicMock()
        context.project_context = {"key1": "val1"}
        
        assert get_project_value(context, "key1") == "val1"
        assert get_project_value(context, "key2", "default_val") == "default_val"
        
    def test_has_project_value(self):
        context = MagicMock()
        context.project_context = {"key1": "val1"}
        
        assert has_project_value(context, "key1") is True
        assert has_project_value(context, "key2") is False