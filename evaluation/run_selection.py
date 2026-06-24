import os
import io
import re
import json
import time
import tokenize
import argparse
import traceback
from tqdm import tqdm
import multiprocessing
from unidiff import PatchSet
from agent import SelectorAgent, RandomSelector


class Candidate:
    def __init__(self, fix_commit_id, issue, patch, apply, build, check):
        self.fix_commit_id = fix_commit_id
        self.issue = issue
        self.patch = patch
        self.apply = apply
        self.build = build
        self.check = check


def read_candidates(path, candidate_ids):
    all_candidates = json.loads(open(path, "r").read())
    candidates_dict = {}
    for candidate_id in candidate_ids:
        candidate = all_candidates[candidate_id]
        for instance in candidate:
            can = Candidate(fix_commit_id=instance["fix_commit_id"],
                            issue=instance["issue"],
                            patch=instance["patch"],
                            apply=instance["apply"],
                            build=instance["build"],
                            check=instance["check"])
            if instance["fix_commit_id"] not in candidates_dict.keys():
                candidates_dict[instance["fix_commit_id"]] = [can]
            else:
                candidates_dict[instance["fix_commit_id"]].append(can)

    candidates = list(candidates_dict.values())

    return candidates


def remove_comments_from_line(line: str) -> str:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(line).readline)
        result_parts = []
        prev_end = (0, 0)

        for tok_type, tok_str, tok_start, tok_end, _ in tokens:
            if tok_type == tokenize.COMMENT:
                break
            (srow, scol) = tok_start
            if srow == 1 and scol > prev_end[1]:
                result_parts.append(line[prev_end[1]:scol])
            result_parts.append(tok_str)
            prev_end = tok_end

        return ''.join(result_parts).rstrip()
    except tokenize.TokenError:
        if '//' in line:
            return line.split('//', 1)[0].rstrip()
        return line


def clean_patch(ori_patch_text):
    patch = PatchSet(ori_patch_text)
    extracted_lines = []
    delete_lines = []
    add_lines = []
    for patched_file in patch:
        for hunk in patched_file:
            for line in hunk:
                if line.is_added:
                    content = line.value.lstrip('+')
                    if content.strip() and not re.match(r'^\s*//', content):
                        content = remove_comments_from_line(content.rstrip())
                        extracted_lines.append('+' + content)
                        add_lines.append(content)
                elif line.is_removed:
                    content = line.value.lstrip('-')
                    if content.strip() and not re.match(r'^\s*//', content):
                        content = remove_comments_from_line(content.rstrip())
                        extracted_lines.append('-' + content)
                        delete_lines.append(content)
    new_patch_text = '\n'.join(extracted_lines)
    new_patch_text = re.sub(r'\s+', '', new_patch_text)

    return new_patch_text


def select_one_instance(ori_candidate_list, shared_data, lock):
    time0 = time.time()
    fix_commit_id = ori_candidate_list[0].fix_commit_id
    issue_description = ori_candidate_list[0].issue
    save_result_filename = os.path.join(args.save_path_result, f"{fix_commit_id}.log")

    if not os.path.exists(save_result_filename):
        with lock:
            pass

        if args.selector == "random":
            selector = RandomSelector(args)
            try:
                patch, check_result, log, usage = selector.run(ori_candidate_list, issue_description, fix_commit_id, shared_data.num_done)
            except Exception as e:
                patch = ori_candidate_list[0].patch
                check_result = ori_candidate_list[0].check
                log = str(traceback.format_exc())
                usage = []
            usage.append({"time": time.time() - time0})
            open(save_result_filename, "w", encoding="utf-8").write(
                "<patch>\n" + patch.strip() + "\n</patch>\n\n<check_result>\n" + str(
                    check_result) + "\n</check_result>\n\n<message>\n" + log.strip() + "\n</message>\n\n<usage>\n" + json.dumps(
                    usage, indent=4).strip() + "\n</usage>")

            with lock:
                shared_data.num_done += 1
            return

        candidate_list = []
        for candidate in ori_candidate_list:
            if (not candidate.apply) or (not candidate.build):
                continue
            candidate_list.append(candidate)

        if len(candidate_list) == 0:
            usage = []
            patch = ori_candidate_list[0].patch
            check_result = ori_candidate_list[0].check
            log = ""
        elif len([_ for _ in candidate_list if _.check]) == 0:
            usage = []
            patch = candidate_list[0].patch
            check_result = candidate_list[0].check
            log = ""
        else:
            if args.selector == "llvm-sel":
                new_candidate_list = []
                patch_set = []
                for candidate in candidate_list:
                    try:
                        tmp_patch = clean_patch(candidate.patch)
                    except Exception as e:
                        tmp_patch = re.sub(r'\s+', '', candidate.patch)
                    if tmp_patch not in patch_set:
                        patch_set.append(tmp_patch)
                        new_candidate_list.append(candidate)
                candidate_list = new_candidate_list

                selector = SelectorAgent(args)
                try:
                    patch, check_result, log, usage = selector.run(candidate_list, issue_description, fix_commit_id, shared_data.num_done)
                except Exception as e:
                    patch = candidate_list[0].patch
                    check_result = candidate_list[0].check
                    log = str(traceback.format_exc())
                    usage = []
            else:
                raise NotImplementedError

            usage.append({"time": time.time() - time0})
            open(save_result_filename, "w", encoding="utf-8").write(
                "<patch>\n" + patch.strip() + "\n</patch>\n\n<check_result>\n" + str(
                    check_result) + "\n</check_result>\n\n<message>\n" + log.strip() + "\n</message>\n\n<usage>\n" + json.dumps(
                    usage, indent=4).strip() + "\n</usage>")

            with lock:
                shared_data.num_done += 1
    else:
        with lock:
            shared_data.num_done += 1


def worker(task_queue, done_queue, shared_data, lock):
    while True:
        task = task_queue.get()
        if task is None:
            break
        instance, index = task
        select_one_instance(instance, shared_data, lock)
        done_queue.put(1)


def select_all_instances(all_candidates):
    if not os.path.exists(args.save_path_result):
        os.makedirs(args.save_path_result)

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
    for i in range(len(all_candidates)):
        tasks.append((all_candidates[i], i + 1))

    for task in tasks:
        task_queue.put(task)

    for _ in range(args.num_processes):
        task_queue.put(None)

    pbar = tqdm(total=len(all_candidates), ascii=True)
    for _ in range(len(all_candidates)):
        done_queue.get()
        pbar.update(1)
    pbar.close()

    for p in pool:
        p.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="deepseek-chat", help="used LLMs")
    parser.add_argument("--candidate", type=str, help="[bm25, oracle, agent, all]")
    parser.add_argument("--selector", type=str, default="llvm-sel", help="[random, llvm-sel]")
    parser.add_argument("--num_processes", type=int, default=1)
    args = parser.parse_args()

    assert args.candidate in ["bm25", "oracle", "agent", "all"]
    if args.candidate == "bm25":
        args.candidate_ids = []
        for model in ["deepseek-chat", "qwen3-coder-plus", "google/gemini-3-flash-preview", "x-ai/grok-code-fast-1"]:
            for retrieval in ["bm25"]:
                for retrieval_length in ["13000", "27000", "50000"]:
                    args.candidate_ids.append(f"{model.replace('/', '-')}-{retrieval}-{retrieval_length}")
    elif args.candidate == "oracle":
        args.candidate_ids = []
        for model in ["deepseek-chat", "qwen3-coder-plus", "google/gemini-3-flash-preview", "x-ai/grok-code-fast-1"]:
            for retrieval in ["oracle"]:
                for retrieval_length in ["13000", "27000", "50000"]:
                    args.candidate_ids.append(f"{model.replace('/', '-')}-{retrieval}-{retrieval_length}")
    elif args.candidate == "agent":
        args.candidate_ids = []
        for agent in ["swe-agent", "trae-agent", "live-swe-agent"]:
            for model in ["deepseek-chat", "qwen3-coder-plus", "google/gemini-3-flash-preview", "x-ai/grok-code-fast-1"]:
                args.candidate_ids.append(f"{agent}-{model.replace('/', '-')}")
    elif args.candidate == "all":
        args.candidate_ids = []
        for model in ["deepseek-chat", "qwen3-coder-plus", "google/gemini-3-flash-preview", "x-ai/grok-code-fast-1"]:
            for retrieval in ["bm25", "oracle"]:
                for retrieval_length in ["13000", "27000", "50000"]:
                    args.candidate_ids.append(f"{model.replace('/', '-')}-{retrieval}-{retrieval_length}")
        for agent in ["swe-agent", "trae-agent", "live-swe-agent"]:
            for model in ["deepseek-chat", "qwen3-coder-plus", "google/gemini-3-flash-preview", "x-ai/grok-code-fast-1"]:
                args.candidate_ids.append(f"{agent}-{model.replace('/', '-')}")
    else:
        raise ValueError(f"Unknown candidate: {args.candidate}")

    args.api_key = "sk-xxxxxx"
    args.base_url = "https://openrouter.ai/api/v1"
    
    args.base_path = "../"
    if args.selector == "random":
        args.save_id = f"{args.selector}-{args.candidate}"
    elif args.selector == "llvm-sel":
        args.save_id = f"{args.selector}-{args.model.replace('/', '-')}-{args.candidate}"
    else:
        raise ValueError(f"Unknown selector: {args.selector}")
    args.save_path_result = os.path.join(args.base_path, f"result_selection/{args.save_id}/")
    args.max_retries = 10
    args.temperature = 0
    args.max_tokens = 8192

    all_candidates = read_candidates("../dataset/candidates.jsonl", args.candidate_ids)
    select_all_instances(all_candidates)
