"""Tests for darnit.agent.state."""


from darnit.agent.state import AuditState, FeedbackQuestion


class TestFeedbackQuestion:
    def test_defaults(self):
        q = FeedbackQuestion(
            control_id="OSPS-BR-02.01",
            context_key="has_releases",
            question="Does the project publish releases?",
        )

        assert q.answer is None
        assert q.answered is False

    def test_can_be_answered(self):
        q = FeedbackQuestion(
            control_id="OSPS-BR-02.01",
            context_key="has_releases",
            question="Does the project publish releases?",
        )

        q.answer = "yes"
        q.answered = True

        assert q.answer == "yes"
        assert q.answered is True


class TestAuditState:
    def test_defaults(self):
        state = AuditState(local_path="/repo")

        assert state.owner is None
        assert state.repo is None
        assert state.default_branch == "main"
        assert state.framework_name is None
        assert state.level == 3
        assert state.audit_results == []
        assert state.feedback_questions == []
        assert state.context_values == {}
        assert state.remediation_results == []
        assert state.error is None

    def test_failing_control_ids_empty_when_no_results(self):
        state = AuditState(local_path="/repo")

        assert state.failing_control_ids() == []

    def test_failing_control_ids_filters_by_fail_status(self):
        state = AuditState(
            local_path="/repo",
            audit_results=[
                {"id": "CTRL-01", "status": "FAIL"},
                {"id": "CTRL-02", "status": "PASS"},
                {"id": "CTRL-03", "status": "FAIL"},
                {"id": "CTRL-04", "status": "WARN"},
            ],
        )

        result = state.failing_control_ids()

        assert result == ["CTRL-01", "CTRL-03"]

    def test_warn_control_ids_filters_by_warn_status(self):
        state = AuditState(
            local_path="/repo",
            audit_results=[
                {"id": "CTRL-01", "status": "FAIL"},
                {"id": "CTRL-02", "status": "WARN"},
                {"id": "CTRL-03", "status": "PASS"},
            ],
        )

        result = state.warn_control_ids()

        assert result == ["CTRL-02"]

    def test_has_unanswered_questions_false_when_empty(self):
        state = AuditState(local_path="/repo")

        assert state.has_unanswered_questions() is False

    def test_has_unanswered_questions_true_when_unanswered(self):
        state = AuditState(local_path="/repo")
        state.feedback_questions.append(
            FeedbackQuestion("CTRL-01", "has_releases", "Do you have releases?")
        )

        assert state.has_unanswered_questions() is True

    def test_has_unanswered_questions_false_when_all_answered(self):
        state = AuditState(local_path="/repo")
        q = FeedbackQuestion("CTRL-01", "has_releases", "Do you have releases?")
        q.answered = True
        q.answer = "yes"
        state.feedback_questions.append(q)

        assert state.has_unanswered_questions() is False

    def test_collect_answered_context_empty_when_none_answered(self):
        state = AuditState(local_path="/repo")
        state.feedback_questions.append(
            FeedbackQuestion("CTRL-01", "has_releases", "Q?")
        )

        result = state.collect_answered_context()

        assert result == {}

    def test_collect_answered_context_returns_answered_only(self):
        state = AuditState(local_path="/repo")

        q1 = FeedbackQuestion("CTRL-01", "has_releases", "Q1?")
        q1.answer = "yes"
        q1.answered = True

        q2 = FeedbackQuestion("CTRL-02", "maintainers", "Q2?")  # not answered

        state.feedback_questions = [q1, q2]

        result = state.collect_answered_context()

        assert result == {"has_releases": "yes"}
        assert "maintainers" not in result

    def test_collect_answered_context_multiple_answers(self):
        state = AuditState(local_path="/repo")

        for key, answer in [("has_releases", "yes"), ("is_library", "no")]:
            q = FeedbackQuestion("CTRL-01", key, f"Q for {key}?")
            q.answer = answer
            q.answered = True
            state.feedback_questions.append(q)

        result = state.collect_answered_context()

        assert result == {"has_releases": "yes", "is_library": "no"}
