"""Business-route isolation contracts for the single Agent worker."""

import pytest

from agent import worker


def test_config_routes_keep_namespaced_and_legacy_compatibility():
    assert worker._route_name("/config/chat") == "config_chat"
    assert worker._route_name("/chat") == "config_chat"
    assert worker._route_name("/config/chat_stream") == "config_chat_stream"
    assert worker._route_name("/chat_stream") == "config_chat_stream"
    assert worker._route_name("/config/reset") == "config_reset"
    assert worker._route_name("/reset") == "config_reset"


def test_report_routes_are_namespaced_without_sharing_config_state():
    assert worker._route_name("/report/analyze") == "report_analyze"
    assert worker._route_name("/report/latest") == "report_latest"
    assert worker._report_lock is not worker._config_lock
    assert not hasattr(worker, "_agent_lock")


def test_report_request_accepts_only_session_and_scope_schema():
    request = worker._parse_report_request(
        {
            "session_id": 12,
            "data_access_scope": {
                "current_session": True,
                "longitudinal": False,
                "cohort": False,
            },
        }
    )
    assert request.session_id == 12

    with pytest.raises(ValueError):
        worker._parse_report_request(
            {
                "session_id": 12,
                "data_access_scope": {"current_session": True},
                "sql": "SELECT * FROM test_sessions",
            }
        )


def test_report_request_rejects_disabled_current_session_scope():
    with pytest.raises(ValueError):
        worker._parse_report_request(
            {
                "session_id": 12,
                "data_access_scope": {"current_session": False},
            }
        )


def test_unknown_route_is_not_resolved():
    assert worker._route_name("/tools/run") is None
