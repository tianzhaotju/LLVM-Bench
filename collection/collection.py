import re
import json
import numpy as np
from git import Repo
from tqdm import tqdm
from datetime import datetime, timezone


def get_all_commits(repo, branch="main", start_time=None, end_time=None):
    # LLVM main branch
    if branch == "main":
        main = repo.heads.main
    else:
        print("Please check the branch name.")
    total_num_commits = len(list(repo.iter_commits("main")))

    # commits
    idx = 0
    all_commits = []
    for commit in tqdm(main.commit.iter_items(repo, f'{main.commit.hexsha}'), total=total_num_commits):
        idx += 1
        # commit type
        if commit.type != "commit":
            continue

        # time range
        if start_time is not None:
            if commit.committed_datetime.replace(tzinfo=timezone.utc) < start_time:
                continue
        if end_time is not None:
            if commit.committed_datetime.replace(tzinfo=timezone.utc) > end_time:
                continue

        # commit parents
        if len(commit.parents) not in [1]:
            continue

        # only fix one issue
        if "https://github.com/llvm/llvm-project/issues/" not in commit.message:
            continue

        # must modify test/unittests files
        if len(commit.stats.files) < 2:
            continue
        if ("/test/" not in str(list(commit.stats.files.keys()))) and \
                ("/unittests/" not in str(list(commit.stats.files.keys()))):
            continue
        if len([_ for _ in list(commit.stats.files.keys()) if "/test/" not in _ and "/unittests/" not in _]) == 0:
            continue

        # count modified files and lines
        modified_files = []
        modified_lines = 0
        for m_file in commit.stats.files.keys():
            if "/test/" in m_file or "/unittests/" in m_file:
                continue
            if m_file not in modified_files:
                modified_files.append(m_file)
            modified_lines += commit.stats.files[m_file]["lines"]

        if modified_lines > 1000:
            continue

        if len(modified_files) > 30:
            continue

        # get LLVM version
        try:
            ori_version = repo.git.describe("--tags", commit.hexsha)
            version = int(ori_version.split("-")[1])
        except:
            continue

        # only select the latest 18, 19, 20, 21 versions
        selected_version = [21, 20, 19, 18]
        if version not in selected_version:
            continue
        all_commits.append([commit, version])

    return all_commits


def get_all_instances(all_commits):
    all_instances = []
    for commit, version in tqdm(all_commits):
        fix_commit_id = str(commit.hexsha)
        bug_commit_id = str(commit.parents[0])

        modified_file_list = list(commit.stats.files.keys())

        # full patch (one file)
        golden_full_patch = repo.git.show(fix_commit_id, format="", pretty="")

        # split the full patch by file
        parts = re.split(r'(?=diff --git a/)', golden_full_patch)
        file_patches = {}
        for part in parts:
            if not part.strip():
                continue
            # exact filename from "diff --git a/foo b/foo"
            m = re.match(r'diff --git a/(.*?) b/', part)
            if m:
                filename = m.group(1)
                file_patches[filename] = part

        # filter rename commits
        if set(list(file_patches.keys())) != set(modified_file_list) or \
                len(list(file_patches.keys())) != len(modified_file_list):
            continue

        # construct golden code patch and golden code patch
        golden_code_patch = ""
        golden_test_patch = ""
        for filename in modified_file_list:
            if "/test/" in filename or "/unittests/" in filename:
                golden_test_patch += file_patches[filename].strip()+"\n"
            else:
                golden_code_patch += file_patches[filename].strip()+"\n"

        all_instances.append({"repository": repository_name,
                              "bug_commit_id": bug_commit_id,
                              "fix_commit_id": fix_commit_id,
                              "golden_full_patch": golden_full_patch,
                              "golden_code_patch": golden_code_patch,
                              "golden_test_patch": golden_test_patch,
                              "commit_message": commit.message,
                              "committed_datetime": str(commit.committed_datetime.replace(tzinfo=timezone.utc)),
                              "modification": commit.stats.files,
                              "version": version})

    return all_instances


if __name__ == "__main__":
    repo_path = "../codebases/llvm-project-ori/"
    repo = Repo(repo_path)
    repository_name = "llvm/llvm-project"
    branch = "main"
    start_time, end_time = None, None

    all_commits = get_all_commits(repo, branch, start_time, end_time)
    print(len(all_commits))

    all_instances = get_all_instances(all_commits)
    print(len(all_instances))
    with open('./all_instances_1.jsonl', 'w', encoding='utf-8') as f:
        for item in all_instances:
            f.write(json.dumps(item) + '\n')
