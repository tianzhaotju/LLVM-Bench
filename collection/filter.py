import os
import re
import time
import json
import subprocess
import numpy as np
from git import Repo
from tqdm import tqdm
from datetime import datetime, timezone


def read_all_instances(path):
    all_instances = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            instance = json.loads(line.strip())
            all_instances.append(instance)

    return all_instances


def run_with_realtime_output(cmd, cwd, shell, input=None):
    if input is None:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            shell=shell,
        )
    else:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            shell=shell,
        )
        # Write patch to stdin
        process.stdin.write(input)
        process.stdin.close()


    logs = []
    for line in process.stdout:
        print(line, end="")
        logs.append(line)

    process.wait()

    return process.returncode, "".join(logs)


def verify_one_instance(instance, base_path, ori_repo_path, tmp_repo_path):
    log_text = ""
    bug_commit_id = instance["bug_commit_id"]
    golden_code_patch = instance["golden_code_patch"]
    golden_test_patch = instance["golden_test_patch"]

    cmd = "git reset --hard HEAD"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(tmp_repo_path), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    cmd = "git clean -fd"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(tmp_repo_path), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    cmd = f"git checkout {bug_commit_id}"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(tmp_repo_path), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    print("git apply <golden test patch>", "...")
    returncode, logs = run_with_realtime_output(["git", "apply", "-"], str(tmp_repo_path), False, golden_test_patch)
    log_text += "git apply <golden test patch>\n"
    if returncode != 0:
        print("git apply <golden test patch>", "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    print("git apply <golden code patch>", "...")
    returncode, logs = run_with_realtime_output(["git", "apply", "-"], str(tmp_repo_path), False, golden_code_patch)
    log_text += "git apply <golden code patch>\n"
    if returncode != 0:
        print("git apply <golden code patch>", "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    return True, log_text


def verify_all_instances(all_instances, base_path, save_path, ori_repo_path, tmp_repo_path):
    if not os.path.exists(ori_repo_path):
        print(f"Project path not found: {ori_repo_path}\n")
        exit(1)

    if os.path.exists(tmp_repo_path):
        cmd = f"rm -rf {tmp_repo_path}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd, str(os.path.join(base_path, "codebases")), True)
        if returncode != 0:
            print(cmd, "❌")
            exit(1)

    cmd = f"cp -r {ori_repo_path} {tmp_repo_path}"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(os.path.join(base_path, "codebases")), True)
    if returncode != 0:
        print(cmd, "❌")
        exit(1)

    new_all_instances = []
    for instance in tqdm(all_instances):
        modified_files = instance["modification"].keys()
        flag = True
        for modified_file in modified_files:
            if "/test/" in modified_file or "/unittests/" in modified_file:
                continue
            if modified_file.split(".")[-1] not in ["c", "h", "cpp", "hpp"]:
                flag = False
                break
        if flag:
            result, log_text = verify_one_instance(instance, base_path, ori_repo_path, tmp_repo_path)
            if result == True:
                new_all_instances.append(instance)
        print("# Instances", len(new_all_instances))
    return new_all_instances


def filter_clang_llvm(all_instances):
    new_all_instances = []
    for instance in tqdm(all_instances):
        modified_files = instance["modification"].keys()
        flag = True
        for modified_file in modified_files:
            if "/test/" in modified_file or "/unittests/" in modified_file:
                continue
            if modified_file.startswith("llvm/"):
                continue
            elif modified_file.startswith("clang/"):
                continue
            else:
                flag = False
                break
        if flag:
            new_all_instances.append(instance)
        print("# Instances", len(new_all_instances))

    return new_all_instances


if __name__ == "__main__":
    base_path = "../"
    ori_repo_path = os.path.join(base_path, "codebases/llvm-project-ori/")
    tmp_repo_path = os.path.join(base_path, "codebases/llvm-project-tmp/")
    all_instances_path = os.path.join(base_path, "collection/all_instances_1.jsonl")
    save_path = os.path.join(base_path, "collection/")

    all_instances = read_all_instances(all_instances_path)
    print("# Ori Commits", len(all_instances))

    if not os.path.exists("./all_instances_2.jsonl"):
        new_all_instances = verify_all_instances(all_instances, base_path, save_path, ori_repo_path, tmp_repo_path)
        print("# Instances", len(new_all_instances))
        with open("./all_instances_2.jsonl", "w", encoding="utf-8") as f:
            for item in new_all_instances:
                f.write(json.dumps(item) + "\n")

    all_instances = read_all_instances("./all_instances_2.jsonl")
    new_all_instances = filter_clang_llvm(all_instances)
    print("# Instances", len(new_all_instances))
    with open("./all_instances_3.jsonl", "w", encoding="utf-8") as f:
        for item in new_all_instances:
            f.write(json.dumps(item) + "\n")