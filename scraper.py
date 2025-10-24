"""
scraper.py
------------

This module provides a `JiraClient` class for interacting with the public
Apache Jira REST API and functions to transform raw issue data into a
JSONL‑friendly format.  It is designed to be fault‑tolerant, efficient
and easily extendable for additional transformations.

The API methods here do not require authentication for public projects on
`issues.apache.org`.  If you wish to scrape private Jira instances, you
should add support for basic auth or OAuth as appropriate.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Generator, Iterable, List, Optional, Tuple

import requests
from requests import Response


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class JiraClient:
    """A simple client for the Apache Jira REST API.

    This client handles pagination, retries and basic error handling.  It can
    fetch issues for a given project key and retrieve details (including
    comments) for each issue.
    """

    BASE_URL = "https://issues.apache.org/jira/rest/api/2"

    def __init__(self, max_retries: int = 5, backoff_factor: float = 1.0) -> None:
        self.session = requests.Session()
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def _retry_request(self, method: str, url: str, **kwargs) -> Response:
        """Perform a HTTP request with retry and exponential back‑off.

        Args:
            method: HTTP verb ('GET', 'POST', etc.)
            url: Full URL to request.
            **kwargs: Additional arguments forwarded to `requests.Session.request`.

        Returns:
            The successful `Response` object.

        Raises:
            requests.HTTPError if the request ultimately fails after retries.
        """
        retries = 0
        while True:
            try:
                resp: Response = self.session.request(method, url, timeout=30, **kwargs)
                # Respect HTTP 429 (rate limiting)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 5))
                    logger.warning("Rate limited (429). Waiting %s seconds before retry", retry_after)
                    time.sleep(retry_after)
                    raise requests.HTTPError(f"HTTP 429: Rate limited", response=resp)
                # Handle 5xx errors
                if 500 <= resp.status_code < 600:
                    raise requests.HTTPError(f"Server error {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                if retries >= self.max_retries:
                    logger.error("Max retries exceeded for %s %s", method, url)
                    raise
                wait_time = self.backoff_factor * (2 ** retries)
                logger.warning("Request error: %s. Retrying in %.1f seconds (attempt %d/%d)", exc, wait_time, retries + 1, self.max_retries)
                time.sleep(wait_time)
                retries += 1

    def search_issues(self, project: str, start_at: int = 0, max_results: int = 100) -> Tuple[List[Dict], int]:
        """Query Jira for issues in a project using the search API.

        Args:
            project: The Jira project key, e.g. 'SPARK'.
            start_at: Index of the first issue to return (for pagination).
            max_results: Maximum number of results to return per page (max 100).

        Returns:
            A tuple of (issues, total) where issues is a list of issue objects and
            total is the total number of issues in the project.
        """
        jql = f"project={project} order by key asc"
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            # Ask only for fields we need; other fields will be None.
            "fields": "summary,description,issuetype,status,priority,reporter,assignee,created,updated,labels",  # noqa: E501
        }
        url = f"{self.BASE_URL}/search"
        resp = self._retry_request("GET", url, params=params)
        data = resp.json()
        issues = data.get("issues", [])
        total = data.get("total", 0)
        return issues, total

    def fetch_issue_details(self, issue_key: str) -> Dict:
        """Fetch detailed information (including comments) for a specific issue.

        Args:
            issue_key: The issue key, e.g. 'SPARK-12345'.

        Returns:
            The JSON representation of the issue.
        """
        url = f"{self.BASE_URL}/issue/{issue_key}"
        params = {"expand": "comments"}
        resp = self._retry_request("GET", url, params=params)
        return resp.json()


def iter_project_issues(client: JiraClient, project: str) -> Generator[Dict, None, None]:
    """Iterate through all issues in a project, yielding detailed issue data.

    This generator takes care of pagination under the hood.  It fetches
    summaries in batches then retrieves each issue's details (including
    comments).
    """
    start = 0
    batch_size = 100
    total = None
    while True:
        issues, total_count = client.search_issues(project, start_at=start, max_results=batch_size)
        if total is None:
            total = total_count
            logger.info("Project %s: total %d issues", project, total)
        if not issues:
            break
        for item in issues:
            issue_key = item.get("key")
            try:
                details = client.fetch_issue_details(issue_key)
                yield details
            except Exception as exc:
                logger.error("Failed to fetch details for issue %s: %s", issue_key, exc)
        start += len(issues)
        if start >= total:
            break


def transform_issue(issue: Dict) -> Dict:
    """Transform a raw Jira issue into a structured JSON object for LLM tasks.

    Args:
        issue: Raw issue JSON returned from the Jira API.

    Returns:
        A dictionary ready for serialisation to JSONL.
    """
    fields = issue.get("fields", {})
    key = issue.get("key")
    summary = fields.get("summary")
    description = fields.get("description") or ""
    issuetype = fields.get("issuetype", {}).get("name")
    status = fields.get("status", {}).get("name")
    priority = fields.get("priority", {}).get("name")
    reporter = fields.get("reporter", {}).get("displayName") if fields.get("reporter") else None
    assignee = fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None
    created = fields.get("created")
    updated = fields.get("updated")
    labels = fields.get("labels", []) or []
    # Extract comments (plain text)
    comment_data = fields.get("comment", {})
    comments: List[str] = []
    if comment_data and "comments" in comment_data:
        for c in comment_data.get("comments", []):
            body = c.get("body")
            if body:
                comments.append(body)

    # Derive tasks for LLM training
    tasks: List[Dict[str, str]] = []
    # Summarisation: for demo, use the first 300 characters of description + first comment
    combined_text = description
    if comments:
        combined_text += "\n" + comments[0]
    summary_text = combined_text[:300] + ("..." if len(combined_text) > 300 else "")
    tasks.append({
        "task": "summarisation",
        "input": description,
        "output": summary_text,
    })
    # Classification: label by issue type
    tasks.append({
        "task": "classification",
        "input": description,
        "output": issuetype or "Unknown",
    })
    # Q&A: simple question/answer pair about what the issue describes
    question = f"What is the issue {key} about?"
    answer = summary_text
    tasks.append({
        "task": "question_answering",
        "question": question,
        "answer": answer,
    })
    return {
        "issue_key": key,
        "title": summary,
        "status": status,
        "project": issue.get("fields", {}).get("project", {}).get("key"),
        "reporter": reporter,
        "assignee": assignee,
        "priority": priority,
        "created": created,
        "updated": updated,
        "labels": labels,
        "description": description,
        "comments": comments,
        "tasks": tasks,
    }


def save_issues_as_jsonl(issues: Iterable[Dict], output_path: str, checkpoint_path: Optional[str] = None) -> None:
    """Save transformed issues to a JSONL file with optional checkpointing.

    Args:
        issues: An iterable of transformed issue dictionaries.
        output_path: Path to write the JSONL file.
        checkpoint_path: Path to a checkpoint JSON file mapping issue keys to `True`.
    """
    # Load existing checkpoints if present
    processed: Dict[str, bool] = {}
    if checkpoint_path and os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                processed = json.load(f)
            logger.info("Loaded checkpoint with %d issues", len(processed))
        except Exception as exc:
            logger.warning("Failed to read checkpoint file %s: %s", checkpoint_path, exc)

    with open(output_path, "a", encoding="utf-8") as out_f:
        for issue in issues:
            key = issue.get("issue_key")
            if processed.get(key):
                continue
            out_f.write(json.dumps(issue, ensure_ascii=False) + "\n")
            processed[key] = True
            if checkpoint_path:
                # Persist checkpoint after every issue
                try:
                    with open(checkpoint_path, "w", encoding="utf-8") as ckpt_f:
                        json.dump(processed, ckpt_f)
                except Exception as exc:
                    logger.warning("Failed to write checkpoint file %s: %s", checkpoint_path, exc)