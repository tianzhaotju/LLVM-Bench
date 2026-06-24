import os
import re
import time
import json
import random
import tiktoken
import subprocess, signal
from cgym import CompilerGym
from types import SimpleNamespace
from utils import get_llm_response, parse_content, run_with_realtime_output


class SWEAgentCoder:
    def __init__(self, args, tmp_repo_path):
        self.model = args.model
        self.max_retries = args.max_retries
        self.api_key = args.api_key
        self.base_url = args.base_url
        self.temperature = args.temperature
        self.max_tokens = args.max_tokens
        self.max_turn = args.max_turn
        self.ori_repo_path = args.ori_repo_path
        self.base_path = args.base_path
        self.tmp_repo_path = tmp_repo_path
        self.split_word = ["```bash", "```"]
        self.tool_output_token = 1024

    def get_system_prompt(self):
        system_prompt = """You are a helpful assistant that can interact multiple times with a computer shell to solve programming tasks.
Your response must contain exactly ONE bash code block with ONE command (or commands connected with && or ||).

Include a concise THOUGHT section before your command where you explain your reasoning process.
Format your response as shown in <format_example>.

<format_example>
THOUGHT: Your concise reasoning and analysis here

```bash
your_command_here
```
</format_example>

Failure to follow these rules will cause your response to be rejected.
Make sure your answer content is not empty.

Patch Output Requirement: Finally, you'll output the unified diff directly as required.
"""

        return system_prompt

    def get_user_prompt(self, issue_description):
        user_prompt = f"""<pr_description>
Consider the following PR description:
{issue_description}
</pr_description>

<instructions>
# Task Instructions

## Overview
You're a software engineer interacting continuously with a computer by submitting commands.
You'll be helping implement necessary changes to meet requirements in the PR description.
Your task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.

IMPORTANT: This is an interactive process where you will think and issue ONE command, see its result, then think and issue your next command.

For each response:
1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish
2. Provide exactly ONE bash command to execute

## Important Boundaries
- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)
- DO NOT MODIFY: Tests, configuration files

## Recommended Workflow
1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust

## Command Execution Rules
You are operating in an environment where
1. You write a single command
2. The system executes that command in a subshell
3. You see the result
4. You write your next command

Each response should include:
1. A concise **THOUGHT** section where you explain your reasoning and plan
2. A single bash code block with your command

Format your responses like this:

<format_example>
THOUGHT: Here I explain my reasoning process, analysis of the current situation,
and what I'm trying to accomplish with the command below.

```bash
your_command_here
```
</format_example>

Commands must be specified in a single bash code block:

```bash
your_command_here
```

**CRITICAL REQUIREMENTS:**
- Your response SHOULD include a concise THOUGHT section explaining your reasoning
- Your response MUST include EXACTLY ONE bash code block
- This bash block MUST contain EXACTLY ONE command (or a set of commands connected with && or ||)
- If you include zero or multiple bash blocks, or no command at all, YOUR RESPONSE WILL FAIL
- Do NOT try to run multiple independent commands in separate blocks in one response
- Directory or environment variable changes are not persistent. Every action is executed in a new subshell.
- However, you can prefix any action with `MY_ENV_VAR=MY_VALUE cd /path/to/working/dir && ...` or write/load environment variables from files

Example of a CORRECT response:
<example_response>
THOUGHT: I need to understand the structure of the repository first. Let me check what files are in the current directory to get a better understanding of the codebase.

```bash
ls -la
```
</example_response>

Example of an INCORRECT response:
<example_response>
THOUGHT: I need to examine the codebase and then look at a specific file. I'll run multiple commands to do this.

```bash
ls -la
```

Now I'll read the file:

```bash
cat file.txt
```
</example_response>

If you need to run multiple commands, either:
1. Combine them in one block using && or ||
```bash
command1 && command2 || echo "Error occurred"
```

2. Wait for the first command to complete, see its output, then issue the next command in your following response.

## Environment Details
- You have a full Linux shell environment
- Always use non-interactive flags (-y, -f) for commands
- Avoid interactive tools like vi, nano, or any that require user input
- If a command isn't available, you can install it

## Useful Command Examples

### View file content:
```bash
# View specific lines with numbers
nl -ba filename.c | sed -n '10,20p'
```

### Edit files with sed:
```bash
# Replace all occurrences
sed -i 's/old_string/new_string/g' filename.c

# Replace only first occurrence
sed -i 's/old_string/new_string/' filename.c

# Replace first occurrence on line 1
sed -i '1s/old_string/new_string/' filename.c

# Replace all occurrences in lines 1-10
sed -i '1,10s/old_string/new_string/g' filename.c
```

### Create a new file:
```bash
cat <<'EOF' > newfile.c
printf("Hello, World!");
return 0;
EOF
```

### Any other command you want to run
```bash
anything
```

## Submission
When you've completed your work (reading, editing, testing), return the following results:
1. You are only allowed to output a unified git diff.
2. The diff consists of changes to the codebase. It specifies the file names, the line numbers of each change, and the removed and added lines. The diff must follow this exact format:
<example_final_response>
```code
diff --git a/<path> b/<path>
--- a/<path>
+++ b/<path>
@@ -l,s +l,s @@
<code changes>
```
</example_final_response>


This result will submit your work.
You cannot continue working (reading, editing, testing) in any way on this task after submitting.
</instructions>
"""

        return user_prompt

    def lint_shell_command(self, cmd):

        DANGEROUS_CMDS = [
            "sudo", "su", "mount", "umount", "bwrap", "nsenter", "chroot",
            "ssh", "scp", "rsync", "nc", "netcat", "curl", "wget",
            "dd", "mkfs", "losetup", "cryptsetup",
            "iptables", "nft", "sysctl",
            "docker", "podman", "kubectl",
            "apt-get", "install",
        ]

        cmd = cmd.strip()

        for word in DANGEROUS_CMDS:
            if re.search(rf"\b{re.escape(word)}\b", cmd):
                return False, f"Error: Forbidden command: {word}"

        tmp_cmd = cmd.replace("//", "<special_token1>")
        tmp_cmd = tmp_cmd.replace("/*", "<special_token2>")
        tmp_cmd = tmp_cmd.replace("*/", "<special_token3>")
        if re.compile(r'(^|\s)/[^\s]*').search(tmp_cmd):
            return False, "Warning: The command may contain absolute paths, which are not allowed."

        return True, "OK"

    def sandbox_execute(self, cmd, if_print):
        cmd = cmd.replace("/testbed/", "./")
        cmd = cmd.replace("/testbed", ".")
        cmd = cmd.replace("testbed/", "./")

        log_text = ""
        print("Sandbox Execution CMD: " + cmd)
        print(f"\nfix_commit_id: {self.fix_commit_id}\n")
        log_text += "Sandbox Execution CMD: " + cmd + "\n"

        allow, tmp_log = self.lint_shell_command(cmd)
        if not allow:
            log_text += "You cannot use this command.\n"
            log_text += tmp_log
            return {"output": log_text, "returncode": -1, "logs": log_text}

        safe_cmd = f"ulimit -v 10485760\nulimit -f 1269760\nulimit -t 100\n{cmd}"

        returncode, final_output = run_with_realtime_output(cmd=safe_cmd,
                                                            cwd=str(self.tmp_repo_path),
                                                            shell=True,
                                                            if_print=if_print,
                                                            timeout=300,
                                                            idle_timeout=100)

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(final_output)
        if len(tokens) > self.tool_output_token:
            final_output = enc.decode(tokens[:self.tool_output_token]) + "\n\n/* ...truncated... */\n"
            final_output += """Warning: The output of your last command was too long."""
            return {"output": final_output, "returncode": returncode,
                    "logs": log_text + "\n" + final_output}

        log_text += "Execution Output:\n" + final_output

        return {"output": f"<result>\n{final_output}\n</result>", "returncode": returncode, "logs": log_text}

    def run(self, issue_description, bug_commit_id, fix_commit_id, num_done):
        log_text = ""
        self.messages = []
        self.issue_description = issue_description
        self.bug_commit_id = bug_commit_id
        self.fix_commit_id = fix_commit_id
        self.num_done = num_done

        compiler_gym = CompilerGym(SimpleNamespace(ori_repo_path=self.ori_repo_path,
                                                   base_path=self.base_path,
                                                   tmp_repo_path=self.tmp_repo_path,
                                                   if_print=True))
        is_successful, log_text = compiler_gym.get_project(self.bug_commit_id, log_text)
        if not is_successful:
            compiler_gym.stop()
            return "", log_text, {}

        self.system_prompt = self.get_system_prompt()
        system_message = {"role": "system", "content": self.system_prompt}
        self.messages.append(system_message)

        self.user_prompt = self.get_user_prompt(self.issue_description)
        user_message = {"role": "user", "content": self.user_prompt}
        self.messages.append(user_message)

        turn = 0
        final_usage = []
        final_patch = ""
        while turn < self.max_turn:
            turn += 1
            print(f">>> {self.num_done}, {self.fix_commit_id}, {turn}")
            answer_list, finish_reason_list, usage = get_llm_response(model=self.model,
                                                                      messages=self.messages,
                                                                      api_key=self.api_key,
                                                                      base_url=self.base_url,
                                                                      temperature=self.temperature,
                                                                      max_retries=self.max_retries,
                                                                      max_tokens=self.max_tokens)

            if len(answer_list) == 0:
                continue
            final_usage.append(usage)
            answer = answer_list[0]

            self.messages.append(answer)
            answer_content = answer["content"]
            if answer_content is None:
                answer_content = ""

            print(f"\n### Agent ({turn})\n", json.dumps(answer, indent=4))
            print(f"\nfix_commit_id: {self.fix_commit_id}\n")
            system_res_messages = []
            if "```code\ndiff --git" in answer_content:
                final_patch = answer_content
                break
            else:
                cmd = parse_content(answer_content, self.split_word)
                execution_result = self.sandbox_execute(cmd, if_print=True)
                system_res_messages.append({"role": "user", "content": execution_result["output"]})
                system_res_messages.append({"role": "user", "content": f"Reminder: You have {max(0, self.max_turn-20)} rounds of tool calls, and now you have {max(0, self.max_turn-20-turn)} rounds left. You'd better generate the final patch as soon as possible."})
            print(f"\n### Tool ({turn})\n", json.dumps(system_res_messages[0], indent=4))
            print(f"\nfix_commit_id: {self.fix_commit_id}\n")
            self.messages += system_res_messages

            if turn == self.max_turn:
                final_patch = "❌ Max-Turn Limit!"

        for message in self.messages:
            log_text += json.dumps(message, indent=4).strip() + "\n"

        compiler_gym.stop()

        return final_patch, log_text, final_usage


class LiveSWEAgentCoder:
    def __init__(self, args, tmp_repo_path):
        self.model = args.model
        self.max_retries = args.max_retries
        self.api_key = args.api_key
        self.base_url = args.base_url
        self.temperature = args.temperature
        self.max_tokens = args.max_tokens
        self.max_turn = args.max_turn
        self.ori_repo_path = args.ori_repo_path
        self.base_path = args.base_path
        self.tmp_repo_path = tmp_repo_path
        self.split_word = ["```bash", "```"]
        self.tool_output_token = 1024

    def get_system_prompt(self):
        system_prompt = """You are a helpful assistant that can interact multiple times with a computer shell to solve programming tasks.
Your response must contain exactly ONE bash code block with ONE command (or commands connected with && or ||).

Include a THOUGHT section before your command where you explain your reasoning process.
Format your response as shown in <format_example>.

<format_example>
THOUGHT: Your reasoning and analysis here

```bash
your_command_here
```
</format_example>

Failure to follow these rules will cause your response to be rejected.
Make sure your answer content is not empty.

Patch Output Requirement: Finally, you'll output the unified diff directly as required.
"""

        return system_prompt

    def get_user_prompt(self, issue_description):
        user_prompt = f"""<pr_description>
Consider the following PR description:
{issue_description}
</pr_description>

<instructions>
# Task Instructions

## Overview
You're a software engineer interacting continuously with a computer by submitting commands.
You'll be helping implement necessary changes to meet requirements in the PR description.
Your task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.

IMPORTANT: This is an interactive process where you will think and issue ONE command, see its result, then think and issue your next command.

For each response:
1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish
2. Provide exactly ONE bash command to execute

## Important Boundaries
- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)
- DO NOT MODIFY: Tests, configuration files

## Recommended Workflow
1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust

## Command Execution Rules
You are operating in an environment where
1. You write a single command
2. The system executes that command in a subshell
3. You see the result
4. You write your next command

Each response should include:
1. A concise **THOUGHT** section where you explain your reasoning and plan
2. A single bash code block with your command

Format your responses like this:

<format_example>
THOUGHT: Here I explain my reasoning process, analysis of the current situation,
and what I'm trying to accomplish with the command below.

```bash
your_command_here
```
</format_example>

Commands must be specified in a single bash code block:

```bash
your_command_here
```

**CRITICAL REQUIREMENTS:**
- Your response SHOULD include a concise THOUGHT section explaining your reasoning
- Your response MUST include EXACTLY ONE bash code block
- This bash block MUST contain EXACTLY ONE command (or a set of commands connected with && or ||)
- If you include zero or multiple bash blocks, or no command at all, YOUR RESPONSE WILL FAIL
- Do NOT try to run multiple independent commands in separate blocks in one response
- Directory or environment variable changes are not persistent. Every action is executed in a new subshell.
- However, you can prefix any action with `MY_ENV_VAR=MY_VALUE cd /path/to/working/dir && ...` or write/load environment variables from files

Example of a CORRECT response:
<example_response>
THOUGHT: I need to understand the structure of the repository first. Let me check what files are in the current directory to get a better understanding of the codebase.

```bash
ls -la
```
</example_response>

Example of an INCORRECT response:
<example_response>
THOUGHT: I need to examine the codebase and then look at a specific file. I'll run multiple commands to do this.

```bash
ls -la
```

Now I'll read the file:

```bash
cat file.txt
```
</example_response>

If you need to run multiple commands, either:
1. Combine them in one block using && or ||
```bash
command1 && command2 || echo "Error occurred"
```

2. Wait for the first command to complete, see its output, then issue the next command in your following response.

## Environment Details
- You have a full Linux shell environment
- Always use non-interactive flags (-y, -f) for commands
- Avoid interactive tools like vi, nano, or any that require user input
- If a command isn't available, you can install it

## Useful Command Examples

### View file content:
```bash
# View specific lines with numbers
nl -ba filename.c | sed -n '10,20p'
```

### Edit files with sed:
```bash
# Replace all occurrences
sed -i 's/old_string/new_string/g' filename.c

# Replace only first occurrence
sed -i 's/old_string/new_string/' filename.c

# Replace first occurrence on line 1
sed -i '1s/old_string/new_string/' filename.c

# Replace all occurrences in lines 1-10
sed -i '1,10s/old_string/new_string/g' filename.c
```

### Create a new file:
```bash
cat <<'EOF' > newfile.c
printf("Hello, World!");
return 0;
EOF
```

**IMPORTANT TOOL CREATION INSTRUCTIONS**
## Creating your own tools 
- You can also create your own tools in Python to help with your workflow
- Compared to basic bash commands, the tools you create should be able to better aid your workflow in solving the task
- Ensure each tool you create is in Python, contains informative outputs or error messages, and can be ran from the command line
- You should at least create a simple edit tool that can help you effectively edit arbitrary files instead of using bash commands
- The tools you create can be for any purpose, it does not need to be general, instead think about how it can help you specifically with the current task at hand

### Example of creating a custom tool:
<example_response>
THOUGHT: I noticed that in order to solve the issue I need to ... therefore I should create a custom tool to help me ...

```bash
cat <<'EOF' > /path/to/tool_name.py
#!/usr/bin/env python3
import sys
# Import other packages if needed

def main():
    # Your tool logic here
    ...

if __name__ == "__main__":
    main()
EOF
```
</example_response>

### Example of using the tool you created:
<example_response>
THOUGHT: Let me use the custom tool I created to help me with ...

```bash
python /path/to/tool_name.py <<EOF
your_input_here
EOF
```
</example_response>

## Submission
When you've completed your work (reading, editing, testing), return the following results:
1. You are only allowed to output a unified git diff.
2. The diff consists of changes to the codebase. It specifies the file names, the line numbers of each change, and the removed and added lines. The diff must follow this exact format:
<example_final_response>
```code
diff --git a/<path> b/<path>
--- a/<path>
+++ b/<path>
@@ -l,s +l,s @@
<code changes>
```
</example_final_response>

This result will submit your work.
You cannot continue working (reading, editing, testing) in any way on this task after submitting.
</instructions>
"""

        return user_prompt

    def lint_shell_command(self, cmd):

        DANGEROUS_CMDS = [
            "sudo", "su", "mount", "umount", "bwrap", "nsenter", "chroot",
            "ssh", "scp", "rsync", "nc", "netcat", "curl", "wget",
            "dd", "mkfs", "losetup", "cryptsetup",
            "iptables", "nft", "sysctl",
            "docker", "podman", "kubectl",
            "apt-get", "install",
        ]

        cmd = cmd.strip()

        for word in DANGEROUS_CMDS:
            if re.search(rf"\b{re.escape(word)}\b", cmd):
                return False, f"Error: Forbidden command: {word}"

        tmp_cmd = cmd.replace("//", "<special_token1>")
        tmp_cmd = tmp_cmd.replace("/*", "<special_token2>")
        tmp_cmd = tmp_cmd.replace("*/", "<special_token3>")
        if re.compile(r'(^|\s)/[^\s]*').search(tmp_cmd):
            return False, "Warning: The command may contain absolute paths, which are not allowed."

        return True, "OK"

    def sandbox_execute(self, cmd, if_print):
        cmd = cmd.replace("/testbed/", "./")
        cmd = cmd.replace("/testbed", ".")
        cmd = cmd.replace("testbed/", "./")

        log_text = ""
        print("Sandbox Execution CMD: " + cmd)
        print(f"\nfix_commit_id: {self.fix_commit_id}\n")
        log_text += "Sandbox Execution CMD: " + cmd + "\n"

        allow, tmp_log = self.lint_shell_command(cmd)
        if not allow:
            log_text += "You cannot use this command.\n"
            log_text += tmp_log
            return {"output": log_text, "returncode": -1, "logs": log_text}

        safe_cmd = f"ulimit -v 10485760\nulimit -f 1269760\nulimit -t 100\n{cmd}"

        returncode, final_output = run_with_realtime_output(cmd=safe_cmd,
                                                            cwd=str(self.tmp_repo_path),
                                                            shell=True,
                                                            if_print=if_print,
                                                            timeout=300,
                                                            idle_timeout=100)

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(final_output)
        if len(tokens) > self.tool_output_token:
            final_output = enc.decode(tokens[:self.tool_output_token]) + "\n\n/* ...truncated... */\n"
            final_output += """Warning: The output of your last command was too long."""

            return {"output": final_output, "returncode": returncode,
                    "logs": log_text + "\n" + final_output}

        log_text += "Execution Output:\n" + final_output

        return {"output": f"<result>\n{final_output}\n</result>", "returncode": returncode, "logs": log_text}

    def run(self, issue_description, bug_commit_id, fix_commit_id, num_done):
        log_text = ""
        self.messages = []
        self.issue_description = issue_description
        self.bug_commit_id = bug_commit_id
        self.fix_commit_id = fix_commit_id
        self.num_done = num_done

        compiler_gym = CompilerGym(SimpleNamespace(ori_repo_path=self.ori_repo_path,
                                                   base_path=self.base_path,
                                                   tmp_repo_path=self.tmp_repo_path,
                                                   if_print=True))
        is_successful, log_text = compiler_gym.get_project(self.bug_commit_id, log_text)
        if not is_successful:
            compiler_gym.stop()
            return "", log_text, {}

        self.system_prompt = self.get_system_prompt()
        system_message = {"role": "system", "content": self.system_prompt}
        self.messages.append(system_message)

        self.user_prompt = self.get_user_prompt(self.issue_description)
        user_message = {"role": "user", "content": self.user_prompt}
        self.messages.append(user_message)

        turn = 0
        final_usage = []
        final_patch = ""
        while turn < self.max_turn:
            turn += 1
            print(f">>> {self.num_done}, {self.fix_commit_id}, {turn}")
            answer_list, finish_reason_list, usage = get_llm_response(model=self.model,
                                                                      messages=self.messages,
                                                                      api_key=self.api_key,
                                                                      base_url=self.base_url,
                                                                      temperature=self.temperature,
                                                                      max_retries=self.max_retries,
                                                                      max_tokens=self.max_tokens)
            if len(answer_list) == 0:
                continue
            final_usage.append(usage)
            answer = answer_list[0]

            self.messages.append(answer)
            answer_content = answer["content"]
            if answer_content is None:
                answer_content = ""

            print(f"\n### Agent ({turn})\n", json.dumps(answer, indent=4))
            print(f"\nfix_commit_id: {self.fix_commit_id}\n")
            system_res_messages = []
            if "```code\ndiff --git" in answer_content:
                final_patch = answer_content
                break
            else:
                cmd = parse_content(answer_content, self.split_word)
                execution_result = self.sandbox_execute(cmd, if_print=True)
                system_res_messages.append({"role": "user", "content": execution_result["output"]})
                system_res_messages.append({"role": "user", "content": f"Reminder: You have {max(0, self.max_turn-20)} rounds of tool calls, and now you have {max(0, self.max_turn-20-turn)} rounds left. You'd better generate the final patch as soon as possible."})
            print(f"\n### Tool ({turn})\n", json.dumps(system_res_messages[0], indent=4))
            print(f"\nfix_commit_id: {self.fix_commit_id}\n")
            self.messages += system_res_messages

            if turn == self.max_turn:
                final_patch = "❌ Max-Turn Limit!"

        for message in self.messages:
            log_text += json.dumps(message, indent=4).strip() + "\n"

        compiler_gym.stop()

        return final_patch, log_text, final_usage


class TraeAgentCoder:
    def __init__(self, args, tmp_repo_path):
        self.model = args.model
        self.max_retries = args.max_retries
        self.api_key = args.api_key
        self.base_url = args.base_url
        self.temperature = args.temperature
        self.max_tokens = args.max_tokens
        self.max_turn = args.max_turn
        self.ori_repo_path = args.ori_repo_path
        self.base_path = args.base_path
        self.tmp_repo_path = tmp_repo_path
        self.split_word = ["```bash", "```"]
        self.tool_output_token = 1024

    def get_system_prompt(self):
        system_prompt = """You are an expert AI software engineering agent.

File Path Rule: All commands that take a `file_path` as an argument require an **relative path**. You MUST provide the relative path.

For example, the project root is `/testbed` and you need to edit `/testbed/src/main.c`, the correct `file_path` argument is `src/main.py`. Do NOT use absolute paths like `/testbed/src/main.py`.

Your primary goal is to resolve a given GitHub issue by navigating the provided codebase, identifying the root cause of the bug, implementing a robust fix, and ensuring your changes are safe and well-tested.

Follow these steps methodically:

1.  Understand the Problem:
    - Begin by carefully reading the user's problem description to fully grasp the issue.
    - Identify the core components and expected behavior.

2.  Explore and Locate:
    - Use the available commands to explore the codebase.
    - Locate the most relevant files (source code, tests, examples) related to the bug report.

3.  Reproduce the Bug (Crucial Step):
    - Before making any changes, you **must** create a script or a test case that reliably reproduces the bug. This will be your baseline for verification.
    - Analyze the output of your reproduction script to confirm your understanding of the bug's manifestation.

4.  Debug and Diagnose:
    - Inspect the relevant code sections you identified.
    - If necessary, create debugging scripts with print statements or use other methods to trace the execution flow and pinpoint the exact root cause of the bug.

5.  Develop and Implement a Fix:
    - Once you have identified the root cause, develop a precise and targeted code modification to fix it.
    - Use the provided file editing commands to apply your patch. Aim for minimal, clean changes.

6.  Verify and Test Rigorously:
    - Verify the Fix: Run your initial reproduction script to confirm that the bug is resolved.
    - Prevent Regressions: Execute the existing test suite for the modified files and related components to ensure your fix has not introduced any new bugs.
    - Write New Tests: Create new, specific test cases (e.g., using `pytest`) that cover the original bug scenario. This is essential to prevent the bug from recurring in the future. Add these tests to the codebase.
    - Consider Edge Cases: Think about and test potential edge cases related to your changes.

7.  Summarize Your Work:
    - Conclude your trajectory with a clear and concise summary. Explain the nature of the bug, the logic of your fix, and the steps you took to verify its correctness and safety.

**Guiding Principle:** Act like a senior software engineer. Prioritize correctness, safety, and high-quality, test-driven development.

IMPORTANT: This is an interactive process where you will think and provide ONE command, see its result, then think and provide your next command.
Each response should include a single bash code block with your command. Format your responses like this:
```bash
your_command_here
```
Make sure your answer content is not empty.

Finally,
## Submission
Once you have collected enough information to solve the issue, return the following results:
1. You are only allowed to output a unified git diff.
2. The diff consists of changes to the codebase. It specifies the file names, the line numbers of each change, and the removed and added lines. The diff must follow this exact format:
<example_final_response>
```code
diff --git a/<path> b/<path>
--- a/<path>
+++ b/<path>
@@ -l,s +l,s @@
<code changes>
```
</example_final_response>

Patch Output Requirement: Finally, you'll output the unified diff directly as required.
"""

        return system_prompt

    def get_user_prompt(self, issue_description):
        user_prompt = f"[Problem statement]: We're currently solving the following issue within our repository. Here's the issue text:\n{issue_description}\n"
        user_prompt += "Think and provide ONE command, see its result, then think and provide your next command. Each response should include a single bash code block with your command. Format your responses like this:\n```bash\nyour_command_here\n```"

        return user_prompt

    def lint_shell_command(self, cmd):

        DANGEROUS_CMDS = [
            "sudo", "su", "mount", "umount", "bwrap", "nsenter", "chroot",
            "ssh", "scp", "rsync", "nc", "netcat", "curl", "wget",
            "dd", "mkfs", "losetup", "cryptsetup",
            "iptables", "nft", "sysctl",
            "docker", "podman", "kubectl",
            "apt-get", "install",
        ]

        cmd = cmd.strip()

        for word in DANGEROUS_CMDS:
            if re.search(rf"\b{re.escape(word)}\b", cmd):
                return False, f"Error: Forbidden command: {word}"

        tmp_cmd = cmd.replace("//", "<special_token1>")
        tmp_cmd = tmp_cmd.replace("/*", "<special_token2>")
        tmp_cmd = tmp_cmd.replace("*/", "<special_token3>")
        if re.compile(r'(^|\s)/[^\s]*').search(tmp_cmd):
            return False, "Warning: The command may contain absolute paths, which are not allowed."

        return True, "OK"

    def sandbox_execute(self, cmd, if_print):
        cmd = cmd.replace("/testbed/", "./")
        cmd = cmd.replace("/testbed", ".")
        cmd = cmd.replace("testbed/", "./")

        log_text = ""
        print("Sandbox Execution CMD: " + cmd)
        print(f"\nfix_commit_id: {self.fix_commit_id}\n")
        log_text += "Sandbox Execution CMD: " + cmd + "\n"

        allow, tmp_log = self.lint_shell_command(cmd)
        if not allow:
            log_text += "You cannot use this command.\n"
            log_text += tmp_log
            return {"output": log_text, "returncode": -1, "logs": log_text}

        safe_cmd = f"ulimit -v 10485760\nulimit -f 1269760\nulimit -t 100\n{cmd}"

        returncode, final_output = run_with_realtime_output(cmd=safe_cmd,
                                                            cwd=str(self.tmp_repo_path),
                                                            shell=True,
                                                            if_print=if_print,
                                                            timeout=300,
                                                            idle_timeout=100)

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(final_output)
        if len(tokens) > self.tool_output_token:
            final_output = enc.decode(tokens[:self.tool_output_token]) + "\n\n/* ...truncated... */\n"
            final_output += """Warning: The output of your last command was too long."""

            return {"output": final_output, "returncode": returncode,
                    "logs": log_text + "\n" + final_output}

        log_text += "Execution Output:\n" + final_output

        return {"output": f"<result>\n{final_output}\n</result>", "returncode": returncode, "logs": log_text}

    def run(self, issue_description, bug_commit_id, fix_commit_id, num_done):
        log_text = ""
        self.messages = []
        self.issue_description = issue_description
        self.bug_commit_id = bug_commit_id
        self.fix_commit_id = fix_commit_id
        self.num_done = num_done

        compiler_gym = CompilerGym(SimpleNamespace(ori_repo_path=self.ori_repo_path,
                                                   base_path=self.base_path,
                                                   tmp_repo_path=self.tmp_repo_path,
                                                   if_print=True))
        is_successful, log_text = compiler_gym.get_project(self.bug_commit_id, log_text)
        if not is_successful:
            compiler_gym.stop()
            return "", log_text, {}

        self.system_prompt = self.get_system_prompt()
        system_message = {"role": "system", "content": self.system_prompt}
        self.messages.append(system_message)

        self.user_prompt = self.get_user_prompt(self.issue_description)
        user_message = {"role": "user", "content": self.user_prompt}
        self.messages.append(user_message)

        turn = 0
        final_usage = []
        final_patch = ""
        while turn < self.max_turn:
            turn += 1
            print(f">>> {self.num_done}, {self.fix_commit_id}, {turn}")
            answer_list, finish_reason_list, usage = get_llm_response(model=self.model,
                                                                      messages=self.messages,
                                                                      api_key=self.api_key,
                                                                      base_url=self.base_url,
                                                                      temperature=self.temperature,
                                                                      max_retries=self.max_retries,
                                                                      max_tokens=self.max_tokens)
            if len(answer_list) == 0:
                continue
            final_usage.append(usage)
            answer = answer_list[0]

            self.messages.append(answer)
            answer_content = answer["content"]
            if answer_content is None:
                answer_content = ""

            print(f"\n### Agent ({turn})\n", json.dumps(answer, indent=4))
            print(f"\nfix_commit_id: {self.fix_commit_id}\n")
            system_res_messages = []
            if "```code\ndiff --git" in answer_content:
                final_patch = answer_content
                break
            else:
                cmd = parse_content(answer_content, self.split_word)
                execution_result = self.sandbox_execute(cmd, if_print=True)
                system_res_messages.append({"role": "user", "content": execution_result["output"]})
                system_res_messages.append({"role": "user", "content": f"Reminder: You have {max(0, self.max_turn-20)} rounds of tool calls, and now you have {max(0, self.max_turn-20-turn)} rounds left. You'd better generate the final patch as soon as possible."})
            print(f"\n### Tool ({turn})\n", json.dumps(system_res_messages[0], indent=4))
            print(f"\nfix_commit_id: {self.fix_commit_id}\n")
            self.messages += system_res_messages

            if turn == self.max_turn:
                final_patch = "❌ Max-Turn Limit!"

        for message in self.messages:
            log_text += json.dumps(message, indent=4).strip() + "\n"

        compiler_gym.stop()

        return final_patch, log_text, final_usage


class RandomSelector:
    def __init__(self, args):
        self.model = args.model
        self.max_retries = args.max_retries
        self.api_key = args.api_key
        self.base_url = args.base_url
        self.temperature = args.temperature
        self.max_tokens = args.max_tokens
        self.base_path = args.base_path
        self.tool_output_token = 512

    def run(self, candidate_list, issue_description, fix_commit_id, num_done):
        patch_idx = random.randint(0, len(candidate_list) - 1)
        print(patch_idx, len(candidate_list))
        patch = candidate_list[patch_idx].patch
        apply_result = candidate_list[patch_idx].apply
        build_result = candidate_list[patch_idx].build
        check_result = candidate_list[patch_idx].check
        log = ""
        usage = []

        return patch, check_result, log, usage


class SelectorAgent:
    def __init__(self, args):
        self.model = args.model
        self.max_retries = args.max_retries
        self.api_key = args.api_key
        self.base_url = args.base_url
        self.temperature = args.temperature
        self.max_tokens = args.max_tokens
        self.base_path = args.base_path
        self.tool_output_token = 512

    def get_system_prompt(self):
        system_prompt = f"""# ROLE: Act as an expert patch selector. Given a github issue of LLVM and **{len(self.candidate_patch_list)} candidate patches**, your responsibility is to **select the correct one** to solve the issue.

# WORK PROCESS: 
**1. Understand the Issue**
Carefully read the issue description to comprehend the problem.
**2. Analyze the Candidate Patches**
For each patch, analyze its logic and intended fix. Consider whether the changes align with the issue description.
**3. Select the Best Patch**
Choose the patch that best resolves the issue.

# FINAL REPORT: If you have successfully selected the correct patch, submit your answer in the following format:
<result>Patch-x</result>

# IMPORTANT TIPS:
1. Never avoid making a selection.
2. There must be at least one correct patch.
3. The 'x' in 'Patch-x' is the index of correct patch!
"""

        return system_prompt

    def get_user_prompt(self):
        user_prompt = f"[Github issue description]:\n```\n{self.issue_description}\n```\n\n[Candidate Patches]:"
        for idx in range(0, len(self.candidate_patch_list)):
            user_prompt += f"\nPatch-{idx + 1}:\n```\n{self.candidate_patch_list[idx].patch}\n```"

        return user_prompt

    def run(self, candidate_patch_list, issue_description, fix_commit_id, num_done):
        log_text = ""
        final_usage = []

        if len(candidate_patch_list) == 1:
            final_patch = candidate_patch_list[0].patch
            check_result = candidate_patch_list[0].check

            return final_patch, check_result, log_text, final_usage

        self.messages = []
        self.candidate_patch_list = candidate_patch_list
        self.issue_description = issue_description
        self.fix_commit_id = fix_commit_id
        self.num_done = num_done

        self.system_prompt = self.get_system_prompt()
        system_message = {"role": "system", "content": self.system_prompt}
        self.messages.append(system_message)

        self.user_prompt = self.get_user_prompt()
        user_message = {"role": "user", "content": self.user_prompt}
        self.messages.append(user_message)

        answer_list, finish_reason_list, usage = get_llm_response(model=self.model,
                                                                  messages=self.messages,
                                                                  api_key=self.api_key,
                                                                  base_url=self.base_url,
                                                                  temperature=self.temperature,
                                                                  max_retries=self.max_retries,
                                                                  max_tokens=self.max_tokens)

        final_usage.append(usage)
        answer = answer_list[0]
        self.messages.append(answer)
        answer_content = answer["content"]
        if answer_content is None:
            answer_content = ""

        print(f"\n### Agent\n", json.dumps(answer, indent=4))
        print(f"\nfix_commit_id: {self.fix_commit_id}\n")
        x = "none"
        if "<result>" in answer_content and "</result>" in answer_content:
            try:
                x = int(answer_content.split("<result>")[1].split("</result>")[0].split("Patch-")[1].strip())
                final_patch = candidate_patch_list[x-1].patch
                check_result = candidate_patch_list[x-1].check
            except:
                final_patch = candidate_patch_list[0].patch
                check_result = candidate_patch_list[0].check
        else:
            final_patch = candidate_patch_list[0].patch
            check_result = candidate_patch_list[0].check

        for message in self.messages:
            log_text += json.dumps(message, indent=4).strip() + "\n"

        log_text += f"\nIndex: {x}"

        return final_patch, check_result, log_text, final_usage