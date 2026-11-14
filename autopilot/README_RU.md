# MorphoLabel Autopilot — минимальная связка ChatGPT ↔ Codex

Дата сборки: 2026-11-14.

## Что проверено вручную перед сборкой

1. **ChatGPT → OpenCode Browse**: чтение и отправка сообщений во вкладке `2 MorphoLabel` работают.
2. **Codex «2 работа» без CLI-resume**: команда `codex queue --thread 01a1da96-a6d4-7322-bf3c-f294840f0565 --message ...` успешно ставит сообщение в существующую сессию. Desktop принял тест и ответил `OK_AUTOPILOT_Q`; `task_complete` появился в rollout-файле.
3. **Полный тестовый цикл ChatGPT → Codex → ChatGPT** выполнен на маркере `AUTOPILOT_CYCLE_TEST_20261114_02`: ChatGPT выдал безопасное задание, Codex ответил `OK_AUTOPILOT_CYCLE`, результат возвращён в ChatGPT и подтверждён.

## Как запустить

- Фоново: `AUTOPILOT_START.cmd`
- Видимо в текущем окне: `AUTOPILOT_START_FOREGROUND.cmd`
- Статус: `AUTOPILOT_STATUS.cmd`

Скрипт выполняет не более `limits.max_cycles` циклов из `autopilot/config/autopilot.config.json` и завершается. Для длительной работы увеличьте `max_cycles` осознанно.

## Как остановить или приостановить

- Пауза: `AUTOPILOT_PAUSE.cmd`
- Снять паузу: `AUTOPILOT_RESUME.cmd`
- Стоп на ближайшей безопасной точке: `AUTOPILOT_STOP.cmd`

`AUTOPILOT_STOP.cmd` не убивает уже запущенный Codex-процесс и не редактирует внутренние файлы Codex. Он просит координатор остановиться. Принудительное завершение только координатора: `powershell -File autopilot\scripts\Stop-MorphoLabelAutopilot.ps1 -ForceKillCoordinator`.

## Что делает координатор

1. Находит вкладку ChatGPT по названию/URL через `browse status --json` и делает `browse session adopt` в отдельную сессию `morpholabel-autopilot`.
2. Просит у ChatGPT задание строго между маркерами `AUTOPILOT_TASK_BEGIN_<cycle>` и `AUTOPILOT_TASK_END_<cycle>`.
3. Передаёт задание в Codex только через `codex queue --thread <ID> --message <текст>`.
4. Ждёт завершения read-only чтением rollout-файла Codex; не опрашивает языковую модель для мониторинга.
5. Возвращает результат в ChatGPT и просит следующее задание.
6. Хранит только хэши/ID/статусы в `autopilot/runtime/autopilot_state.json`; безопасная копия без текстов заданий — `autopilot/state/last_safe_state.json`.

## Ограничения безопасности

- Разрешённая запись: только `D:\SIMM_GITHUB_CLEAN`.
- `D:\Phoxinus_X-Ray` — только чтение; скрипт туда не пишет.
- Конфиденциальные материалы не отправляются в GitHub. Автокоммит выключен (`github.auto_commit=false`).
- Нет ручного редактирования rollout/queue/internal Codex файлов.
- Повторное исполнение задания ограничено по SHA-256 текста задания в `processed_markers`.

## Управление чатами ChatGPT

Реализован консервативный контур: активный чат хранится в состоянии, а конфиг содержит `rotation.project_base_url` и следующее имя чата. Автоматический переход **отключён** (`rotation.enabled=false`) и требует подтверждения пользователя. Причина: безопасное создание следующего чата строго внутри того же ChatGPT-проекта через Browse ещё не подтверждено отдельным тестом. До подтверждения автопилот не должен считаться полностью автономным по пункту смены чатов.

## Состояние и логи

- Runtime/control/log: `autopilot/runtime/`, `autopilot/control/`, `autopilot/logs/` — не коммитятся.
- Безопасный экспорт состояния: `autopilot/state/last_safe_state.json`.
- Испытания: `autopilot/results/`.

## Текущий статус готовности

Связка ChatGPT ↔ Codex ↔ ChatGPT проверена на безопасном маркере. Автопилот можно запускать для ограниченных циклов, но **нельзя оставлять полностью без присмотра**, пока отдельно не проверены: смена чата ChatGPT внутри проекта, восстановление после реального лимита Codex и реальное содержательное задание MorphoLabel.
