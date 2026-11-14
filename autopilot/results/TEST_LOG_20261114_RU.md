# Autopilot test log — 2026-11-14

## Проверено вручную через OpenCode/Kimi

1. Browse ↔ ChatGPT `2 MorphoLabel`: чтение и отправка сообщений работают.
2. Codex `2 работа`: `codex queue --thread 01a1da96-a6d4-7322-bf3c-f294840f0565 --message ...` без `--resume` доставил тест `AUTOPILOT_Q_TEST_20261114_01`; Codex ответил `OK_AUTOPILOT_Q`, rollout содержит `task_complete`.
3. Полный маркерный цикл: ChatGPT выдал `<AUTOPILOT_TASK>` → задание передано в Codex через `codex queue` → Codex вернул `OK_AUTOPILOT_CYCLE` → результат возвращён в ChatGPT → ChatGPT подтвердил получение.

## Проверено скриптами

- `python -m unittest autopilot.tests.test_autopilot_core -v` — OK, 3/3.
- `python autopilot/scripts/morpholabel_autopilot.py --config autopilot/config/autopilot.config.json --self-test` — `SELF_TEST_OK`.
- `AUTOPILOT_DRYRUN.cmd` — завершился `dry_run_complete` без обращений к Browse/Codex.
- `AUTOPILOT_PAUSE.cmd`, `AUTOPILOT_RESUME.cmd`, `AUTOPILOT_STOP.cmd` — создают/снимают control-маркеры; `AUTOPILOT_STATUS.cmd` показывает `stop=false`, `pause=false` после очистки.

## Не проверено / не включено

- Автоматическое создание следующего чата ChatGPT строго внутри проекта. Механизм обозначен в конфиге, но `rotation.enabled=false` до отдельного безопасного теста.
- Реальное восстановление после исчерпания лимита Codex не проверялось новым запуском; обработчик rate limit в скрипте сохраняет состояние и останавливается с ошибкой/паузой, но не был испытан на реальном лимите.
- Содержательное задание MorphoLabel через автопилот не запускалось; пройден только безопасный маркерный цикл.

Вывод: автопилот не объявляется полностью готовым. Ограниченные циклы можно запускать под наблюдением после установки разумного `limits.max_cycles`.

## Регрессионная проверка задания — исправление после BLOCKED

- Причина: прежний extractor принимал любой непустой блок между маркерами, включая `<задание>` и текст только с ограничениями; затем `codex_queue` добавлял к нему ограничения и отправлял как будто это задание.
- Исправлено: ChatGPT должен предоставить четыре содержательных поля `TASK`, `GOAL`, `ACCEPTANCE`, `CONSTRAINTS`. Placeholder/отсутствующее поле отклоняется; ChatGPT получает максимум три запроса на уточнение. После исчерпания попыток автопилот фиксирует `blocked_incomplete_chatgpt_task` и ничего не ставит в очередь Codex.
- Хэш любого задания фиксируется до вызова `codex queue`; неудачная/неопределённая попытка не отправляется повторно.
- `max_cycles` ограничен одним циклом за запуск, чтобы перед первым запуском не было нескольких заданий подряд.
- Проверки выполняются локально; Codex/Browse и внешние сервисы для тестов не вызывались.
