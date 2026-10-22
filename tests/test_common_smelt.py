# Copyright SUSE LLC
"""Unit tests for common.smelt."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from common.smelt import submission_ids, submission_packages

URL = "https://smelt.example/graphql/"


@pytest.fixture(autouse=True)
def smelt_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMELT_GRAPHQL_URL", URL)


def test_submission_ids_merges_all_test_issues_settings() -> None:
    settings = {
        "OS_TEST_ISSUES": "3, 1,",
        "BASE_TEST_ISSUES": "2,1",
        "BUILD": "42",
        "X_TEST_ISSUES": "",
        "Y_TEST_ISSUES": "a",
    }
    assert submission_ids(settings) == [1, 2, 3]


def test_submission_packages_without_ids_makes_no_request() -> None:
    session = Mock()
    assert submission_packages([], session) == {}
    session.post.assert_not_called()


def _node(*names: str) -> dict:
    return {"edges": [{"node": {"packages": {"edges": [{"node": {"name": n}} for n in names]}}}]}


def test_submission_packages_one_aliased_query() -> None:
    session = Mock()
    session.post.return_value.json.return_value = {"data": {"i1": _node("zlib", "Apache"), "i2": {"edges": []}}}
    assert submission_packages([1, 2], session) == {1: ["Apache", "zlib"], 2: []}
    url, query = session.post.call_args[0][0], session.post.call_args[1]["json"]["query"]
    assert url == URL
    assert "i1: incidents(incidentId: 1)" in query
    assert "i2: incidents(incidentId: 2)" in query


def test_submission_packages_without_url_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMELT_GRAPHQL_URL")
    session = Mock()
    assert submission_packages([1], session) == {}
    session.post.assert_not_called()


def test_submission_packages_raises_on_http_error() -> None:
    session = Mock()
    session.post.return_value.raise_for_status.side_effect = requests.HTTPError("500")
    with pytest.raises(requests.RequestException):
        submission_packages([1], session)
