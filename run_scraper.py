#!/usr/bin/env python3
"""
CLI entry point for running the Apache Jira scraper.

Example usage:

    python run_scraper.py --projects SPARK HADOOP ZOOKEEPER --output output.jsonl

You can interrupt the script at any time; if a checkpoint path is supplied it
will resume where it left off on the next run.
"""

import argparse
import os
from typing import Dict, Generator, List

from scraper import JiraClient, iter_project_issues, save_issues_as_jsonl, transform_issue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Apache Jira projects and output JSONL data")
    parser.add_argument(
        "--projects",
        nargs="+",
        required=True,
        help="One or more Jira project keys to scrape (e.g. SPARK HADOOP ZOOKEEPER)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the output JSONL file (existing file will be appended to)",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="Optional path to a checkpoint JSON file to enable resumption",
    )

    parser.add_argument(
        "--max-issues",
        type=int,
        default=None,
        help=(
            "Maximum number of issues to fetch across all projects. "
            "Use this for quick testing to limit the amount of data fetched. "
            "If omitted, all issues will be processed."
        ),
    )
    return parser.parse_args()


def main(
    projects: List[str],
    output_path: str,
    checkpoint_path: str | None = None,
    max_issues: int | None = None,
) -> None:
    """
    Execute the scraper for the given projects.

    Args:
        projects: List of Jira project keys to scrape.
        output_path: Path to write the JSONL output.
        checkpoint_path: Optional path to a checkpoint JSON file.
        max_issues: Optional maximum number of issues to process across all projects.
    """
    client = JiraClient()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if checkpoint_path:
        os.makedirs(os.path.dirname(checkpoint_path) or ".", exist_ok=True)
    # Iterate through projects and process issues, respecting max_issues if provided
    def generate() -> Generator[Dict, None, None]:
        count = 0
        for project in projects:
            for raw_issue in iter_project_issues(client, project):
                if max_issues is not None and count >= max_issues:
                    return
                yield transform_issue(raw_issue)
                count += 1
    save_issues_as_jsonl(generate(), output_path, checkpoint_path)


if __name__ == "__main__":
    args = parse_args()
    main(args.projects, args.output, args.checkpoint, args.max_issues)