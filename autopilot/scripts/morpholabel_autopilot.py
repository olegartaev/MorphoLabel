#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MorphoLabel autopilot coordinator.

Safety model:
- ChatGPT I/O goes through the official OpenCode Browse CLI.
- Codex input goes only through `codex queue --thread ... --message ...` (no manual
  edits of Codex session files).
- Codex completion is detected by READ-ONLY parsing of the session rollout file.
- Runtime control uses plain marker files: STOP / PAUSE.
- Runtime files stay under autopilot/runtime; source/research data outside the
  repository are never modified by this script.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

UTC = dt.timezone.utc

TASK_FIELDS = ("TASK", "GOAL", "ACCEPTANCE", "CONSTRAINTS")
MAX_TASK_REQUESTS = 3


def parse_task_fields(block: str) -> Dict[str, str]:
    """Parse a structured ChatGPT task and require substantive, non-placeholder fields."""
    if not isinstance(block, str):
        return {}
    values: Dict[str, str] = {}
    current: Optional[str] = None
    for raw_line in block.splitlines():
        match = re.match(r"^\s*(TASK|GOAL|ACCEPTANCE|CONSTRAINTS)\s*:\s*(.*)$", raw_line, re.I)
        if match:
            current = match.group(1).upper()
            values[current] = match.group(2).strip()
        elif current:
            values[current] = (values[current] + "\n" + raw_line.strip()).strip()
    return {key: value.strip() for key, value in values.items() if value.strip()}


def task_completeness_error(block: str) -> Optional[str]:
    fields = parse_task_fields(block)
    missing = [field for field in TASK_FIELDS if not fields.get(field)]
    if missing:
        return "missing required fields: " + ", ".join(missing)
    placeholder = re.compile(
        r"^(?:<[^>]+>|\[[^\]]+\]|\.\.\.|задание|уточнить|нет|n/?a|todo|tbd)$",
        re.I,
    )
    # Earlier request examples passed length-only checks; refuse those as tasks.
    sample_prefixes = {
        "TASK": ("конкретные действия, ожидаемые файлы",),
        "GOAL": ("цель этого этапа и зачем он нужен",),
        "ACCEPTANCE": ("проверяемые критерии завершения",),
        "CONSTRAINTS": ("запись только в d:\\simm_github_clean; d:\\phoxinus_x-ray только для чтения",),
    }
    for field in TASK_FIELDS:
        value = fields[field]
        normalized = " ".join(value.casefold().split())
        if placeholder.fullmatch(value.strip()) or len(re.sub(r"\W", "", value)) < 8:
            return f"field {field} is a placeholder or too short"
        if any(normalized.startswith(prefix) for prefix in sample_prefixes[field]):
            return f"field {field} repeats an instruction template rather than a task"
    if len(fields["TASK"]) < 20:
        return "TASK must describe a concrete action, not just a label"
    if len(fields["GOAL"]) < 15:
        return "GOAL must explain the intended outcome"
    if len(fields["ACCEPTANCE"]) < 15:
        return "ACCEPTANCE must define observable completion checks"
    if len(fields["CONSTRAINTS"]) < 15:
        return "CONSTRAINTS must state scope and safety boundaries"
    return None


def task_was_attempted(task_hash: str, state: Dict[str, Any]) -> bool:
    """Reject tasks already queued or completed, including uncertain queue outcomes."""
    return task_hash in state.get("attempted_task_hashes", []) or task_hash in state.get("processed_markers", [])


def now_iso() -> str:
    return dt.datetime.now(UTC).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def run_command(argv: list[str], timeout_s: int, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )


class AutopilotError(RuntimeError):
    pass


class MorphoLabelAutopilot:
    def __init__(self, config_path: Path, dry_run: bool = False) -> None:
        self.config_path = config_path
        self.config = load_json(config_path, {})
        if not self.config:
            raise AutopilotError(f"Empty or missing config: {config_path}")
        self.dry_run = dry_run
        self.repo_root = Path(self.config["repo_root"]).resolve()
        self.runtime_dir = (self.repo_root / self.config["runtime_dir"]).resolve()
        self.control_dir = (self.repo_root / self.config["control_dir"]).resolve()
        self.logs_dir = (self.repo_root / self.config["logs_dir"]).resolve()
        self.state_file = (self.repo_root / self.config["state_file"]).resolve()
        self.safe_state_export = (self.repo_root / self.config["safe_state_export"]).resolve()
        for directory in (self.runtime_dir, self.control_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.log_file = self.logs_dir / f"autopilot-{dt.datetime.now():%Y%m%d}.log"
        self.session_name = self.config["browse_session"]
        self.state = load_json(self.state_file, self.default_state())

    def default_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "status": "new",
            "cycle": 0,
            "updated_at": now_iso(),
            "codex_thread_id": self.config["codex"]["thread_id"],
            "active_chatgpt_url": self.config["chatgpt"].get("project_url"),
            "processed_markers": [],
            "rejected_task_hashes": [],
            "attempted_task_hashes": [],
            "pending": {},
            "limits": {"last_rate_limit": None, "paused_until": None},
            "last_error": None,
            "notes": [],
        }

    def log(self, message: str) -> None:
        line = f"{now_iso()} {message}"
        print(line, flush=True)
        with self.log_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    def save_state(self) -> None:
        self.state["updated_at"] = now_iso()
        save_json_atomic(self.state_file, self.state)
        safe = dict(self.state)
        safe.pop("last_error", None)
        # Keep only hashes/ids/statuses; no task/result bodies are stored here.
        save_json_atomic(self.safe_state_export, safe)

    def stop_requested(self) -> bool:
        return (self.control_dir / "STOP").exists()

    def pause_requested(self) -> bool:
        return (self.control_dir / "PAUSE").exists()

    def wait_with_control(self, seconds: float) -> str:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.stop_requested():
                return "stop"
            if self.pause_requested():
                self.state["status"] = "paused"
                self.save_state()
                time.sleep(min(2.0, max(0.2, deadline - time.monotonic())))
                continue
            time.sleep(min(2.0, max(0.2, deadline - time.monotonic())))
        return "timeout"

    def browse(self, *args: str, timeout_s: int = 60) -> Dict[str, Any]:
        if self.dry_run:
            raise AutopilotError("browse called in dry-run mode")
        exe = self.config["browse_exe"]
        cp = run_command([exe, *args, "--json"], timeout_s, self.repo_root)
        if cp.returncode != 0:
            raise AutopilotError(f"browse failed rc={cp.returncode}: {cp.stderr[:1000]}")
        try:
            return json.loads(cp.stdout)
        except json.JSONDecodeError as exc:
            raise AutopilotError(f"browse returned non-JSON: {cp.stdout[:1000]}") from exc

    def browse_value(self, envelope: Dict[str, Any]) -> Any:
        if envelope.get("isError") or envelope.get("ok") is False:
            raise AutopilotError(f"browse error: {json.dumps(envelope, ensure_ascii=False)[:1200]}")
        value = envelope.get("value")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def ensure_chatgpt_session(self) -> None:
        status = self.browse("status", timeout_s=30)
        targets = (
            status.get("targets")
            or ((status.get("extension") or {}).get("targets"))
            or (((status.get("status") or {}).get("targets")))
            or []
        )
        cfg = self.config["chatgpt"]
        target = None
        for item in targets:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            if cfg["title_contains"] in title and cfg["url_contains"] in url:
                target = item
                break
        if not target:
            raise AutopilotError("ChatGPT target tab not found by title/url filters")
        tab_id = target.get("tabId")
        if tab_id is None:
            raise AutopilotError("ChatGPT target has no tabId")
        existing_session = target.get("opencodeBrowserSessionId")
        if existing_session:
            # Reuse the already attached Browse session instead of forcing a second adoption.
            self.session_name = str(existing_session)
        else:
            cp = run_command(
                [self.config["browse_exe"], "session", "adopt", "--session", self.session_name, "--tab-id", str(tab_id)],
                30,
                self.repo_root,
            )
            if cp.returncode != 0:
                match = re.search(r"already adopted by session ([A-Za-z0-9_-]+)", cp.stderr)
                if match:
                    self.session_name = match.group(1)
                else:
                    raise AutopilotError(f"browse session adopt failed: {cp.stderr[:1000]}")
        self.state["active_chatgpt_url"] = target.get("url")
        self.state["active_chatgpt_tab_id"] = tab_id
        self.state["browse_session"] = self.session_name
        self.save_state()

    def js_path(self, name: str, code: str) -> Path:
        path = self.runtime_dir / "js" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8", newline="\n")
        return path

    def chatgpt_read(self) -> Dict[str, Any]:
        js = self.js_path(
            "read_chatgpt.js",
            "const text = await page.evaluate(() => document.body.innerText);\n"
            "return { url: page.url(), title: await page.title(), text };\n",
        )
        env = self.browse("execute", "--session", self.session_name, "--file", str(js), timeout_s=60)
        value = self.browse_value(env)
        if not isinstance(value, dict) or "text" not in value:
            raise AutopilotError("ChatGPT read did not return text")
        return value

    def chatgpt_send(self, text: str) -> None:
        payload = json.dumps(text, ensure_ascii=False)
        code = (
            f"const text = {payload};\n"
            "const box = page.getByRole('textbox', { name: /Спросить|Ask|Message|Сообщение/i });\n"
            "await box.click();\n"
            "try { await box.fill(text); } catch (e) { await box.pressSequentially(text, { delay: 1 }); }\n"
            "const send = page.getByRole('button', { name: /Отправить|Send/i });\n"
            "await send.click();\n"
            "return { sent: true, url: page.url() };\n"
        )
        js = self.js_path("send_chatgpt.js", code)
        env = self.browse("execute", "--session", self.session_name, "--file", str(js), timeout_s=90)
        self.browse_value(env)

    def request_task(self, cycle_id: str) -> Optional[str]:
        begin = f"AUTOPILOT_TASK_BEGIN_{cycle_id}"
        end = f"AUTOPILOT_TASK_END_{cycle_id}"
        previous_rejection: Optional[str] = None
        for attempt in range(1, MAX_TASK_REQUESTS + 1):
            prompt = self.task_request_prompt(cycle_id, begin, end, attempt, previous_rejection)
            baseline = self.chatgpt_read()["text"]
            before = baseline.count(begin)
            before_end = baseline.count(end)
            no_task_token = f"NO_TASK_{cycle_id}"
            no_task_before = baseline.count(no_task_token)
            self.chatgpt_send(prompt)
            response = self.wait_for_task_response(cycle_id, begin, before, before_end, no_task_before)
            if response is None:
                return None
            task, error = response
            if error is None:
                return task
            digest = sha256_text(task)
            rejected = self.state.setdefault("rejected_task_hashes", [])
            if digest not in rejected:
                rejected.append(digest)
            del rejected[:-100]
            self.state["status"] = "requesting_complete_task"
            self.state["last_rejected_task"] = {"hash": digest, "reason": error, "attempt": attempt}
            self.save_state()
            previous_rejection = error
            self.log(f"Rejected incomplete ChatGPT task {digest[:12]}: {error}")
        self.state["status"] = "blocked_incomplete_chatgpt_task"
        self.state["pending"] = {}
        self.save_state()
        raise AutopilotError(
            f"ChatGPT did not provide a complete task after {MAX_TASK_REQUESTS} bounded requests; nothing queued to Codex"
        )

    @staticmethod
    def task_request_prompt(cycle_id: str, begin: str, end: str, attempt: int,
                            rejection_reason: Optional[str] = None) -> str:
        correction = (
            f"\nПредыдущий ответ отклонён: {rejection_reason}. Исправь его полностью; не повторяй шаблон.\n"
            if rejection_reason else ""
        )
        return (
            f"{cycle_id} (попытка {attempt}/{MAX_TASK_REQUESTS})\n\n"
            "Из действующего научного плана этого чата выбери ОДНО реальное следующее задание "
            "для существующего Codex '2 работа'. Самостоятельно укажи конкретные действия и файлы, "
            "ожидаемый результат, измеримые критерии завершения и границы доступа. "
            "Не повторяй описание полей, не выдавай шаблон или одни ограничения. "
            "Если после чтения контекста невозможно определить конкретное полезное действие, "
            "не придумывай его.\n"
            f"Ответ начни с точного маркера {begin} отдельной строкой; "
            f"заверши точным маркером {end} отдельной строкой. "
            "Между маркерами напиши четыре содержательных поля с префиксами "
            "TASK:, GOAL:, ACCEPTANCE:, CONSTRAINTS:. "
            "TASK должен описывать реальную работу и ожидаемые файлы/результат; "
            "GOAL — конкретную цель; ACCEPTANCE — проверяемые тесты; "
            "CONSTRAINTS — разрешённые пути и запреты. "
            "Не копируй эти пояснения как значения полей.\n"
            "Разрешённая запись — только D:\\SIMM_GITHUB_CLEAN; "
            "D:\\Phoxinus_X-Ray — исключительно чтение; опубликованную версию не менять.\n"
            f"Если действительного задания нет — ответь ровно NO_TASK_{cycle_id}.\n"
            f"{correction}Не запускай Codex сам и не меняй файлы/GitHub."
        )

    @staticmethod
    def has_new_complete_task(body: str, begin: str, end: str,
                              before_begin: int, before_end: int) -> bool:
        """Count markers in both prompt and a complete assistant answer."""
        return body.count(begin) >= before_begin + 2 and body.count(end) >= before_end + 2

    @staticmethod
    def has_new_no_task(body: str, token: str, before_count: int) -> bool:
        """Do not mistake the coordinator prompt for a ChatGPT reply."""
        return body.count(token) >= before_count + 2

    def wait_for_task_response(self, cycle_id: str, begin: str, previous_count: int,
                               previous_end_count: int, no_task_previous_count: int):
        deadline = time.monotonic() + int(self.config["limits"]["chatgpt_wait_timeout_s"])
        end = f"AUTOPILOT_TASK_END_{cycle_id}"
        no_task = f"NO_TASK_{cycle_id}"
        while time.monotonic() < deadline:
            if self.stop_requested():
                raise AutopilotError("Stopped while waiting for ChatGPT task")
            if self.pause_requested():
                if self.wait_with_control(2) == "stop":
                    raise AutopilotError("Stopped while paused")
                continue
            text = self.chatgpt_read()["text"]
            if self.has_new_complete_task(text, begin, end, previous_count, previous_end_count):
                return self.extract_task_with_validation(text, cycle_id)
            if self.has_new_no_task(text, no_task, no_task_previous_count):
                return None
            time.sleep(int(self.config["limits"]["poll_control_s"]))
        raise AutopilotError("Timeout waiting for ChatGPT task")

    @classmethod
    def extract_task_with_validation(cls, text: str, cycle_id: str):
        task = cls.extract_task(text, cycle_id)
        if task is None:
            return None, "empty task block"
        return task, task_completeness_error(task)

    @staticmethod
    def extract_task(text: str, cycle_id: str) -> Optional[str]:
        begin = f"AUTOPILOT_TASK_BEGIN_{cycle_id}"
        end = f"AUTOPILOT_TASK_END_{cycle_id}"
        blocks = re.findall(re.escape(begin) + r"(.*?)" + re.escape(end), text, flags=re.S)
        if blocks:
            task = blocks[-1].strip()
            # A wrapper/empty block is not a task; malformed nonempty content is
            # returned to validation so ChatGPT can be asked to complete it.
            return task
        if f"NO_TASK_{cycle_id}" in text:
            return None
        return None

    def find_codex_rollout(self) -> Path:
        thread = self.config["codex"]["thread_id"]
        root = Path(self.config["codex"]["sessions_root"])
        matches = sorted(root.glob(f"**/rollout-*{thread}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            raise AutopilotError(f"Codex rollout not found for thread {thread}")
        return matches[0]

    def codex_queue(self, task: str, marker: str) -> str:
        if self.dry_run:
            return "dry-run-queued"
        safe_task = (
            f"{marker}\n\n{task}\n\n"
            "Границы: запись только в D:\\SIMM_GITHUB_CLEAN; "
            "D:\\Phoxinus_X-Ray исключительно для чтения. "
            "Не изменяй исходные исследовательские данные. "
            "Если задание опасно или неоднозначно, остановись и верни BLOCKED с причиной.\n"
        )
        exe = self.config["codex"]["exe"]
        thread = self.config["codex"]["thread_id"]
        cp = run_command([exe, "queue", "--thread", thread, "--message", safe_task], 60, self.repo_root)
        if cp.returncode != 0:
            raise AutopilotError(f"codex queue failed rc={cp.returncode}: {cp.stderr[:1000]}")
        output = cp.stdout.strip()
        self.log(f"codex queue: {output}")
        return output

    def codex_wait(self, marker: str) -> Dict[str, Any]:
        rollout = self.find_codex_rollout()
        timeout_s = int(self.config["limits"]["codex_wait_timeout_s"])
        poll_s = int(self.config["limits"]["poll_codex_s"])
        deadline = time.monotonic() + timeout_s
        seen_user = False
        while time.monotonic() < deadline:
            if self.stop_requested():
                self.state["pending"] = {"codex_marker": marker, "status": "waiting_after_stop_request"}
                self.save_state()
                raise AutopilotError("Stopped while Codex was running; task may still finish in Codex")
            if self.pause_requested():
                if self.wait_with_control(2) == "stop":
                    continue
                continue
            result = self.scan_codex_rollout(rollout, marker)
            if result.get("user_seen"):
                seen_user = True
            if seen_user and result.get("task_complete"):
                return result
            self.check_rate_limit(result)
            time.sleep(poll_s)
        raise AutopilotError("Timeout waiting for Codex completion")

    @staticmethod
    def scan_codex_rollout(path: Path, marker: str) -> Dict[str, Any]:
        user_seen = False
        complete: Optional[Dict[str, Any]] = None
        last_rate_limit: Optional[Dict[str, Any]] = None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if marker not in line and '"type":"task_complete"' not in line and '"type":"token_count"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "response_item":
                    payload = obj.get("payload") or {}
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        content = json.dumps(payload.get("content") or [], ensure_ascii=False)
                        if marker in content:
                            user_seen = True
                if obj.get("type") == "event_msg":
                    payload = obj.get("payload") or {}
                    if payload.get("type") == "task_complete":
                        complete = {
                            "task_complete": True,
                            "turn_id": payload.get("turn_id"),
                            "duration_ms": payload.get("duration_ms"),
                            "last_agent_message": payload.get("last_agent_message"),
                            "timestamp": obj.get("timestamp"),
                        }
                    if payload.get("type") == "token_count":
                        last_rate_limit = (payload.get("rate_limits") or {})
        return {
            "user_seen": user_seen,
            "task_complete": bool(complete),
            "completion": complete,
            "rate_limits": last_rate_limit,
        }

    def check_rate_limit(self, scan: Dict[str, Any]) -> None:
        limits = scan.get("rate_limits") or {}
        if not limits:
            return
        if limits.get("rate_limit_reached_type") or limits.get("spend_control_reached"):
            primary = (limits.get("primary") or {}).get("resets_at")
            secondary = (limits.get("secondary") or {}).get("resets_at")
            resume_at = max([x for x in (primary, secondary) if isinstance(x, (int, float))] or [time.time() + 3600])
            self.state["status"] = "paused_by_limit"
            self.state["limits"]["paused_until"] = dt.datetime.fromtimestamp(resume_at, UTC).isoformat()
            self.state["limits"]["last_rate_limit"] = limits
            self.save_state()
            raise AutopilotError("Codex rate/spend limit reached; state saved and autopilot paused")

    def send_result_and_request_next(self, cycle_id: str, result: Dict[str, Any]) -> Optional[str]:
        completion = result.get("completion") or {}
        text = completion.get("last_agent_message") or ""
        next_begin = f"AUTOPILOT_TASK_BEGIN_NEXT_{cycle_id}"
        next_end = f"AUTOPILOT_TASK_END_NEXT_{cycle_id}"
        prompt = (
            f"AUTOPILOT_RESULT_{cycle_id}\n\n"
            "Codex завершил задание. Результат ниже.\n\n"
            "```\n" + text[:12000] + "\n```\n\n"
            f"Подтверди получение. Затем, если есть следующее задание для Codex, верни его строго между {next_begin} и {next_end}. "
            f"Если задания нет, верни ровно NO_TASK_{cycle_id}. Не запускай Codex сам и не меняй файлы.\n"
        )
        before = self.chatgpt_read()["text"].count(next_begin)
        self.chatgpt_send(prompt)
        deadline = time.monotonic() + int(self.config["limits"]["chatgpt_wait_timeout_s"])
        while time.monotonic() < deadline:
            if self.stop_requested():
                raise AutopilotError("Stopped while waiting for ChatGPT next task")
            if self.pause_requested():
                if self.wait_with_control(2) == "stop":
                    raise AutopilotError("Stopped while paused")
                continue
            body = self.chatgpt_read()["text"]
            if body.count(next_begin) >= before + 2 or f"NO_TASK_{cycle_id}" in body:
                blocks = re.findall(re.escape(next_begin) + r"(.*?)" + re.escape(next_end), body, flags=re.S)
                if blocks:
                    return blocks[-1].strip() or None
                return None
            time.sleep(int(self.config["limits"]["poll_control_s"]))
        raise AutopilotError("Timeout waiting for ChatGPT next task")

    def note_processed(self, marker: str) -> None:
        markers = self.state.setdefault("processed_markers", [])
        if marker not in markers:
            markers.append(marker)
        del markers[:-50]

    def run_once(self) -> str:
        limits = self.config["limits"]
        max_cycles = int(limits["max_cycles"])
        cycles_this_run = 0
        while cycles_this_run < max_cycles:
            if self.stop_requested():
                self.state["status"] = "stopped"
                self.save_state()
                return "stopped"
            if self.pause_requested():
                self.state["status"] = "paused"
                self.save_state()
                if self.wait_with_control(5) == "stop":
                    continue
                continue
            if self.dry_run:
                cycle = int(self.state.get("cycle", 0)) + 1
                cycle_id = f"DRYRUN_{dt.datetime.now():%Y%m%d_%H%M%S}_{cycle:02d}"
                task = f"dry-run task {cycle_id}"
                result = {"completion": {"last_agent_message": "OK_DRY_RUN", "duration_ms": 0}}
                self.note_processed(sha256_text(task)[:16])
                self.state["cycle"] = cycle
                self.state["status"] = "dry_run_complete"
                self.state["last_result"] = {"hash": sha256_text(result["completion"]["last_agent_message"]), "chars": len("OK_DRY_RUN")}
                self.save_state()
                return "dry_run_complete"

            self.ensure_chatgpt_session()
            cycle = int(self.state.get("cycle", 0)) + 1
            cycles_this_run += 1
            cycle_id = f"MLAP_{dt.datetime.now():%Y%m%d_%H%M%S}_{cycle:02d}"
            self.state["status"] = "requesting_task"
            self.state["cycle"] = cycle
            self.save_state()
            task = self.request_task(cycle_id)
            if not task:
                self.state["status"] = "idle_no_task"
                self.save_state()
                if cycles_this_run >= max_cycles:
                    return "idle_no_task"
                if self.wait_with_control(int(limits["idle_sleep_s"])) == "stop":
                    continue
                continue
            task_hash = sha256_text(task)
            if task_was_attempted(task_hash, self.state):
                self.state["status"] = "duplicate_or_previously_attempted_task_skipped"
                self.save_state()
                continue
            marker = f"MLAP_CODEX_{cycle_id}_{task_hash[:12]}"
            self.state.setdefault("attempted_task_hashes", []).append(task_hash)
            del self.state["attempted_task_hashes"][:-100]
            self.state["status"] = "queued_to_codex"
            self.state["pending"] = {"cycle_id": cycle_id, "task_hash": task_hash, "marker": marker, "queued_at": now_iso()}
            self.save_state()
            try:
                self.codex_queue(task, marker)
            except Exception:
                self.state["status"] = "queue_failed_task_not_retried"
                self.state["pending"] = {}
                self.save_state()
                raise
            self.state["status"] = "waiting_codex"
            self.save_state()
            result = self.codex_wait(marker)
            self.state["pending"] = {}
            self.note_processed(task_hash)
            self.state["status"] = "sending_result"
            self.state["last_result"] = {
                "cycle_id": cycle_id,
                "task_hash": task_hash,
                "turn_id": (result.get("completion") or {}).get("turn_id"),
                "duration_ms": (result.get("completion") or {}).get("duration_ms"),
                "result_hash": sha256_text((result.get("completion") or {}).get("last_agent_message") or ""),
            }
            self.save_state()
            next_task = self.send_result_and_request_next(cycle_id, result)
            self.state["status"] = "cycle_complete" if next_task else "idle_no_task"
            self.save_state()
            if not next_task:
                if self.wait_with_control(int(limits["idle_sleep_s"])) == "stop":
                    continue
        self.state["status"] = "max_cycles_reached"
        self.save_state()
        return "max_cycles_reached"

    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "control": {"stop": self.stop_requested(), "pause": self.pause_requested()},
            "log_file": str(self.log_file),
        }


def self_test() -> None:
    sample = "prefix AUTOPILOT_TASK_BEGIN_X\nDo safe thing\nAUTOPILOT_TASK_END_X suffix"
    assert MorphoLabelAutopilot.extract_task(sample, "X") == "Do safe thing"
    assert MorphoLabelAutopilot.extract_task("NO_TASK_X", "X") is None
    assert sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    print("SELF_TEST_OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="MorphoLabel autopilot coordinator")
    parser.add_argument("--config", default="autopilot/config/autopilot.config.json")
    parser.add_argument("--once", action="store_true", help="Run the bounded loop from config.max_cycles and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not call Browse/Codex; validate control/state only")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    app = MorphoLabelAutopilot((Path.cwd() / args.config).resolve(), dry_run=args.dry_run)
    if args.status:
        print(json.dumps(app.status(), ensure_ascii=False, indent=2))
        return 0
    try:
        result = app.run_once()
        app.log(f"finished: {result}")
        return 0
    except Exception as exc:  # keep state readable for the operator
        if app.state.get("status") != "blocked_incomplete_chatgpt_task":
            app.state["status"] = "error"
        app.state["last_error"] = f"{type(exc).__name__}: {exc}"
        app.save_state()
        app.log(f"ERROR {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
