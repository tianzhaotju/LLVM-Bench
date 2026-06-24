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


def build_project(instance, log_text, base_path, tmp_repo_path):
    print("bug_commit_id", instance["bug_commit_id"])
    print("fix_commit_id", instance["fix_commit_id"])
    if os.path.exists(os.path.join(tmp_repo_path, "build")):
        cmd = f"rm -rf {str(os.path.join(tmp_repo_path, 'build'))}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd, str(tmp_repo_path), True)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

    cmd = f"mkdir {str(os.path.join(tmp_repo_path, 'build'))}"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(tmp_repo_path), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs+ "\n"

    cmake_path = os.path.join(base_path, "config/cmake-4.2.0-linux-x86_64/bin/cmake")
    cmd = f"""{cmake_path} -G Ninja ../llvm \
        -DLLVM_ENABLE_PROJECTS=clang\;llvm \
        -DLLVM_TARGETS_TO_BUILD="X86" \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLVM_ENABLE_ASSERTIONS=ON \
        -DCLANG_ENABLE_NVPTX=OFF \
        -DCLANG_ENABLE_AMDGPU=OFF \
        -DPython3_EXECUTABLE=$(which python3);"""
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(os.path.join(tmp_repo_path, 'build')), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    cmake_path = os.path.join(base_path, "config/cmake-4.2.0-linux-x86_64/bin/cmake")
    cmd = f"{cmake_path} --build . -- -j32;"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(os.path.join(tmp_repo_path, 'build')), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    return True, log_text


def check_project(instance, log_text, base_path, tmp_repo_path):
    print("bug_commit_id", instance["bug_commit_id"])
    print("fix_commit_id", instance["fix_commit_id"])
    if not os.path.exists(os.path.join(tmp_repo_path, "build")):
        result, log_text = build_project(instance, log_text, base_path, tmp_repo_path)
        if result == False:
            return False, log_text

    del_tests = [str(os.path.join(tmp_repo_path, "clang/test/Driver/gpu-libc.c")),
                 str(os.path.join(tmp_repo_path, "clang/test/Driver/gpu-libc-headers.c")),
                 str(os.path.join(tmp_repo_path, "llvm/test/tools/llvm-ar/error-opening-permission.test")),
                 str(os.path.join(tmp_repo_path, "llvm/test/tools/llvm-dwarfdump/X86/output.s")),
                 str(os.path.join(tmp_repo_path, "llvm/test/tools/llvm-ifs/fail-file-write.test")),
                 str(os.path.join(tmp_repo_path, "llvm/test/tools/llvm-ranlib/error-opening-permission.test")),
                 str(os.path.join(tmp_repo_path, "tools/llvm-reduce/parallel-workitem-kill.ll")),
                 ]
    for del_test in del_tests:
        if os.path.exists(del_test):
            cmd = f"rm {del_test}"
            print(cmd, "...")
            returncode, logs = run_with_realtime_output(cmd, str(os.path.join(tmp_repo_path, 'build')), True)
            log_text += cmd + "\n"
            if returncode != 0:
                print(cmd, "❌")
                return False, log_text + logs
            else:
                log_text += logs + "\n"

    cmake_path = os.path.join(base_path, "config/cmake-4.2.0-linux-x86_64/bin/cmake")
    cmd = f"{cmake_path} --build . --target check-all -- -j32"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(os.path.join(tmp_repo_path, 'build')), True)
    log_text += cmd + "\n"
    if returncode != 0:
        print(cmd, "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    return True, log_text


def verify_one_instance(instance, base_path, ori_repo_path, tmp_repo_path):
    log_text = ""
    bug_commit_id = instance["bug_commit_id"]
    golden_code_patch = instance["golden_code_patch"]
    golden_test_patch = instance["golden_test_patch"]

    if not os.path.exists(ori_repo_path):
        log_text += f"Project path not found: {ori_repo_path}\n"
        return False, log_text

    if os.path.exists(tmp_repo_path):
        cmd = f"rm -rf {tmp_repo_path}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd, str(os.path.join(base_path, "codebases")), True)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

    cmd = f"cp -r {ori_repo_path} {tmp_repo_path}"
    print(cmd, "...")
    returncode, logs = run_with_realtime_output(cmd, str(os.path.join(base_path, "codebases")), True)
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

    returncode, log_text = build_project(instance, log_text, base_path, tmp_repo_path)
    if returncode == False:
        return False, log_text
    returncode, log_text = check_project(instance, log_text, base_path, tmp_repo_path)

    if returncode == True and len(re.findall(r"Failed Tests\s*\(\s*\d+\s*\)\s*:", log_text)) == 0:
        log_text += f"Returncode: {returncode}. Reproduction failed.\n"
        print(f"Returncode: {returncode}. Reproduction failed.", "❌")
        return False, log_text

    print("git apply <golden code patch>", "...")
    returncode, logs = run_with_realtime_output(["git", "apply", "-"], str(tmp_repo_path), False, golden_code_patch)
    log_text += "git apply <golden code patch>\n"
    if returncode != 0:
        print("git apply <golden code patch>", "❌")
        return False, log_text + logs
    else:
        log_text += logs + "\n"

    returncode, log_text = build_project(instance, log_text, base_path, tmp_repo_path)
    if returncode == False:
        return False, log_text
    returncode, log_text = check_project(instance, log_text, base_path, tmp_repo_path)

    if returncode == False or len(re.findall(r"Failed Tests\s*\(\s*\d+\s*\)\s*:", log_text)) == 2:
        log_text += f"Returncode: {returncode}. Repair failed.\n"
        print(f"Returncode: {returncode}. Repair failed.", "❌")
        return False, log_text

    log_text += "\nReproduction & Repair success.\n"
    return True, log_text

def verify_all_instances(all_instances, base_path, save_path, ori_repo_path, tmp_repo_path, selected_version_number, fail_instances):
    success_verified_instances = {}
    for version in selected_version_number.keys():
        success_verified_instances[version] = 0

    if not os.path.exists(save_path):
        os.makedirs(save_path)

    new_all_instances = []
    new_all_instances_num = {21: 0, 20: 0, 19: 0, 18: 0}
    for instance in all_instances:
        if new_all_instances_num[instance["version"]] < selected_version_number[instance["version"]]:
            tmp = ['7ba3c55d91dcd7da5a5eb1c58225f648fb38b740', '3706dfef660097f24fb5efbac0d7f14b424492ed', '7aed53eb1982113e825534f0f66d0a0e46e7a5ed', 'd2047242e6d0f0deb7634ff22ab164354c520c79', 'fe58eee60200c91b5b4131e9dc73a5e870b3cf4d', '88b1d16c4a040cc3d919be13f0baf44f30a5aa13']
            if instance["fix_commit_id"] in tmp:
                new_all_instances.append(instance)
                new_all_instances_num[instance["version"]] += 1
    all_instances = new_all_instances

    for instance in tqdm(all_instances):
        fix_commit_id = instance["fix_commit_id"]

        if fix_commit_id in fail_instances:
            continue

        if os.path.exists(os.path.join(save_path, fix_commit_id)):
            continue

        if success_verified_instances[instance["version"]] >= selected_version_number[instance["version"]]:
            continue

        result, log_text = verify_one_instance(instance, base_path, ori_repo_path, tmp_repo_path)
        open(os.path.join(save_path, fix_commit_id), "w", encoding="utf-8").write("<start>"+str(result)+"<end>\n"+log_text)
        if result == True:
            success_verified_instances[instance["version"]] += 1
            print(f"✅ {fix_commit_id}")
        else:
            print(f"❌ {fix_commit_id}")

        print("# Instances: ", success_verified_instances)


if __name__ == "__main__":
    base_path = "../"
    ori_repo_path = os.path.join(base_path, "codebases/llvm-project-ori/")
    tmp_repo_path = os.path.join(base_path, "codebases/llvm-project-tmp/")
    all_instances_path = os.path.join(base_path, "collection/all_instances_3.jsonl")
    save_path = os.path.join(base_path, "collection/log/exec-1")

    selected_version_number = {21: 10000,
                               20: 0,
                               19: 0,
                               18: 0}
    fail_instances = [_ for _ in open(os.path.join(base_path, "collection/fail_instances"), "r").readlines() if not _.strip()]

    all_instances = read_all_instances(all_instances_path)
    print("# Ori Commits", len(all_instances))

    verify_all_instances(all_instances, base_path, save_path, ori_repo_path, tmp_repo_path, selected_version_number, fail_instances)
