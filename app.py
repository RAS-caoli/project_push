import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
DATA_DIR = PROJECT_ROOT / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"


class UserCancelledError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local GitHub multi-account push tool.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host, default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port, default: {DEFAULT_PORT}")
    return parser


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS_FILE.exists():
        write_accounts([])


def read_accounts() -> list[dict[str, str]]:
    ensure_data_files()
    try:
        payload = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"账号文件格式错误：{ACCOUNTS_FILE}") from exc

    accounts = payload.get("accounts", []) if isinstance(payload, dict) else []
    cleaned: list[dict[str, str]] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        cleaned.append(
            {
                "id": str(account.get("id") or "").strip(),
                "name": str(account.get("name") or "").strip(),
                "email": str(account.get("email") or "").strip(),
                "pat": str(account.get("pat") or "").strip(),
            }
        )
    return [account for account in cleaned if account["id"]]


def write_accounts(accounts: list[dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"accounts": accounts}
    ACCOUNTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_account(payload: dict[str, object]) -> dict[str, str]:
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip()
    pat = str(payload.get("pat") or "").strip()
    if not name or not email or not pat:
        raise RuntimeError("请完整填写 name、email 和 PAT。")

    return {
        "id": email.lower(),
        "name": name,
        "email": email,
        "pat": pat,
    }


def save_account(payload: dict[str, object]) -> dict[str, object]:
    account = normalize_account(payload)
    accounts = read_accounts()
    replaced = False
    next_accounts: list[dict[str, str]] = []
    for item in accounts:
        if item["id"] == account["id"]:
            next_accounts.append(account)
            replaced = True
        else:
            next_accounts.append(item)

    if not replaced:
        next_accounts.insert(0, account)

    write_accounts(next_accounts)
    return {
        "message": f"账号已保存到 {ACCOUNTS_FILE}",
        "account": account,
        "accounts": next_accounts,
        "storagePath": str(ACCOUNTS_FILE),
    }


def delete_account(account_id: str) -> dict[str, object]:
    normalized_id = account_id.strip().lower()
    if not normalized_id:
        raise RuntimeError("缺少账号 ID。")

    accounts = read_accounts()
    next_accounts = [item for item in accounts if item["id"] != normalized_id]
    if len(next_accounts) == len(accounts):
        raise RuntimeError("未找到要删除的账号。")

    write_accounts(next_accounts)
    return {
        "message": "账号已删除。",
        "accounts": next_accounts,
        "storagePath": str(ACCOUNTS_FILE),
    }


def ensure_git_exists() -> None:
    if shutil.which("git"):
        return
    raise RuntimeError("未检测到 git，请先安装 Git 并确保 git 命令已加入 PATH。")


def normalize_project_path(project_path: str) -> Path:
    if not project_path or not str(project_path).strip():
        raise RuntimeError("请先选择项目路径。")

    target = Path(project_path).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise RuntimeError(f"项目路径不存在或不是文件夹：{target}")
    return target


def run_git_command(
    args: list[str],
    cwd: Path,
    extra_configs: list[tuple[str, str]] | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
    display_command: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    ensure_git_exists()

    command = ["git"]
    for key, value in extra_configs or []:
        command.extend(["-c", f"{key}={value}"])
    command.extend(args)

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra_env:
        env.update(extra_env)

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    safe_display_command = display_command or command
    if check and completed.returncode != 0:
        raise RuntimeError(format_command_output(safe_display_command, completed))
    return completed


def format_command_output(command: list[str], completed: subprocess.CompletedProcess[str]) -> str:
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    parts = [f"$ {' '.join(command)}", f"exit code: {completed.returncode}"]
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(stderr)
    return "\n".join(parts)


def set_local_identity(project_dir: Path, account: dict[str, str]) -> list[str]:
    name = (account.get("name") or "").strip()
    email = (account.get("email") or "").strip()
    if not name or not email:
        raise RuntimeError("请先填写 name 和 email。")

    logs = []
    for args in (["config", "user.name", name], ["config", "user.email", email]):
        result = run_git_command(args, cwd=project_dir)
        logs.append(format_command_output(["git", *args], result))
    return logs


def get_repo_summary(project_dir: Path) -> dict[str, str | bool]:
    summary: dict[str, str | bool] = {
        "projectPath": str(project_dir),
        "isGitRepo": False,
        "branch": "",
        "remoteUrl": "",
        "statusText": "",
    }

    probe = run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=project_dir, check=False)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return summary

    summary["isGitRepo"] = True
    branch = run_git_command(["branch", "--show-current"], cwd=project_dir, check=False)
    remote = run_git_command(["remote", "get-url", "origin"], cwd=project_dir, check=False)
    status = run_git_command(["status", "--short", "--branch"], cwd=project_dir, check=False)
    summary["branch"] = branch.stdout.strip()
    summary["remoteUrl"] = remote.stdout.strip()
    summary["statusText"] = status.stdout.strip()
    return summary


def choose_project_path(initial_dir: str | None) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("当前环境无法打开系统文件夹选择器。") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    start_dir = initial_dir or str(Path.home())
    selected = filedialog.askdirectory(initialdir=start_dir, title="选择 Git 项目路径")
    root.destroy()

    if not selected:
        raise UserCancelledError("已取消选择项目路径。")

    return str(Path(selected).resolve())


def handle_action(payload: dict[str, object]) -> dict[str, object]:
    action = str(payload.get("action") or "").strip()
    if not action:
        raise RuntimeError("缺少 action 参数。")

    project_dir = normalize_project_path(str(payload.get("projectPath") or ""))
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    remote_url = str(payload.get("remoteUrl") or "").strip()
    commit_message = str(payload.get("commitMessage") or "first commit").strip() or "first commit"
    logs: list[str] = []

    if action == "init":
        result = run_git_command(["init"], cwd=project_dir)
        logs.append(format_command_output(["git", "init"], result))
        if account:
            logs.extend(set_local_identity(project_dir, account))
    elif action == "add":
        result = run_git_command(["add", "."], cwd=project_dir)
        logs.append(format_command_output(["git", "add", "."], result))
    elif action == "commit":
        if account:
            logs.extend(set_local_identity(project_dir, account))
        result = run_git_command(["commit", "-m", commit_message], cwd=project_dir)
        logs.append(format_command_output(["git", "commit", "-m", commit_message], result))
    elif action == "branch_main":
        result = run_git_command(["branch", "-M", "main"], cwd=project_dir)
        logs.append(format_command_output(["git", "branch", "-M", "main"], result))
    elif action == "remote_add":
        if not remote_url:
            raise RuntimeError("请先填写 GitHub 仓库地址。")

        probe = run_git_command(["remote", "get-url", "origin"], cwd=project_dir, check=False)
        if probe.returncode == 0:
            result = run_git_command(["remote", "set-url", "origin", remote_url], cwd=project_dir)
            logs.append("检测到已存在 origin，已自动更新远程地址。")
            logs.append(format_command_output(["git", "remote", "set-url", "origin", remote_url], result))
        else:
            result = run_git_command(["remote", "add", "origin", remote_url], cwd=project_dir)
            logs.append(format_command_output(["git", "remote", "add", "origin", remote_url], result))
    elif action == "push":
        extra_configs: list[tuple[str, str]] = []
        if account:
            logs.extend(set_local_identity(project_dir, account))
            pat = (str(account.get("pat") or "")).strip()
            if pat:
                token = base64.b64encode(f"x-access-token:{pat}".encode("utf-8")).decode("ascii")
                extra_configs.append(("http.extraHeader", f"Authorization: Basic {token}"))

        result = run_git_command(
            ["push", "-u", "origin", "main"],
            cwd=project_dir,
            extra_configs=extra_configs,
            display_command=["git", "push", "-u", "origin", "main"],
        )
        logs.append(format_command_output(["git", "push", "-u", "origin", "main"], result))
    else:
        raise RuntimeError(f"不支持的操作：{action}")

    return {
        "message": "操作执行成功。",
        "logs": logs,
        "summary": get_repo_summary(project_dir),
    }


class GitPushHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                self.send_json({"ok": True, "message": "server ready"})
                return
            if path == "/api/accounts":
                query = parse_qs(parsed.query)
                active_account_id = query.get("active", [""])[0].strip().lower()
                self.send_json(
                    {
                        "ok": True,
                        "accounts": read_accounts(),
                        "activeAccountId": active_account_id,
                        "storagePath": str(ACCOUNTS_FILE),
                    }
                )
                return
        except Exception as exc:
            self.send_json({"ok": False, "message": str(exc)}, status=500)
            return

        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/select-path":
                initial_dir = str(payload.get("currentPath") or "")
                selected = choose_project_path(initial_dir if initial_dir else None)
                body = {
                    "ok": True,
                    "message": "项目路径已更新。",
                    "projectPath": selected,
                    "summary": get_repo_summary(Path(selected)),
                }
            elif path == "/api/git-action":
                body = {"ok": True, **handle_action(payload)}
            elif path == "/api/accounts/save":
                body = {"ok": True, **save_account(payload)}
            elif path == "/api/accounts/delete":
                body = {"ok": True, **delete_account(str(payload.get("id") or ""))}
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
                return
        except UserCancelledError as exc:
            body = {"ok": False, "message": str(exc)}
        except Exception as exc:
            body = {"ok": False, "message": str(exc)}

        self.send_json(body)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    ensure_data_files()
    if not WEB_ROOT.exists():
        print(f"Missing web root: {WEB_ROOT}", file=sys.stderr)
        sys.exit(1)

    server = ThreadingHTTPServer((args.host, args.port), GitPushHandler)
    print(f"GitHub push tool is running at http://{args.host}:{args.port}")
    print(f"Accounts file: {ACCOUNTS_FILE}")
    print("Press Ctrl+C to stop the server.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
