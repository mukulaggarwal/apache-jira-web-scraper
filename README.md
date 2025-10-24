# Apache Jira Web Scraper Assignment

This repository contains a reference implementation of the **Web Scraping Tutor Assignment**.  The goal of the assignment is to build a robust data‐scraping and transformation pipeline that collects public issue data from Apache’s Jira instance and converts it into a high‑quality JSONL corpus suitable for training large language models (LLMs).

## Overview

The provided Python code implements a scraper that:

1. **Scrapes issue data from multiple Apache Jira projects.**  You can specify any number of project keys (the assignment requires at least three).  The scraper fetches issue metadata, descriptions, comments and other relevant fields from the public Jira REST API at `https://issues.apache.org/jira`.  For quick testing you can also limit how many issues are processed across all projects by using the `--max-issues` command‑line option.
2. **Handles pagination, rate‑limits and transient failures.**  Requests are retried with exponential back‑off for common network errors, HTTP 429 (Too Many Requests) and 5xx server responses.  The `max_results` and `start_at` parameters are used to iteratively page through large result sets.  A simple checkpointing mechanism allows the scraper to resume from the last successful state if interrupted.
3. **Transforms raw Jira issues into a clean JSONL format.**  Each output JSON object contains:
   - *issue_key*, *title*, *status*, *project*, *reporter*, *assignee*, *priority*, *created*, *updated* and other metadata.
   - The full *description* and list of *comments* (plain text).
   - A derived set of **tasks** (summarization, classification and question‑answer pairs) that can be used to fine‑tune language models.
4. **Produces reproducible, structured output.**  All scraped issues are streamed to a JSONL file on disk.  Each line represents a single issue to facilitate easy downstream processing.

## Repository contents

```
web_scraping_assignment/
├── README.md            – this file
├── scraper.py           – reusable library for interacting with Apache Jira
├── run_scraper.py       – command line entry point for running the scraper
└── examples/
    └── output.jsonl     – sample JSONL produced by scraping three projects
```

## Quick start

This project requires Python 3.8+ and the `requests` package.  Create a virtual environment and install dependencies with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To scrape three example Apache projects (e.g. `SPARK`, `HADOOP` and `ZOOKEEPER`) and write the results to `output.jsonl`:

```bash
python run_scraper.py --projects SPARK HADOOP ZOOKEEPER --output examples/output.jsonl
```

During development or testing you may not want to download every issue.  You can limit the number of issues processed across all projects by specifying the `--max-issues` option.  For example, to fetch only the first **10** issues from the above projects and write them to `test_output.jsonl`:

```bash
python run_scraper.py \
  --projects SPARK HADOOP ZOOKEEPER \
  --output examples/test_output.jsonl \
  --max-issues 10
```

The script will stream progress to the console and write each issue as a JSON object on a separate line of the output file.  You can safely interrupt and resume the scraper; it will continue from the last saved checkpoint.

## Architecture and design decisions

### 1. Scraper logic

The scraper uses the public Jira REST API (`/rest/api/2/search` and `/rest/api/2/issue/{issueKey}`) to gather issue data.  The `search` endpoint accepts a JQL query (`project=XYZ`) and supports pagination via `startAt` and `maxResults`.  To optimise throughput, the scraper requests up to 100 issues per page and includes only the fields that we care about (summary, description, status, etc.).  Comments are fetched separately per issue because the search endpoint returns only partial comment data.

### 2. Fault tolerance

All network calls are wrapped in a `retry_request` helper that attempts a request up to five times with exponential back‑off.  If the server returns HTTP 429 (Too Many Requests), the scraper honours the `Retry‑After` header when present.  For 5xx responses, it waits an increasing amount of time before retrying.  Other transient errors (connection timeouts, DNS failures, etc.) are similarly retried.

### 3. Checkpointing and resumption

The scraper writes a lightweight checkpoint file (`.checkpoint.json`) alongside the output to record the list of issues already processed.  On start‑up it reads this file (if present) and skips any issues that were previously saved.  This allows the script to resume after a crash or network interruption without re‑downloading data.

### 4. Data transformation

When each issue is retrieved, the script constructs a Python dictionary capturing its metadata, description and comments.  It then derives three types of tasks:

1. **Summarisation**: A concise summary of the issue’s description and comments.  For demonstration purposes the summary simply truncates the description and first comment to a fixed length; however, this could be replaced with a call to a summarisation model.
2. **Classification**: The issue type (e.g. `Bug`, `Improvement`, etc.) is included as a label suitable for classification tasks.
3. **Question & Answer**: A simple Q&A pair asking what the issue describes and answering with the summary.

These tasks illustrate how unstructured Jira data can be converted into training examples for an LLM.

### 5. Extensibility

The code is intentionally modular.  The `JiraClient` class encapsulates API interactions, while `transform_issue` prepares the JSON objects.  This makes it straightforward to add new fields, change the JQL query, or plug in more sophisticated NLP transformations.

### 6. Future improvements

- **Concurrency**: Currently issues are processed sequentially.  Using asynchronous HTTP requests or a thread pool would significantly speed up the scraping of large projects.
- **Advanced summarisation**: Integrate a summarisation model (e.g. via Hugging Face) to produce higher‑quality summaries of descriptions and comments.
- **Persistent database**: Instead of writing directly to a file, store raw and processed issues in a database (e.g. SQLite or PostgreSQL) for easier querying and deduplication.
- **Dockerisation**: Package the scraper as a Docker image for reproducible execution across environments.
- **Testing**: Add unit tests for individual components, especially the retry logic and transformation functions.

## Edge cases handled

- Network timeouts, DNS failures and connection errors – handled by retry logic.
- HTTP 429 responses (rate limiting) – waits according to `Retry‑After` header or a sensible default.
- HTTP 5xx responses – retried with exponential back‑off.
- Empty or malformed data – fields are defaulted to `None` if missing; comments are an empty list when absent.
- Interrupted runs – checkpointing allows resumption without duplicating data.

## Licence

This work is provided solely for demonstration purposes in the context of the Meta staff engineer assignment.  You are free to modify and extend it for educational use.