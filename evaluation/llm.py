import json
from utils import get_llm_response


class LLMCoder:
    def __init__(self, args):
        self.model = args.model
        self.max_retries = args.max_retries
        self.api_key = args.api_key
        self.base_url = args.base_url
        self.temperature = args.temperature
        self.max_tokens = args.max_tokens

    def get_system_prompt(self):
        system_prompt = """You are an autonomous AI software engineer operating in a llvm-project repository.

Your sole objective is to solve the given GitHub issue by producing a correct code patch that makes all tests pass.

You must follow these rules strictly:

1. You are only allowed to output a unified git diff.
2. The diff consists of changes to the codebase. It specifies the file names, the line numbers of each change, and the removed and added lines. The diff must follow this exact format:

```code
diff --git a/<path> b/<path>
--- a/<path>
+++ b/<path>
@@ -l,s +l,s @@
<code changes>
```

3. Do NOT include:
   - explanations
   - comments
   - markdown
   - analysis
   - natural language
   - stack traces
   - test output
   - filenames outside the diff

4. The patch must:
   - solve the issue described in the GitHub issue
   - satisfy all existing tests
   - not introduce new failures

5. A single patch file can contain changes to multiple files. If multiple files must be modified, include all of them in one diff.

I need you to solve the provided issue by generating a single patch file that I can apply directly to this repository using git apply. 
Please respond with a single patch file in the format shown above.
Respond below:
```code
```
"""
        return system_prompt

    def get_user_prompt(self, issue_description, context):
        user_prompt = f"[Github Issue Description]:\n```\n{issue_description}\n```\n\n[Related Code]:\n```\n{context}\n```\n"
        return user_prompt

    def run(self, issue_description, context):
        self.messages = []

        self.system_prompt = self.get_system_prompt()
        system_message = {"role": "system", "content": self.system_prompt}
        self.messages.append(system_message)

        self.user_prompt = self.get_user_prompt(issue_description, context)
        user_message = {"role": "user", "content": self.user_prompt}
        self.messages.append(user_message)

        answer_list, finish_reason_list, usage = get_llm_response(model=self.model,
                                                                  messages=self.messages,
                                                                  api_key=self.api_key,
                                                                  base_url=self.base_url,
                                                                  temperature=self.temperature,
                                                                  max_retries=self.max_retries,
                                                                  max_tokens=self.max_tokens)

        if len(answer_list) == 0:
            return "", "", None

        answer = answer_list[0]

        print(f"\n### LLM\n", json.dumps(answer, indent=4))

        self.messages.append(answer)
        if answer["content"] is None:
            final_patch = ""
        else:
            final_patch = answer["content"]
        finish_reason = finish_reason_list[0]
        final_usage = [usage]

        log = ""
        for message in self.messages:
            log += json.dumps(message, indent=4).strip() + "\n"

        return final_patch, log, final_usage