import os
from utils import run_with_realtime_output


class CompilerGym:
    def __init__(self, args):
        self.ori_repo_path = args.ori_repo_path
        self.base_path = args.base_path
        self.tmp_repo_path = args.tmp_repo_path
        self.if_print = args.if_print
        self.GIT_APPLY_CMDS = [
            ["git", "-c", "core.askPass=true", "apply", "--verbose", "-"],
            ["git", "-c", "core.askPass=true", "apply", "--verbose", "--reject", "-"],
            ["patch", "--batch", "--fuzz=5", "-p1"]
        ]

    def get_project(self, bug_commit_id, log_text):
        if not os.path.exists(self.ori_repo_path):
            log_text += f"Project path not found: {self.ori_repo_path}\n"
            return False, log_text

        if os.path.exists(self.tmp_repo_path):
            cmd = f"rm -rf {self.tmp_repo_path}"
            print(cmd, "...")
            returncode, logs = run_with_realtime_output(cmd=cmd,
                                                        cwd=str(os.path.join(self.base_path, "codebases")),
                                                        shell=True,
                                                        if_print=self.if_print)
            log_text += cmd + "\n"
            if returncode != 0:
                print(cmd, "❌")
            else:
                log_text += logs + "\n"

        cmd = f"cp -r {self.ori_repo_path} {self.tmp_repo_path}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(os.path.join(self.base_path, "codebases")),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        cmd = f"GIT_TERMINAL_PROMPT=0 git -c core.askPass=true checkout -f {bug_commit_id}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(self.tmp_repo_path),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        return True, log_text

    def checkout_project(self, bug_commit_id, log_text):
        cmd = f"GIT_TERMINAL_PROMPT=0 git -c core.askPass=true checkout -f {bug_commit_id}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(self.tmp_repo_path),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        return True, log_text

    def reset_project(self, log_text):
        cmd = f"GIT_TERMINAL_PROMPT=0 git -c core.askPass=true reset --hard"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(self.tmp_repo_path),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
        else:
            log_text += logs + "\n"

    def stop(self):
        log_text = ""
        if os.path.exists(self.tmp_repo_path):
            cmd = f"rm -rf {self.tmp_repo_path}"
            print(cmd, "...")
            returncode, logs = run_with_realtime_output(cmd=cmd,
                                                        cwd=str(os.path.join(self.base_path, "codebases")),
                                                        shell=True,
                                                        if_print=self.if_print)
            log_text += cmd + "\n"
            if returncode != 0:
                print(cmd, "❌")
                return False, log_text + logs
            else:
                log_text += logs + "\n"

        return True, log_text

    def apply_patch(self, generated_patch, log_text):
        returncode = -1
        for git_apply_cmd in self.GIT_APPLY_CMDS:
            print(f"{git_apply_cmd} ...")
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_PAGER"] = "cat"
            returncode, logs = run_with_realtime_output(cmd=git_apply_cmd,
                                                        cwd=str(self.tmp_repo_path),
                                                        shell=False,
                                                        input=generated_patch,
                                                        if_print=self.if_print)
            log_text += f"{git_apply_cmd} <generated patch>\n"
            log_text += logs + "\n"
            if returncode == 0:
                break

        if returncode != 0:
            print("git apply <generated patch>", "❌")
            return False, log_text

        return True, log_text

    def apply_test_patch(self, test_patch, log_text):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_PAGER"] = "cat"
        returncode, logs = run_with_realtime_output(cmd=self.GIT_APPLY_CMDS[0],
                                                    cwd=str(self.tmp_repo_path),
                                                    shell=False,
                                                    input=test_patch,
                                                    if_print=self.if_print)
        log_text += f"{self.GIT_APPLY_CMDS[0]} <golden test patch>\n"
        if returncode != 0:
            print(f"git apply <golden test patch>", "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        return True, log_text

    def build_project(self, log_text):
        if os.path.exists(os.path.join(self.tmp_repo_path, "build")):
            cmd = f"rm -rf {str(os.path.join(self.tmp_repo_path, 'build'))}"
            print(cmd, "...")
            returncode, logs = run_with_realtime_output(cmd=cmd,
                                                        cwd=str(self.tmp_repo_path),
                                                        shell=True,
                                                        if_print=self.if_print)
            log_text += cmd + "\n"
            if returncode != 0:
                print(cmd, "❌")
                return False, log_text + logs
            else:
                log_text += logs + "\n"

        cmd = f"mkdir {str(os.path.join(self.tmp_repo_path, 'build'))}"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(self.tmp_repo_path),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs+ "\n"

        cmake_path = os.path.join(self.base_path, "config/cmake-4.2.0-linux-x86_64/bin/cmake")
        cmd = f"""{cmake_path} -G Ninja ../llvm \
            -DLLVM_ENABLE_PROJECTS=clang\;llvm \
            -DLLVM_TARGETS_TO_BUILD="X86" \
            -DCMAKE_BUILD_TYPE=Release \
            -DLLVM_ENABLE_ASSERTIONS=ON \
            -DCLANG_ENABLE_NVPTX=OFF \
            -DCLANG_ENABLE_AMDGPU=OFF \
            -DPython3_EXECUTABLE=$(which python3);"""
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(os.path.join(self.tmp_repo_path, 'build')),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        cmake_path = os.path.join(self.base_path, "config/cmake-4.2.0-linux-x86_64/bin/cmake")
        cmd = f"{cmake_path} --build . -- -j32;"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(os.path.join(self.tmp_repo_path, 'build')),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        return True, log_text

    def check_project(self, log_text):
        if not os.path.exists(os.path.join(self.tmp_repo_path, "build")):
            result, log_text = self.build_project(log_text)
            if result == False:
                return False, log_text

        del_tests = [str(os.path.join(self.tmp_repo_path, "clang/test/Driver/gpu-libc.c")),
                     str(os.path.join(self.tmp_repo_path, "clang/test/Driver/gpu-libc-headers.c")),
                     str(os.path.join(self.tmp_repo_path, "llvm/test/tools/llvm-ar/error-opening-permission.test")),
                     str(os.path.join(self.tmp_repo_path, "llvm/test/tools/llvm-dwarfdump/X86/output.s")),
                     str(os.path.join(self.tmp_repo_path, "llvm/test/tools/llvm-ifs/fail-file-write.test")),
                     str(os.path.join(self.tmp_repo_path, "llvm/test/tools/llvm-ranlib/error-opening-permission.test")),
                     str(os.path.join(self.tmp_repo_path, "tools/llvm-reduce/parallel-workitem-kill.ll")),
                     ]
        for del_test in del_tests:
            if os.path.exists(del_test):
                cmd = f"rm {del_test}"
                print(cmd, "...")
                returncode, logs = run_with_realtime_output(cmd=cmd,
                                                            cwd=str(os.path.join(self.tmp_repo_path, 'build')),
                                                            shell=True,
                                                            if_print=self.if_print)
                log_text += cmd + "\n"
                if returncode != 0:
                    print(cmd, "❌")
                    return False, log_text + logs
                else:
                    log_text += logs + "\n"

        cmake_path = os.path.join(self.base_path, "config/cmake-4.2.0-linux-x86_64/bin/cmake")
        cmd = f"{cmake_path} --build . --target check-all -- -j32"
        print(cmd, "...")
        returncode, logs = run_with_realtime_output(cmd=cmd,
                                                    cwd=str(os.path.join(self.tmp_repo_path, 'build')),
                                                    shell=True,
                                                    if_print=self.if_print)
        log_text += cmd + "\n"
        if returncode != 0:
            print(cmd, "❌")
            return False, log_text + logs
        else:
            log_text += logs + "\n"

        return True, log_text

    def get_applied_patch(self, log_text):
        get_applied_patch_cmd = "git diff"
        print(f"{get_applied_patch_cmd} ...")
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_PAGER"] = "cat"
        returncode, logs = run_with_realtime_output(cmd=get_applied_patch_cmd,
                                                    cwd=str(self.tmp_repo_path),
                                                    shell=True,
                                                    if_print=self.if_print)

        log_text += f"{get_applied_patch_cmd}\n"
        log_text += logs + "\n"
        applied_patch = logs.strip()

        if returncode != 0:
            print(f"{get_applied_patch_cmd}", "❌")
            return False, applied_patch, log_text

        return True, applied_patch, log_text