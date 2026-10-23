# Copyright SUSE LLC
"""Unit tests for common.smelt."""

from __future__ import annotations

import json as json_module

import httpx
import pytest

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


def _client(status_code: int = 200, json: dict | None = None) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json=json, request=request)

    return httpx.Client(transport=httpx.MockTransport(respond)), seen


def _node(*names: str) -> dict:
    return {"edges": [{"node": {"packages": {"edges": [{"node": {"name": n}} for n in names]}}}]}


def test_submission_packages_without_ids_makes_no_request() -> None:
    client, seen = _client(json={})
    assert submission_packages([], client) == {}
    assert not seen


def test_submission_packages_one_aliased_query() -> None:
    client, seen = _client(json={"data": {"i1": _node("zlib", "Apache"), "i2": {"edges": []}}})
    assert submission_packages([1, 2], client) == {1: ["Apache", "zlib"], 2: []}
    assert [str(r.url) for r in seen] == [URL]
    query = json_module.loads(seen[0].content)["query"]
    assert "i1: incidents(incidentId: 1)" in query
    assert "i2: incidents(incidentId: 2)" in query


def test_submission_packages_without_url_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMELT_GRAPHQL_URL")
    client, seen = _client(json={})
    assert submission_packages([1], client) == {}
    assert not seen


def test_submission_packages_raises_on_http_error() -> None:
    client, _ = _client(500)
    with pytest.raises(httpx.HTTPError):
        submission_packages([1], client)
