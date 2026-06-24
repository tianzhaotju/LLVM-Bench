import os
import re
import time
import json
import argparse
from tqdm import tqdm
from typing import List
from cgym import CompilerGym
from utils import read_all_instances


def parse_patch(input_string, split_word):
    if input_string.find(split_word[0]) != -1:
        begin = input_string.find(split_word[0])
        if input_string.find(split_word[1], begin + 1) != -1:
            pattern = re.compile(fr"{re.escape(split_word[0])}(.*?){re.escape(split_word[1])}", re.DOTALL)
            matches = re.findall(pattern, input_string)
            input_string = matches[-1]

    input_string = input_string.replace(split_word[0], "")
    input_string = input_string.replace(split_word[1], "")

    new_patch = []
    for i in input_string.split("\n"):
        if i.strip() and (not i.startswith("index ")):
            new_patch.append(i)
    output_string = "\n".join(new_patch)

    return output_string


def evaluate_one_instance(generated_patch, instance):
    log_text = ""
    bug_commit_id = instance["bug_commit_id"]
    test_patch = instance["test_patch"]

    compiler_gym = CompilerGym(args)
    is_successful, log_text = compiler_gym.get_project(bug_commit_id, log_text)
    if not is_successful:
        return None, log_text

    is_successful, log_text = compiler_gym.apply_patch(generated_patch, log_text)
    if not is_successful:
        final_result = {"apply": False, "build": False, "check": False}
        return final_result, log_text

    is_successful, log_text = compiler_gym.apply_test_patch(test_patch, log_text)
    if not is_successful:
        final_result = {"apply": False, "build": False, "check": False}
        return final_result, log_text

    is_successful, log_text = compiler_gym.build_project(log_text)
    if is_successful == False:
        final_result = {"apply": True, "build": False, "check": False}
        return final_result, log_text
    is_successful, log_text = compiler_gym.check_project(log_text)

    if is_successful == False and len(re.findall(r"Failed Tests\s*\(\s*\d+\s*\)\s*:", log_text)) > 0:
        log_text += f"Is_successful: {is_successful}. Repair failed.\n"
        print(f"Is_successful: {is_successful}. Repair failed.", "❌")
        final_result = {"apply": True, "build": True, "check": False}
        return final_result, log_text

    final_result = {"apply": True, "build": True, "check": True}
    return final_result, log_text


def evaluate_all_instances(all_instances: List[dict], need_run: List):
    if not os.path.exists(args.save_path_result):
        os.makedirs(args.save_path_result)

    all_patches = {}
    for instance in all_instances:
        fix_commit_id = instance["fix_commit_id"]
        if len(need_run) and fix_commit_id not in need_run:
            continue

        save_patch_filename = os.path.join(args.save_path_patch, f"{fix_commit_id}.patch")
        if not os.path.exists(save_patch_filename):
            print(f"❌ No {save_patch_filename}!")
            exit()

        ori_patch = open(save_patch_filename, "r", encoding="utf-8").read()
        try:
            patch = parse_patch(ori_patch, ["```code", "```"])
        except:
            patch = ""
        if not patch:
            patch = f"❌ Could not parse patch! ({save_patch_filename})"
            print(f"❌ Could not parse patch! ({save_patch_filename})")

        all_patches[fix_commit_id] = patch

    for instance in tqdm(all_instances):
        time0 = time.time()
        fix_commit_id = instance["fix_commit_id"]
        if len(need_run) and fix_commit_id not in need_run:
            continue

        save_result_filename = os.path.join(args.save_path_result, f"{fix_commit_id}.log")
        if os.path.exists(save_result_filename):
            continue

        result, log_text = evaluate_one_instance(all_patches[fix_commit_id], instance)

        if result:
            result["time"] = time.time() - time0
            open(save_result_filename, "w", encoding="utf-8").write("<result>\n"+json.dumps(result, indent=4).strip()+"\n</result>\n\n<log>\n"+log_text.strip()+"\n</log>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, required=True, help="llm or agent")
    parser.add_argument("--model", type=str, required=True, help="used LLMs")
    parser.add_argument("--agent", type=str, help="used Agent")
    parser.add_argument("--retrieval", type=str, help="bm25 or oracle")
    parser.add_argument("--retrieval_length", type=str, help="[13000, 27000, 50000]")
    args = parser.parse_args()

    assert args.mode in ["llm", "agent"]
    if args.mode == "llm":
        assert args.retrieval == "bm25" or args.retrieval == "oracle"
        assert args.retrieval_length in ["13000", "27000", "50000"]
    elif args.mode == "agent":
        assert args.agent in ["swe-agent", "trae-agent", "live-swe-agent"]

    args.base_path = "../"
    args.ori_repo_path = os.path.join(args.base_path, "codebases/llvm-project-ori/")
    args.tmp_repo_path = os.path.join(args.base_path, "codebases/llvm-project-tmp/")
    args.all_instances_path = os.path.join(args.base_path, "dataset/compiler_bench.jsonl")
    if args.mode == "llm":
        args.save_id = f"{args.model.replace('/', '-')}-{args.retrieval}-{args.retrieval_length}"
    elif args.mode == "agent":
        args.save_id = f"{args.agent}-{args.model.replace('/', '-')}"
    args.save_path_patch = os.path.join(args.base_path, f"patch/{args.save_id}/")
    args.save_path_result = os.path.join(args.base_path, f"result/{args.save_id}/")
    need_run = []
    args.if_print = True

    all_instances = read_all_instances(args.all_instances_path)
    evaluate_all_instances(all_instances, need_run)
