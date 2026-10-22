# Copyright SUSE LLC
"""Helpers to look up submissions in SMELT."""

from __future__ import annotations

import os

import requests

TIMEOUT = 100


def submission_ids(settings: dict[str, str]) -> list[int]:
    """Return the sorted submission IDs listed in the `*_TEST_ISSUES` job settings."""
    ids = set()
    for key, value in settings.items():
        if "_TEST_ISSUES" in key:
            ids |= {int(x) for x in str(value).split(",") if x.strip().isdigit()}
    return sorted(ids)


def submission_packages(ids: list[int], session: requests.Session | None = None) -> dict[int, list[str]]:
    """Return sorted package names per submission ID from `$SMELT_GRAPHQL_URL`; raise `requests.RequestException`."""
    url = os.environ.get("SMELT_GRAPHQL_URL")
    if not ids or not url:
        return {}
    fields = "edges{node{packages{edges{node{name}}}}}"
    query = "{" + " ".join(f"i{i}: incidents(incidentId: {i}){{{fields}}}" for i in ids) + "}"
    got = (session or requests).post(url, json={"query": query}, timeout=TIMEOUT)
    got.raise_for_status()
    data = got.json().get("data") or {}
    return {
        i: sorted(
            {p["node"]["name"] for e in data.get(f"i{i}", {}).get("edges", []) for p in e["node"]["packages"]["edges"]},
            key=str.casefold,
        )
        for i in ids
    }
