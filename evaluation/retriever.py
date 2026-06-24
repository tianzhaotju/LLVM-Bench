import os
import json
import time
import tiktoken
import argparse
from tqdm import tqdm
from pathlib import Path
from typing import List, Tuple
from rank_bm25 import BM25Okapi
from utils import run_with_realtime_output, read_all_instances

class BM25Retriever:
    def __init__(self):
        self.file_extension_whitelist = [".c", ".cpp", ".h", ".hpp", ".ll"]

    def retrieve_files(self, repo_root: str, query: str, max_token_list: list):
        files = self.list_repo_files(repo_root)
        files = [_ for _ in files if ('/llvm-project-tmp/llvm/' in str(_)) or ('/llvm-project-tmp/clang/' in str(_))]
        files = [_ for _ in files if ('/llvm-project-tmp/llvm/test/' not in str(_)) and \
                 ('/llvm-project-tmp/clang/test/' not in str(_)) and \
                 ('/llvm-project-tmp/llvm/unittests/' not in str(_)) and \
                 ('/llvm-project-tmp/clang/unittests/' not in str(_))]

        if not files:
            return []
        time0 = time.time()
        bm25 = self.build_index(files, repo_root=repo_root)
        time1 = time.time()
        query_tokens = self.tokenize(query)
        scores = bm25.get_scores(query_tokens)
        time2 = time.time()

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )

        all_retrieval_results = {}
        for max_token in max_token_list:
            selected: List[Tuple[str, str]] = []
            total_tokens = 0
            for idx in ranked_indices:
                if total_tokens >= max_token:
                    break

                path = files[idx]
                try:
                    content = open(path, "r", encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                if not content:
                    continue

                rel_path = os.path.relpath(path, repo_root)

                remaining = max_token - total_tokens
                token_num = self.count_tokens(str(rel_path)+"\n"+content)

                if token_num <= remaining:
                    selected.append((str(rel_path), content))
                    total_tokens += token_num
                    continue

                truncated = self.approx_truncate_to_tokens(str(rel_path)+"\n"+content, remaining)
                if not truncated.strip():
                    continue

                selected.append((rel_path, truncated))
                total_tokens += self.count_tokens(truncated)
                break
            all_retrieval_results[max_token] = selected

        return all_retrieval_results

    def list_repo_files(self, repo_root: str):
        files = []
        for p in Path(repo_root).rglob("*"):
            if not p.is_file():
                continue

            if p.suffix.lower() not in self.file_extension_whitelist:
                continue

            files.append(str(p))
        return files

    def build_index(self, files: List[str], repo_root: str):
        docs = []
        for f in files:
            rel_path = os.path.relpath(f, repo_root)
            try:
                content = open(f, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                content = ""
            text = f"{rel_path}\n{content}"
            toks = self.tokenize(text) or [""]
            docs.append(toks)
        return BM25Okapi(docs)

    def tokenize(self, code: str):
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(code)
        return [enc.decode([t]) for t in tokens]

    def count_tokens(self, code: str):
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(code))

    def approx_truncate_to_tokens(self, code: str, token_budget: int):
        if token_budget <= 0:
            return ""

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(code)
        if len(tokens) <= token_budget:
            return code

        truncated = tokens[:token_budget]
        return enc.decode(truncated) + "\n\n/* ...truncated... */\n"


class OracleRetriever:
    def __init__(self):
        self.file_extension_whitelist = [".c", ".cpp", ".h", ".hpp", ".ll"]

    def retrieve_files(self, modification: list, repo_root: str, query: str, max_token_list: list):
        files = modification
        if not files:
            return []

        time0 = time.time()
        bm25 = self.build_index(files, repo_root=repo_root)
        time1 = time.time()
        query_tokens = self.tokenize(query)
        scores = bm25.get_scores(query_tokens)
        time2 = time.time()

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )

        all_retrieval_results = {}
        for max_token in max_token_list:
            selected: List[Tuple[str, str]] = []
            total_tokens = 0
            for idx in ranked_indices:
                if total_tokens >= max_token:
                    break

                path = files[idx]
                try:
                    content = open(path, "r", encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                if not content:
                    continue

                rel_path = os.path.relpath(path, repo_root)

                remaining = max_token - total_tokens
                token_num = self.count_tokens(str(rel_path)+"\n"+content)

                if token_num <= remaining:
                    selected.append((str(rel_path), content))
                    total_tokens += token_num
                    continue

                truncated = self.approx_truncate_to_tokens(str(rel_path)+"\n"+content, remaining)
                if not truncated.strip():
                    continue

                selected.append((rel_path, truncated))
                total_tokens += self.count_tokens(truncated)
                break
            all_retrieval_results[max_token] = selected

        return all_retrieval_results

    def list_repo_files(self, repo_root: str):
        files = []
        for p in Path(repo_root).rglob("*"):
            if not p.is_file():
                continue

            if p.suffix.lower() not in self.file_extension_whitelist:
                continue

            files.append(str(p))
        return files

    def build_index(self, files: List[str], repo_root: str):
        docs = []
        for f in files:
            rel_path = os.path.relpath(f, repo_root)
            try:
                content = open(f, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                content = ""
            text = f"{rel_path}\n{content}"
            toks = self.tokenize(text) or [""]
            docs.append(toks)
        return BM25Okapi(docs)

    def tokenize(self, code: str):
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(code)
        return [enc.decode([t]) for t in tokens]

    def count_tokens(self, code: str):
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(code))

    def approx_truncate_to_tokens(self, code: str, token_budget: int):
        if token_budget <= 0:
            return ""

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(code)
        if len(tokens) <= token_budget:
            return code

        truncated = tokens[:token_budget]
        return enc.decode(truncated) + "\n\n/* ...truncated... */\n"


def get_bm25_retrieval():
    base_path = "../"
    ori_repo_path = os.path.join(base_path, "codebases/llvm-project-ori/")
    tmp_repo_path = os.path.join(base_path, "codebases/llvm-project-tmp/")
    save_path = os.path.join(base_path, f"evaluation/retrieval/{args.retrieval}/")
    all_instances_path = os.path.join(base_path, "dataset/compiler_bench.jsonl")

    all_instances = read_all_instances(all_instances_path)
    max_token_list = [13000, 27000, 50000]

    bm25_retriever = BM25Retriever()
    for instance in tqdm(all_instances):
        query = instance["issue_title"] + "\n" + instance["issue_body"]
        bug_commit_id = instance["bug_commit_id"]
        fix_commit_id = instance["fix_commit_id"]

        if os.path.exists(os.path.join(save_path, fix_commit_id+".jsonl")):
            all_retrieval_results = json.loads(open(os.path.join(save_path, fix_commit_id+".jsonl")).read())
            continue

        cmd = f"git checkout {bug_commit_id}"
        returncode, _ = run_with_realtime_output(cmd, str(tmp_repo_path), True)
        if returncode != 0:
            print(cmd, "❌")
            exit()

        all_retrieval_results = bm25_retriever.retrieve_files(tmp_repo_path, query, max_token_list)
        open(os.path.join(save_path, fix_commit_id+".jsonl"), "w", encoding="utf-8").write(json.dumps(all_retrieval_results))


def get_oracle_retrieval():
    base_path = "../"
    ori_repo_path = os.path.join(base_path, "codebases/llvm-project-ori/")
    tmp_repo_path = os.path.join(base_path, "codebases/llvm-project-tmp/")
    save_path = os.path.join(base_path, f"evaluation/retrieval/{args.retrieval}/")
    all_instances_path = os.path.join(base_path, "dataset/compiler_bench.jsonl")

    all_instances = read_all_instances(all_instances_path)
    max_token_list = [13000, 27000, 50000]

    oracle_retriever = OracleRetriever()
    for instance in tqdm(all_instances):
        query = instance["issue_title"] + "\n" + instance["issue_body"]
        bug_commit_id = instance["bug_commit_id"]
        fix_commit_id = instance["fix_commit_id"]
        modification = list(instance["modification"].keys())
        modification = [_ for _ in modification if (not _.startswith("clang/test/")) and \
                        (not _.startswith("clang/unittests/")) and \
                        (not _.startswith("llvm/test/")) and \
                        (not _.startswith("llvm/unittests/"))]
        modification = [os.path.join(tmp_repo_path, _) for _ in modification]

        if os.path.exists(os.path.join(save_path, fix_commit_id + ".jsonl")):
            all_retrieval_results = json.loads(open(os.path.join(save_path, fix_commit_id + ".jsonl")).read())
            continue

        cmd = f"git checkout {bug_commit_id}"
        returncode, _ = run_with_realtime_output(cmd, str(tmp_repo_path), True)
        if returncode != 0:
            print(cmd, "❌")
            exit()


        all_retrieval_results = oracle_retriever.retrieve_files(modification, tmp_repo_path, query, max_token_list)
        open(os.path.join(save_path, fix_commit_id + ".jsonl"), "w", encoding="utf-8").write(json.dumps(all_retrieval_results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval", type=str, required=True, help="bm25 or oracle")
    args = parser.parse_args()
    if args.retrieval == "bm25":
        get_bm25_retrieval()
    elif args.retrieval == "oracle":
        get_oracle_retrieval()
    else:
        print("Please choose '--retrieval' between bm25 or oracle")