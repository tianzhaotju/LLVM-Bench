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


if "__main__" == __name__:
    ori_all_instances = read_all_instances("./all_instances_4.jsonl")
    all_instances = []
    for instance in tqdm(ori_all_instances):
        print(instance["comments_data"])
        tmp_instance = {}
        tmp_instance["repository"] = instance["repository"]
        tmp_instance["bug_commit_id"] = str(instance["bug_commit_id"])
        tmp_instance["fix_commit_id"] = str(instance["fix_commit_id"])
        tmp_instance["patch"] = instance["golden_code_patch"]
        tmp_instance["test_patch"] = instance["golden_test_patch"]
        tmp_instance["commit_message"] = instance["commit_message"]
        tmp_instance["commit_time"] = instance["committed_datetime"]
        tmp_instance["module"] = instance["location"]
        tmp_instance["modification"] = instance["modification"]
        tmp_instance["version"] = str(instance["version"])
        tmp_instance["issue_id"] = str(int(instance["issue_url"].split("/")[-1]))
        tmp_instance["issue_title"] = instance["issue_data"]["title"]
        tmp_instance["issue_body"] = instance["issue_data"]["body"]
        tmp_instance["issue_type"] = instance["issue_type"]
        tmp_instance["issue_comment"] = [_["body"] for _ in instance["comments_data"]]

        all_instances.append(tmp_instance)

    with open('../dataset/compiler_bench.jsonl', 'w', encoding='utf-8') as f:
        for item in all_instances:
            f.write(json.dumps(item) + '\n')
