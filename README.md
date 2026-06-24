# LLVM-Bench

---

## Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Benchmark Format](#benchmark-format)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Environment Setup](#environment-setup)
  - [Verification](#verification)
- [Benchmark Construction](#benchmark-construction)
- [Running Experiments](#running-experiments)
  - [Step 1: Retrieval](#step-1-retrieval)
  - [Step 2: Patch Generation](#step-2-patch-generation)
  - [Step 3: Patch Evaluation](#step-3-patch-evaluation)
  - [Step 4: Metrics Calculation](#step-4-metrics-calculation)
  - [Step 5: Patch Selection (LLVM-Sel)](#step-5-patch-selection-llvm-sel)

---

## Overview

LLVM-Bench is the first large-scale benchmark specifically designed for real-world LLVM compiler issue resolution. Our contributions span four dimensions:

| | Contribution | Description |
|---|-------------|-------------|
| **Benchmark** | **LLVM-Bench** | 423 high-quality, manually validated tasks from real-world LLVM issue resolutions, filling a critical gap in evaluating LLM-based issue resolution on compiler infrastructure. |
| **Platform** | **LLVM-Gym** | A scalable, flexible evaluation platform that automates the full pipeline: issue reproduction, patch application, compiler building, and execution of the LLVM test suite. |
| **Study** | **Empirical Study** | A comprehensive study involving **4 LLMs**, **6 retrieval configurations**, and **3 agents** (36 experimental subjects total). Results reveal limited effectiveness of current techniques on LLVM-Bench, with patch invalidity and syntactic errors as the dominant failure modes. |
| **Technique** | **LLVM-Sel** | A lightweight patch selection framework inspired by strong complementarity among different LLMs and agents. It filters invalid and redundant candidate patches and selects the most promising solution, significantly outperforming any individual technique. |

---

## Project Structure

```
LLVM-Bench/
├── dataset/                    # Benchmark dataset
│   └── compiler_bench.jsonl    # 423 tasks with full metadata
├── collection/                 # Benchmark construction pipeline
│   ├── collection.py           # Collect commits from llvm-project
│   ├── filter.py               # Filter commits by criteria
│   ├── execution.py            # Execution-based filtering
│   ├── manual.py               # Manual validation of tasks
│   ├── collect_issue.py        # Collect GitHub issues
│   └── reformat.py             # Reformat into final benchmark
├── evaluation/                 # Evaluation platform (LLVM-Gym)
│   ├── retriever.py            # BM25 / Oracle retrieval
│   ├── run_generation.py       # Patch generation (LLM / Agent)
│   ├── run_execution.py        # Patch execution & testing
│   ├── run_metric.py           # Metrics computation
│   ├── run_selection.py        # LLVM-Sel / Random selection
│   ├── llm.py                  # LLM-based coder
│   ├── agent.py                # Agent-based coders (SWE-Agent, Trae-Agent, Live-SWE-Agent)
│   ├── cgym.py                 # Compiler Gym environment
│   └── utils.py                # Shared utilities
├── config/                     # Build tool configurations
├── codebases/                  # llvm-project repository (via download.sh)
├── patch/                      # Generated patches
├── log/                        # Evaluation logs
└── result/                     # Evaluation results
```

---

## Benchmark Format

Each task in `dataset/compiler_bench.jsonl` is a JSON object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `repository` | `string` | Repository name (`llvm/llvm-project`) |
| `bug_commit_id` | `string` | Commit hash of the preceding bug state |
| `fix_commit_id` | `string` | Commit hash of the succeeding fix |
| `patch` | `string` | Unified diff patch of the non-test changes in the fix commit |
| `test_patch` | `string` | Unified diff patch of the test changes in the fix commit |
| `commit_message` | `string` | Original commit message of the fix |
| `commit_time` | `string` | Timestamp of the fix commit |
| `module` | `string` | Involved LLVM component (i.e., `front-end`, `back-end`, `mid-end`, and `others`) |
| `modification` | `object` | Per-file modification summary (insertions, deletions, change type) |
| `version` | `string` | LLVM version (i.e., `18`, `19`, `20`, and `21`) |
| `issue_id` | `string` | GitHub issue id |
| `issue_title` | `string` | GitHub issue title |
| `issue_body` | `string` | GitHub issue body (full description) |
| `issue_type` | `string` | Issue category: `Bug Fix`, `Optimization`, or `New Feature` |
| `issue_comment` | `array` | Developer discussion comments |

---

## Quick Start

### Prerequisites

- **OS**: Linux (x86_64)
- **Python**: >= 3.8 (Conda recommended)
- **Build Tools**: CMake 4.2.0, Ninja 1.11.1

### Environment Setup

**1. Install CMake**

```bash
cd ./config/
wget https://github.com/Kitware/CMake/releases/download/v4.2.0/cmake-4.2.0-linux-x86_64.tar.gz
tar zxvf cmake-4.2.0-linux-x86_64.tar.gz
```

**2. Install Ninja**

```bash
cd ./config/
wget https://github.com/ninja-build/ninja/releases/download/v1.11.1/ninja-linux.zip
unzip ninja-linux.zip
chmod +x ninja
mv ninja /usr/local/bin/
mv /opt/conda/bin/ninja /opt/conda/bin/ninja.bak   # if conda ninja exists
which ninja          # should output: /usr/local/bin/ninja
ninja --version      # should output: 1.11.1
```

**3. Create Python Environment**

```bash
conda create -n py38 python=3.8 -y
conda activate py38
pip install psutil tiktoken rank_bm25 openai unidiff GitPython
```

**4. Clone llvm-project**

```bash
cd ./codebases/
sh download.sh
```

### Verification

Verify the build environment works correctly:

```bash
cd ./codebases/llvm-project/
mkdir -p build && cd build

./config/cmake-4.2.0-linux-x86_64/bin/cmake -G Ninja ../llvm \
    -DLLVM_ENABLE_PROJECTS="clang;llvm" \
    -DLLVM_TARGETS_TO_BUILD="X86" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLVM_ENABLE_ASSERTIONS=ON \
    -DCLANG_ENABLE_NVPTX=OFF \
    -DCLANG_ENABLE_AMDGPU=OFF \
    -DPython3_EXECUTABLE=$(which python3)

./config/cmake-4.2.0-linux-x86_64/bin/cmake --build . -- -j32
./config/cmake-4.2.0-linux-x86_64/bin/cmake --build . --target check-all -- -j32
```

---

## Benchmark Construction

The benchmark is constructed through a multi-stage pipeline. Run each script sequentially:

```bash
cd ./collection/

# Stage 1: Collect candidate commits from llvm-project
python collection.py

# Stage 2: Filter commits by quality criteria
python filter.py

# Stage 3: Execution-based filtering (build & test)
python execution.py

# Stage 4: Manual validation of remaining tasks
python manual.py

# Stage 5: Collect associated GitHub issues
python collect_issue.py

# Stage 6: Reformat into the final benchmark format
python reformat.py
```

The final benchmark is output to `dataset/compiler_bench.jsonl`.

---

## Running Experiments

Our experiments cover **4 LLMs** (DeepSeek, Qwen, Gemini, Grok) accessed via [OpenRouter](https://openrouter.ai/), with **6 retrieval configurations** (Sparse / Oracle at 13K / 27K / 50K token lengths) and **3 agent frameworks** (SWE-Agent, Trae-Agent, Live-SWE-Agent).

Set your OpenRouter API key in `evaluation/run_generation.py` under the `api_key` config.

### Step 1: Retrieval

Generate retrieval context for each task:

```bash
cd ./evaluation/

# Sparse retrieval (BM25)
python retriever.py --retrieval=bm25

# Oracle retrieval (ground-truth file locations)
python retriever.py --retrieval=oracle
```

### Step 2: Patch Generation

Generate patches using LLMs directly or via agent frameworks. Example with Gemini:

```bash
# LLM-based patch generation (Sparse retrieval, varying context lengths)
python run_generation.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=13000 --num_processes=1
python run_generation.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=27000 --num_processes=1
python run_generation.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=50000 --num_processes=1

# LLM-based patch generation (Oracle retrieval, varying context lengths)
python run_generation.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=13000 --num_processes=1
python run_generation.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=27000 --num_processes=1
python run_generation.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=50000 --num_processes=1

# Agent-based patch generation
python run_generation.py --mode=agent --agent=swe-agent \
    --model=google/gemini-3-flash-preview --num_processes=1
python run_generation.py --mode=agent --agent=trae-agent \
    --model=google/gemini-3-flash-preview --num_processes=1
python run_generation.py --mode=agent --agent=live-swe-agent \
    --model=google/gemini-3-flash-preview --num_processes=1
```

### Step 3: Patch Evaluation

Execute and test generated patches:

```bash
# Evaluation of LLM-generated patches
python run_execution.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=13000
python run_execution.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=27000
python run_execution.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=50000
python run_execution.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=13000
python run_execution.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=27000
python run_execution.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=50000

# Evaluation of agent-generated patches
python run_execution.py --mode=agent --agent=swe-agent \
    --model=google/gemini-3-flash-preview
python run_execution.py --mode=agent --agent=trae-agent \
    --model=google/gemini-3-flash-preview
python run_execution.py --mode=agent --agent=live-swe-agent \
    --model=google/gemini-3-flash-preview
```

### Step 4: Metrics Calculation

Compute resolution metrics:

```bash
#  Metrics of LLM-generated patches
python run_metric.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=13000
python run_metric.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=27000
python run_metric.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=bm25 --retrieval_length=50000
python run_metric.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=13000
python run_metric.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=27000
python run_metric.py --mode=llm --model=google/gemini-3-flash-preview \
    --retrieval=oracle --retrieval_length=50000

# Metrics of agent-generated patches
python run_metric.py --mode=agent --agent=swe-agent \
    --model=google/gemini-3-flash-preview
python run_metric.py --mode=agent --agent=trae-agent \
    --model=google/gemini-3-flash-preview
python run_metric.py --mode=agent --agent=live-swe-agent \
    --model=google/gemini-3-flash-preview
```

### Step 5: Patch Selection (LLVM-Sel)

Apply LLVM-Sel or Random selection over the candidate patches:

```bash
# LLVM-Sel selection
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=bm25 --selector=llvm-sel --num_processes=1
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=oracle --selector=llvm-sel --num_processes=1
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=agent --selector=llvm-sel --num_processes=1
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=all --selector=llvm-sel --num_processes=1

# Random selection baseline
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=bm25 --selector=random --num_processes=1
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=oracle --selector=random --num_processes=1
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=agent --selector=random --num_processes=1
python run_selection.py --model=google/gemini-3-flash-preview \
    --candidate=all --selector=random --num_processes=1
```

---