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
from typing import List

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
    return parser.parse_args()


def main(projects: List[str], output_path: str, checkpoint_path: str | None = None) -> None:
    client = JiraClient()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if checkpoint_path:
        os.makedirs(os.path.dirname(checkpoint_path) or ".", exist_ok=True)
    # Iterate through projects and process issues
    def generate():
        for project in projects:
            for raw_issue in iter_project_issues(client, project):
                yield transform_issue(raw_issue)
    save_issues_as_jsonl(generate(), output_path, checkpoint_path)


if __name__ == "__main__":
    args = parse_args()
    main(args.projects, args.output, args.checkpoint)