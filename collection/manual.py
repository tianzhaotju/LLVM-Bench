import os
import re
import csv
import json
import numpy as np
from urlextract import URLExtract


def read_all_instances(path):
    all_instances = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            instance = json.loads(line.strip())
            all_instances.append(instance)

    return all_instances


def print_issue_link():
    commit_issue = {}
    commit_type = {}
    commit_text = {}
    clang_count, llvm_count, backend_count, tools_count, others_count = 0, 0, 0, 0, 0
    location_dict = {}
    path_list = ["exec-1", "exec-2", "exec-3", "exec-4"]
    for path in path_list:
        log_file_list = os.listdir(f"log/{path}")
        for log_file in log_file_list:
            if log_file not in all_instances_dict.keys():
                continue
            log_path = os.path.join(f"log/{path}", log_file)
            log_text = open(log_path, "r").read()
            if not log_text.strip().endswith("Reproduction & Repair success."):
                continue

            commit_message = all_instances_dict[log_file]["commit_message"]

            extractor = URLExtract()
            urls = extractor.find_urls(commit_message)
            issue_urls = []
            for url in urls:
                tmp_url = url.strip(".")
                if not tmp_url.startswith("https://github.com/llvm/llvm-project/issues/"):
                    continue
                issue_num = tmp_url.strip("https://github.com/llvm/llvm-project/issues/")
                if not issue_num.isdecimal():
                    continue
                if tmp_url in issue_urls:
                    continue
                issue_urls.append(tmp_url)

            if len(issue_urls) == 0:
                continue
            elif len(issue_urls) > 1:
                continue

            if issue_urls[0] in commit_issue.values():
                continue

            llvm_flag, clang_flag, backend_flag, tools_flag, others_flag = False, False, False, False, False
            loc = ""
            for _ in all_instances_dict[log_file]["modification"].keys():
                if "/test/" in _ or \
                    "/unittests/" in _:
                    continue

                if _.startswith("clang/"):
                    clang_flag = True
                elif _.startswith("llvm/lib/Target") or \
                        _.startswith("llvm/lib/CodeGen") or \
                        _.startswith("llvm/include/llvm/Target") or \
                        _.startswith("llvm/include/llvm/CodeGen"):
                    backend_flag = True
                elif _.startswith("llvm/lib/Transforms/") or \
                        _.startswith("llvm/lib/Analysis/") or \
                        _.startswith("llvm/include/llvm/Transforms/") or \
                        _.startswith("llvm/include/llvm/Analysis/"):
                    llvm_flag = True
                elif _.startswith("llvm/tools/") or \
                        _.startswith("llvm/utils/"):
                    tools_flag = True
                if "/include/" in _:
                    loc = "/".join(_.split("/")[:4])
                else:
                    loc = "/".join(_.split("/")[:3])
                if clang_flag or llvm_flag or backend_flag or tools_flag:
                    if loc in location_dict.keys():
                        location_dict[loc] += 1
                    else:
                        location_dict[loc] = 1
                    break


            if clang_flag:
                clang_count += 1
            elif llvm_flag:
                llvm_count += 1
            elif backend_flag:
                backend_count += 1
            elif tools_flag:
                tools_count += 1
            else:
                if loc in location_dict.keys():
                    location_dict[loc] += 1
                else:
                    location_dict[loc] = 1
                others_count += 1

            commit_issue[log_file] = issue_urls[0]
            commit_type[log_file] = loc
            commit_text[log_file] = commit_message.replace("\n", " ").replace(",", "，").replace("\r", " ").replace("\t", " ")

    return commit_issue, commit_type, commit_text


if "__main__" == __name__:
    all_instances = read_all_instances("./all_instances_3.jsonl")
    all_instances_dict = {}
    for instance in all_instances:
        all_instances_dict[instance["fix_commit_id"]] = instance

    version_list = {"exec-1": "version 21",
                    "exec-2": "version 20",
                    "exec-3": "version 19",
                    "exec-4": "version 18"}

    commit_issue, commit_type, commit_text = print_issue_link()
    print(len(commit_issue))
    print(len(commit_type))
    log_text = ""
    data = []
    for k, v in commit_issue.items():
        log_text += f"{k}, {commit_type[k]}, {v}, {commit_text[k].strip()}\n"
        data.append([k, commit_type[k], v, commit_text[k].strip()])

    open("commit_issue.csv", "w").write(log_text)