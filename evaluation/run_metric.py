import os
import json
import argparse
import numpy as np
from typing import List
from run_evaluation import parse_patch
from utils import read_all_instances, parse_content


def evaluate_all_instances(all_instances: List[dict]):
    all_metrics = {"apply": [], "build": [], "check": [], "test_time": [],
                   "prompt_tokens": [], "completion_tokens": [], "generation_time": [],
                   "apply_instances": [], "build_instances": [], "check_instances": []}

    for instance in all_instances:
        fix_commit_id = instance["fix_commit_id"]
        save_result_filename = os.path.join(args.save_path_result, f"{fix_commit_id}.log")
        save_log_filename = os.path.join(args.save_path_log, f"{fix_commit_id}.log")
        save_patch_filename = os.path.join(args.save_path_patch, f"{fix_commit_id}.patch")
        if (not os.path.exists(save_result_filename)) or (not os.path.exists(save_log_filename)):
            continue

        ori_patch = open(save_patch_filename, "r", encoding="utf-8").read()
        try:
            patch = parse_patch(ori_patch, ["```code", "```"])
        except:
            patch = ""
        if not patch:
            print(f"❌ Could not parse patch! ({save_patch_filename})")

        result = open(save_result_filename, "r", encoding="utf-8").read()
        result = json.loads(parse_content(result, ["<result>", "</result>"]))

        for metric in ["apply", "build", "check"]:
            if result[metric]:
                all_metrics[metric].append(1)
                all_metrics[metric+"_instances"].append(fix_commit_id)
            else:
                all_metrics[metric].append(0)
        all_metrics["test_time"].append(result["time"])

        log_text = open(save_log_filename, "r", encoding="utf-8").read()
        log_text = json.loads(parse_content(log_text, ["<usage>", "</usage>"]))
        if not log_text:
            continue

        prompt_tokens, completion_tokens, generation_time = 0, 0, 0
        for tmp in log_text:
            if "prompt_tokens" in tmp.keys():
                prompt_tokens += tmp["prompt_tokens"]
            if "completion_tokens" in tmp.keys():
                completion_tokens += tmp["completion_tokens"]
            if "time" in tmp.keys():
                generation_time += tmp["time"]
        all_metrics["prompt_tokens"].append(prompt_tokens)
        all_metrics["completion_tokens"].append(completion_tokens)
        all_metrics["generation_time"].append(generation_time)

    print(f"Count: {len(all_metrics['apply'])} / {len(all_metrics['prompt_tokens'])} / {len(all_instances)}")
    all_num = len(all_instances)
    print(f"Apply@1: {round(np.sum(all_metrics['apply'])/all_num*100,2)}%")
    print(f"Build@1: {round(np.sum(all_metrics['build'])/all_num*100,2)}%")
    print(f"Pass@1: {round(np.sum(all_metrics['check'])/all_num*100,2)}%")
    print(f"Input Tokens: {round(np.average(all_metrics['prompt_tokens']),2)}")
    print(f"Output Tokens: {round(np.average(all_metrics['completion_tokens']),2)}")
    print(f"Generation Time: {round(np.average(all_metrics['generation_time']),2)}")
    print(f"Test Time: {round(np.average(all_metrics['test_time']),2)}")


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

    args.all_instances_path = "../dataset/compiler_bench.jsonl"
    if args.mode == "llm":
        args.save_id = f"{args.model.replace('/', '-')}-{args.retrieval}-{args.retrieval_length}"
    elif args.mode == "agent":
        args.save_id = f"{args.agent}-{args.model.replace('/', '-')}"
    args.save_path_result = f"../result/{args.save_id}/"
    args.save_path_log = f"../log/{args.save_id}/"
    args.save_path_patch = f"../patch/{args.save_id}/"

    all_instances = read_all_instances(args.all_instances_path)
    evaluate_all_instances(all_instances)
