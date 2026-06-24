import os
import re
import sys
import json
import time
import fcntl
import select
import signal
import termios
import subprocess
from openai import OpenAI


def read_all_instances(path):
    all_instances = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            instance = json.loads(line.strip())
            all_instances.append(instance)

    return all_instances


def write_all_instances(path, all_instances):
    with open(path, 'w', encoding='utf-8') as f:
        for item in all_instances:
            f.write(json.dumps(item) + '\n')


def run_with_realtime_output(cmd, cwd, shell, input=None, if_print=False, timeout=3000, idle_timeout=1200):
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE if input else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
        shell=shell,
        preexec_fn=os.setsid
    )
    if input:
        if isinstance(input, str):
            input = input.encode("utf-8")
        os.write(process.stdin.fileno(), input)
        process.stdin.close()

    fd = process.stdout.fileno()
    fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK)

    logs = []
    start = time.time()
    last_output_time = start

    try:
        while True:
            rlist, _, _ = select.select([fd], [], [], 0.5)

            if rlist:
                try:
                    data = os.read(fd, 4096)
                    if data:
                        logs.append(data)
                        if if_print:
                            print(data.decode(errors="replace"), end="", flush=True)
                        last_output_time = time.time()
                except BlockingIOError:
                    pass

            if process.poll() is not None:
                while True:
                    try:
                        chunk = os.read(fd, 4096)
                        if not chunk:
                            break
                        logs.append(chunk)
                    except BlockingIOError:
                        break
                break

            if time.time() - start > timeout:
                raise TimeoutError("Total timeout")

            if time.time() - last_output_time > idle_timeout:
                raise TimeoutError("Idle timeout")

        return process.returncode, b"".join(logs).decode(errors="replace")
    except KeyboardInterrupt:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, termios.tcgetattr(sys.stdin))
        exit()
    except TimeoutError as e:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        return -9, b"".join(logs).decode(errors="replace") + f"\n[{e} KILLED]\n"


def sanitize_for_gemini(messages):
    clean = []
    for m in messages:
        if "tool_calls" in m:
            continue
        if "function_call" in m:
            continue
        if "reasoning_details" in m:
            continue

        clean.append(m)

    return clean


def send_request(client, model, messages, uuid=None, temperature=0.0, n=1, max_retries=1, max_tokens=4096):
    retries = 0
    while retries < max_retries:
        try:
            if model == "google/gemini-3-flash-preview":
                messages = sanitize_for_gemini(messages)
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    n=n,
                    extra_body={"reasoning": {"enabled": False},
                                "provider": {"only": ["google-vertex"]},
                                "tool_choice": "none",
                                "response_format": {"type": "text"}},
                    extra_headers={"extra": json.dumps({"session_id": uuid})},
                    tools=None,
                    tool_choice="none",
                    functions=None,
                    function_call="none"
                )
            elif model == "x-ai/grok-code-fast-1":
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    n=n,
                    extra_body={"reasoning": {
                        "enabled": False,
                        "effort": "none",
                    }},
                    extra_headers={"extra": json.dumps({"session_id": uuid})}
                )
            else:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    n=n,
                    extra_body={"reasoning": {"enabled": False}},
                    extra_headers={"extra": json.dumps({"session_id": uuid})}
                )
            resp_json = json.loads(completion.model_dump_json())

            if completion is None:
                raise ValueError("Completion is None")
            if resp_json is None:
                raise ValueError("Response is None")

            if "choices" not in resp_json or resp_json["choices"] is None:
                raise ValueError("Choices is None")

            return resp_json
        except Exception as e:
            print(f"An error occurred: {e}")
            retries += 1
            if retries < max_retries:
                time.sleep(30)
    print(f"Maximum retries ({max_retries}) exceeded.")
    return None


def get_llm_response(model, messages, api_key, base_url, uuid=None, temperature=0.0, n=1, max_retries=1, max_tokens=4096):
    client = OpenAI(api_key=api_key, base_url=base_url)

    decoded_answer = []
    finish_reason = []
    assistant_response = send_request(client, model, messages, uuid, temperature, n, max_retries, max_tokens)

    if assistant_response is None:
        return [], [], None

    for choice in assistant_response["choices"]:
        decoded_answer.append(choice["message"])
        finish_reason.append(choice["finish_reason"])

    return decoded_answer, finish_reason, assistant_response["usage"]


def parse_content(input_string, split_word):
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
        new_patch.append(i)
    output_string = "\n".join(new_patch)

    return output_string
