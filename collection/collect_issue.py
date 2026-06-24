import os
import re
import csv
import json
import copy
import requests
import numpy as np
from tqdm import tqdm
from typing import Dict, List
from urlextract import URLExtract


def read_all_instances(path):
    all_instances = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            instance = json.loads(line.strip())
            all_instances.append(instance)

    return all_instances


def parse_issue_url(issue_url: str):
    """
    Parse owner, repo, issue_number from GitHub issue URL
    """
    pattern = r"github\.com/([^/]+)/([^/]+)/issues/(\d+)"
    match = re.search(pattern, issue_url)
    if not match:
        raise ValueError("Invalid GitHub issue URL")

    owner, repo, issue_number = match.groups()
    return owner, repo, int(issue_number)


def github_request(url: str, token: str, params=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json(), resp.headers


def get_all_pages(url: str, token: str) -> List[Dict]:
    """
    Handle GitHub pagination automatically
    """
    results = []
    page = 1
    while True:
        data, headers = github_request(
            url, token, params={"per_page": 100, "page": page}
        )
        if not data:
            break
        results.extend(data)
        if len(data) < 100:
            break
        page += 1
    return results


def get_issue_content(issue_url: str, token: str = None):
    """
    Get full issue content from GitHub API
    """
    if not token:
        raise RuntimeError("GitHub token not provided")

    owner, repo, issue_number = parse_issue_url(issue_url)

    # 1. Issue metadata
    GITHUB_API_BASE = "https://api.github.com"
    issue_api = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}"
    issue_data, _ = github_request(issue_api, token)


    # 2. Issue comments
    comments_api = issue_data["comments_url"]
    comments_data = get_all_pages(comments_api, token)

    return [issue_data, comments_data]


if "__main__" == __name__:
    TOKEN = "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"
    ori_all_instances = read_all_instances("./all_instances_3.jsonl")
    confirmed_instances = open("./commit_issue-manual.csv", "r").readlines()
    confirmed_instances = [_.split(",") for _ in confirmed_instances if _.split(",")[3] == "yes"]
    confirmed_instances_dict = {}
    for instance in confirmed_instances:
        confirmed_instances_dict[instance[0]] = instance
    all_instances = []
    for instance in tqdm(ori_all_instances):
        if instance["fix_commit_id"] in confirmed_instances_dict.keys():
            tmp_instance = copy.deepcopy(instance)
            tmp_instance["location"] = confirmed_instances_dict[tmp_instance["fix_commit_id"]][1].strip("/").strip()
            tmp_instance["issue_url"] = confirmed_instances_dict[tmp_instance["fix_commit_id"]][2].strip()
            tmp_instance["issue_type"] = confirmed_instances_dict[tmp_instance["fix_commit_id"]][4].strip()

            if os.path.exists(f"./issue/{tmp_instance['fix_commit_id']}.jsonl"):
                issue_content = json.loads(open(f"./issue/{tmp_instance['fix_commit_id']}.jsonl", "r").read())
            else:
                issue_content = get_issue_content(tmp_instance["issue_url"], TOKEN)
                open(f"./issue/{tmp_instance['fix_commit_id']}.jsonl", "w").write(json.dumps(issue_content))
            tmp_instance["issue_data"] = issue_content[0]
            tmp_instance["comments_data"] = issue_content[1]
            all_instances.append(tmp_instance)

    with open('./all_instances_4.jsonl', 'w', encoding='utf-8') as f:
        for item in all_instances:
            f.write(json.dumps(item) + '\n')