import os
import json
import time
import argparse
import traceback
import multiprocessing
from tqdm import tqdm
from typing import List
from llm import LLMCoder
from utils import read_all_instances
from agent import SWEAgentCoder, LiveSWEAgentCoder,TraeAgentCoder


def generate_one_instance(instance, shared_data, lock):
    time0 = time.time()
    fix_commit_id = instance["fix_commit_id"]
    save_patch_filename = os.path.join(args.save_path_patch, f"{fix_commit_id}.patch")
    save_log_filename = os.path.join(args.save_path_log, f"{fix_commit_id}.log")

    if not os.path.exists(save_patch_filename):
        with lock:
            print(f">>> ", shared_data.num_done, fix_commit_id)
        issue_description = instance["issue_title"] + "\n" + instance["issue_body"]
        bug_commit_id = instance["bug_commit_id"]
        if args.mode == "llm":
            context_path = os.path.join(args.base_path, f"evaluation/retrieval/{args.retrieval}/{instance['fix_commit_id']}.jsonl")
            context_list = json.loads(open(context_path, "r").read())[args.retrieval_length]
            context = ""
            for idx in range(len(context_list)):
                context += f"Related Code {idx+1}:\n{context_list[idx][0].strip()}\n{context_list[idx][1].strip(context_list[idx][0].strip()).strip()}\n"

        if args.mode == "llm":
            coder = LLMCoder(args)
            try:
                patch, log, usage = coder.run(issue_description, context)
            except Exception as e:
                error_message = traceback.format_exc()
                patch = str(error_message)
                log = str(error_message)
                usage = [{"error": str(error_message)}]
        elif args.mode == "agent":
            tmp_repo_path = os.path.join(args.base_path, f"codebases/llvm-project-tmp-{fix_commit_id}/")
            if args.agent == "swe-agent":
                coder = SWEAgentCoder(args, tmp_repo_path)
            elif args.agent == "trae-agent":
                coder = TraeAgentCoder(args, tmp_repo_path)
            elif args.agent == "live-swe-agent":
                coder = LiveSWEAgentCoder(args, tmp_repo_path)
            else:
                print("Unknown agent")
                exit()
            try:
                patch, log, usage = coder.run(issue_description, bug_commit_id, fix_commit_id, shared_data.num_done)
            except Exception as e:
                error_message = traceback.format_exc()
                patch = str(error_message)
                log = str(error_message)
                usage = [{"error": str(error_message)}]
        else:
            print("Unknown mode")
            exit()

        if patch:
            usage.append({"time": time.time() - time0})
            open(save_patch_filename, "w", encoding="utf-8").write(patch)
            open(save_log_filename, "w", encoding="utf-8").write("<message>\n" + log.strip() + "\n</message>\n\n<usage>\n" + json.dumps(usage, indent=4).strip() + "\n</usage>")
        else:
            print(f"❌ Generated code is null. (fix_commit_id: {fix_commit_id})")
            open(save_log_filename, "w", encoding="utf-8").write("<message>\n" + log.strip() + "\n</message>\n\n<usage>\n" + json.dumps(usage, indent=4).strip() + "\n</usage>")

        with lock:
            shared_data.num_done += 1
            print(f"✅ done: {shared_data.num_done}, {fix_commit_id}")
    else:
        with lock:
            shared_data.num_done += 1


def worker(task_queue, done_queue, shared_data, lock):
    while True:
        task = task_queue.get()
        if task is None:
            break
        instance, index = task
        generate_one_instance(instance, shared_data, lock)
        done_queue.put(1)


def generate_all_instances(all_instances: List[dict]):
    if not os.path.exists(args.save_path_patch):
        os.makedirs(args.save_path_patch)

    if not os.path.exists(args.save_path_log):
        os.makedirs(args.save_path_log)

    manager = multiprocessing.Manager()
    shared_data = manager.Namespace()
    shared_data.num_done = 0
    lock = multiprocessing.Lock()

    task_queue = multiprocessing.Queue()
    done_queue = multiprocessing.Queue()

    pool = []
    for _ in range(args.num_processes):
        p = multiprocessing.Process(target=worker, args=(task_queue, done_queue, shared_data, lock))
        p.start()
        pool.append(p)

    tasks = []
    for i in range(len(all_instances)):
        tasks.append((all_instances[i], i + 1))

    for task in tasks:
        task_queue.put(task)

    for _ in range(args.num_processes):
        task_queue.put(None)

    pbar = tqdm(total=len(all_instances), ascii=True)
    for _ in range(len(all_instances)):
        done_queue.get()
        pbar.update(1)
    pbar.close()

    for p in pool:
        p.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, required=True, help="llm or agent")
    parser.add_argument("--model", type=str, required=True, help="used LLMs")
    parser.add_argument("--agent", type=str, help="used Agent")
    parser.add_argument("--retrieval", type=str, help="bm25 or oracle")
    parser.add_argument("--retrieval_length", type=str, help="[13000, 27000, 50000]")
    parser.add_argument("--num_processes", type=int, default=1)
    args = parser.parse_args()

    assert args.mode in ["llm", "agent"]
    if args.mode == "llm":
        assert args.retrieval == "bm25" or args.retrieval == "oracle"
        assert args.retrieval_length in ["13000", "27000", "50000"]
    elif args.mode == "agent":
        assert args.agent in ["swe-agent", "trae-agent", "live-swe-agent"]

    args.api_key = "sk-xxxxxxx"
    args.base_url = "https://openrouter.ai/api/v1"

    args.base_path = "../"
    args.ori_repo_path = os.path.join(args.base_path, "codebases/llvm-project-ori/")
    args.all_instances_path = os.path.join(args.base_path, "dataset/compiler_bench.jsonl")
    if args.mode == "llm":
        args.save_id = f"{args.model.replace('/', '-')}-{args.retrieval}-{args.retrieval_length}"
    elif args.mode == "agent":
        args.save_id = f"{args.agent}-{args.model.replace('/', '-')}"
    args.save_path_log = os.path.join(args.base_path, f"log/{args.save_id}/")
    args.save_path_patch = os.path.join(args.base_path, f"patch/{args.save_id}/")
    args.max_retries = 10
    args.temperature = 0
    args.max_tokens = 8192
    args.max_turn = 50

    all_instances = read_all_instances(args.all_instances_path)
    generate_all_instances(all_instances)