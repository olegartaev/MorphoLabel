import io
import json
import unittest

from autopilot.scripts.morpholabel_autopilot import (
    MAX_TASK_REQUESTS,
    MorphoLabelAutopilot,
    sha256_text,
    task_completeness_error,
    task_was_attempted,
)


class AutopilotCoreTests(unittest.TestCase):
    def test_extract_task(self):
        text = "pre AUTOPILOT_TASK_BEGIN_T1\nTask body\nAUTOPILOT_TASK_END_T1 post"
        self.assertEqual(MorphoLabelAutopilot.extract_task(text, "T1"), "Task body")

    def test_extract_no_task(self):
        self.assertIsNone(MorphoLabelAutopilot.extract_task("NO_TASK_T2", "T2"))

    def test_sha256(self):
        self.assertEqual(
            sha256_text("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_rejects_placeholder_or_constraints_only_task(self):
        self.assertIsNotNone(task_completeness_error("<задание>"))
        self.assertIsNotNone(task_completeness_error("Только ограничения доступа к каталогам."))

    def test_requires_task_goal_acceptance_and_constraints(self):
        incomplete = "TASK: Выполни анализ данных.\nCONSTRAINTS: Только разрешённые локальные пути."
        self.assertIn("GOAL", task_completeness_error(incomplete))
        self.assertIn("ACCEPTANCE", task_completeness_error(incomplete))

    def test_accepts_complete_actionable_task(self):
        task = (
            "TASK: Проанализировать существующие отчёты ошибок распознавания и подготовить сводную таблицу.\n"
            "GOAL: Выбрать следующий ограниченный этап улучшения распознавания позвоночных структур.\n"
            "ACCEPTANCE: Таблица содержит источники, проверенные показатели, ограничения и проходит новые unit-тесты.\n"
            "CONSTRAINTS: Запись только в рабочем репозитории; проект D:\\Phoxinus_X-Ray читать без изменений; исходные снимки не менять."
        )
        self.assertIsNone(task_completeness_error(task))

    def test_retry_limit_is_bounded(self):
        self.assertEqual(MAX_TASK_REQUESTS, 3)
        prompt = MorphoLabelAutopilot.task_request_prompt("T4", "BEGIN", "END", 2, "missing GOAL")
        self.assertIn("TASK:", prompt)
        self.assertIn("GOAL:", prompt)
        self.assertIn("ACCEPTANCE:", prompt)
        self.assertIn("CONSTRAINTS:", prompt)
        self.assertIn("missing GOAL", prompt)

    def test_previous_attempt_is_not_queued_again(self):
        digest = sha256_text("same task")
        self.assertTrue(task_was_attempted(digest, {"attempted_task_hashes": [digest]}))
        self.assertTrue(task_was_attempted(digest, {"processed_markers": [digest]}))
        self.assertFalse(task_was_attempted(digest, {}))

    def test_incomplete_task_is_rejected_before_queue(self):
        task, error = MorphoLabelAutopilot.extract_task_with_validation(
            "AUTOPILOT_TASK_BEGIN_T3\n<задание>\nAUTOPILOT_TASK_END_T3", "T3"
        )
        self.assertEqual(task, "<задание>")
        self.assertIsNotNone(error)


    def test_rejects_formatted_examples_that_could_reach_codex(self):
        legacy = (
            "TASK: конкретные действия, ожидаемые файлы/результат и необходимый объём работы.\n"
            "GOAL: цель этого этапа и зачем он нужен.\n"
            "ACCEPTANCE: проверяемые критерии завершения и требуемые проверки.\n"
            "CONSTRAINTS: запись только в D:\\SIMM_GITHUB_CLEAN; D:\\Phoxinus_X-Ray только для чтения."
        )
        self.assertIsNotNone(task_completeness_error(legacy))
        prompt = MorphoLabelAutopilot.task_request_prompt(
            "TEST", "AUTOPILOT_TASK_BEGIN_TEST", "AUTOPILOT_TASK_END_TEST", 1
        )
        example = MorphoLabelAutopilot.extract_task(prompt, "TEST")
        self.assertIsNotNone(task_completeness_error(example or ""))

    def test_response_markers_require_complete_new_reply(self):
        begin = "AUTOPILOT_TASK_BEGIN_T5"
        end = "AUTOPILOT_TASK_END_T5"
        no_task = "NO_TASK_T5"
        prompt = MorphoLabelAutopilot.task_request_prompt("T5", begin, end, 1)
        self.assertFalse(MorphoLabelAutopilot.has_new_complete_task(prompt, begin, end, 0, 0))
        self.assertFalse(MorphoLabelAutopilot.has_new_no_task(prompt, no_task, 0))
        self.assertFalse(
            MorphoLabelAutopilot.has_new_complete_task(prompt + begin, begin, end, 0, 0)
        )
        reply = begin + "\nTASK: Проверить состояние тестов\nGOAL: Установить причину сбоя\n" + (
            "ACCEPTANCE: Сохранён результат проверки\nCONSTRAINTS: Запись только в проект\n"
        ) + end
        self.assertTrue(MorphoLabelAutopilot.has_new_complete_task(prompt + reply, begin, end, 0, 0))
        self.assertTrue(MorphoLabelAutopilot.has_new_no_task(prompt + no_task, no_task, 0))

    def test_codex_completion_must_follow_the_correct_user_marker(self):
        marker = "MLAP_CODEX_T7"
        old_complete = {"type": "event_msg", "payload": {
            "type": "task_complete", "last_agent_message": "OLD"
        }}
        queued_user = {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"text": marker}]
        }}
        new_complete = {"type": "event_msg", "payload": {
            "type": "task_complete", "last_agent_message": "NEW"
        }}
        other_user = {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"text": "another queue item"}]
        }}

        class MemoryRollout:
            def __init__(self, events):
                self.data = "\n".join(json.dumps(ev, ensure_ascii=False) for ev in events)

            def open(self, **_kwargs):
                return io.StringIO(self.data)

        premature = MorphoLabelAutopilot.scan_codex_rollout(
            MemoryRollout([old_complete, queued_user]), marker
        )
        self.assertTrue(premature["user_seen"])
        self.assertFalse(premature["task_complete"])
        proper = MorphoLabelAutopilot.scan_codex_rollout(
            MemoryRollout([old_complete, queued_user, new_complete]), marker
        )
        self.assertTrue(proper["task_complete"])
        self.assertEqual(proper["completion"]["last_agent_message"], "NEW")
        interleaved = MorphoLabelAutopilot.scan_codex_rollout(
            MemoryRollout([queued_user, other_user, new_complete]), marker
        )
        self.assertTrue(interleaved["interleaved"])
        self.assertFalse(interleaved["task_complete"])


if __name__ == "__main__":
    unittest.main()
