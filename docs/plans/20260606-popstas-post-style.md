# Skill стиля постов (popstas-post-style)

## Overview

Создать skill, который пишет публичные посты в моём стиле — как в моих Telegram-каналах
(и отдельно — как в блоге). Подход: сначала собрать **style fingerprint** (темы, структура,
ритм, словарь, интонации, форматирование, запреты) метриками на Python, затем превратить
признаки в skill (правила, профиль, примеры, анти-примеры, чеклист, режимы генерации) и
проверить его на отложенной выборке реальных постов.

Главный принцип: копировать не поверхностные признаки («пиши короткими абзацами»), а связку
**мыслительный паттерн + интонация + структура + словарь + форматирование + анти-стиль**.
Авто-анализ всегда сверяется вручную — модель может «галлюцинировать» стиль, которого нет.

## Context

- Готовый skill кладётся в `~/.claude/skills/popstas-post-style/` (имя уточнить при сборке).
- Артефакты анализа (корпус, статистика, профиль, черновики, примеры, eval) — в
  `data/style-skill/` этого репозитория (gitignored). Это не код telegram-download-chat.
- **Python-first**: весь анализ — скриптами на Python (живут в `data/style-skill/scripts/`).
  LLM используется минимально, только где без него не обойтись (формулировки профиля,
  разметка «звучит как я», финальные примеры). Шаблоны можно генерировать отдельно.
- По каждой задаче — минимум 1 документ с результатами. Отдельный обязательный документ со
  статистикой исключённых постов (что исключено и почему).
- **Precondition (выполняется вручную, до запуска)**: корпус скачивается отдельно — нужна
  интерактивная Telegram-авторизация и членство в приватных каналах, поэтому это НЕ часть
  автономного прогона. До старта должно существовать:
  - `data/style-skill/corpus/channels/<chat>/messages.json` для 9 каналов (media НЕ качать):
    `@popstas_llm`, `@popstas_llm_examples`, `@popstas_music`, `3318641615` (2026 год),
    `2361996411` (Пхукет 2025), `3681427400` (Пхукет 2026), `1683646732` (техническое),
    `2049434548` (общий), `1864803890` (умный дом).
  - `data/style-skill/corpus/blog/` — копии `.md` из `/home/popstas/projects/site/blog.popstas.ru/content/post/`.
  - `data/style-skill/corpus/SOURCES.md` — что скачано, дата, число постов на источник.
- Adopted from `data/TODO.md` (free-form план + метод из `data/style-skill-create-chatgpt-answer.md`).

## Development Approach

- Testing approach: regular
- Complete each task fully before moving to the next
- Update this plan when scope changes during implementation

## Testing Strategy

- Unit tests required for каждого Python-скрипта анализа (фикстуры на маленьком корпусе)
- Run project tests after each Task before proceeding
- Основной критерий приёмки skill — held-out выборка реальных постов (Task 6)

## Implementation Steps

### Task 1: Сбор и нормализация корпуса + held-out

- [ ] `scripts/load_corpus.py`: прочитать все `messages.json` + блог `.md`, привести к единой
      записи (`source, post_id, date, text, links[], reactions_total, views?, forwards?,
      replies?, is_forward, type_raw`) → `data/style-skill/corpus/normalized.jsonl`.
- [ ] Сгруппировать подряд идущие сообщения одного автора в одну «тему/сессию», пометить
      `is_thread_start` (анализ начал постов идёт только по первым постам темы).
- [ ] `scripts/make_holdout.py`: отложить случайную выборку (30–50 постов) в
      `data/style-skill/eval/holdout.json`; held-out исключается из анализа фаз 2–4.
- [ ] Документ `data/style-skill/results/01-corpus.md`: число постов на источник, число тем,
      распределение по датам, размер held-out.
- [ ] write tests for the corpus-loading and holdout scripts
- [ ] run project tests - must pass before next task

### Task 2: Очистка и категоризация

- [ ] Эвристиками исключить/пометить (не удалять): репосты, чужие цитаты, служебные
      сообщения, рекламу, инструкции/описания, посты только со ссылкой, ссылки на другие
      каналы/посты, дубли, слишком короткие сообщения.
- [ ] Категоризировать посты по типу (короткая мысль / тех-заметка / пост-вывод / анонс /
      эмоциональное наблюдение / длинное объяснение / пост-вопрос / пост со ссылкой /
      репост). Эвристики + минимальная LLM-разметка только на спорных.
- [ ] Документ `data/style-skill/results/02-excluded.md` (обязательный): что исключено и
      почему, по каждому правилу счётчик и примеры.
- [ ] Документ `data/style-skill/results/02-categories.md`: сколько постов в каждом типе.
- [ ] write tests for the cleaning/categorization heuristics
- [ ] run project tests - must pass before next task

### Task 3: Авто-анализ метриками

- [ ] Начала постов (только `is_thread_start`) и концовки: топ типичных шаблонов.
- [ ] Частотные слова/фразы: топ-100 слов, биграммы/триграммы, вводные конструкции; топ
      повторяющихся целых предложений/реплик.
- [ ] Лексические категории (сомнение/вывод/контраст/практика/оценка/усиление/англицизмы/
      связки) + список **запрещённых** нейросеточных слов, которых у меня нет.
- [ ] Пунктуация и форматирование (заголовки, жирный, `код`, списки, эмодзи, кавычки,
      скобки, многоточия, тире/двоеточия, пустые строки, доля вопросов; для тех-каналов —
      оформление команд/продуктов/ссылок/цитат/англотерминов).
- [ ] Длина и ритм (длина поста, число/длина абзацев, доля коротких/длинных предложений,
      доля постов со списками/подзаголовками, 1 тезис vs много).
- [ ] Интонация (метрики-прокси + ручная сверка), мыслительные паттерны, отношение к
      аудитории («ты/вы/мы», вопросы, споры, обратная связь), уровень конкретики.
- [ ] Документ `data/style-skill/results/03-metrics.md`: все метрики + словесные выводы-правила.
- [ ] write tests for the metric/frequency scripts
- [ ] run project tests - must pass before next task

### Task 4: Эталоны, структуры, анти-стиль

- [ ] Структуры поста: перечислить все встречающиеся схемы, отметить самые частые →
      `data/style-skill/results/04-structures.md`.
- [ ] Эталонные посты: отобрать (метрики + ручная сверка) 20 лучших, 20 обычных, 10
      «не имитировать» → `data/style-skill/results/04-reference-posts.md`.
- [ ] Анти-стиль: явный список «как НЕ надо» → `data/style-skill/results/04-anti-style.md`.
- [ ] write tests for the selection/scoring scripts
- [ ] run project tests - must pass before next task

### Task 5: Сборка skill в ~/.claude/skills/popstas-post-style/

- [ ] `SKILL.md`: задача, когда использовать, как анализировать вход, алгоритм генерации
      (тип → тезис → структура → черновик → сверка с профилем → убрать нейросеточность →
      добавить конкретику → проверить длину/ритм → 2–3 варианта для творческих задач), запреты.
- [ ] `style-profile.md` (или `profile/voice|structure|vocabulary|formatting|anti-style.md`).
- [ ] `post-types.md`: шаблоны под типы постов (цель/длина/структура/пример/чего избегать).
- [ ] `examples-good.md` (10–30 эталонов с комментариями) и `examples-bad.md` (плохие имитации).
- [ ] `checklist.md` (финальная самопроверка) и `extraction-notes.md` (ссылки на доки анализа).
- [ ] write tests / валидацию структуры skill-файлов
- [ ] run project tests - must pass before next task

### Task 6: Eval на held-out реальных постах

- [ ] Для каждого held-out поста извлечь тему/тезис (скриптом, LLM минимально) и попросить
      skill сгенерировать пост из тезиса, не показывая оригинал.
- [ ] `scripts/compare_holdout.py`: метрический оверлап оригинал↔сгенерированное (длина,
      абзацы, доля вопросов/списков/эмодзи, пересечение лексики/зачинов/концовок, наличие
      запрещённых слов) → числовой score на пост.
- [ ] Ручная сверка 1–5 (похоже на автора / не похоже на ChatGPT / конкретно / сохранён
      смысл / можно публиковать без правки); `eval/test-prompts.md` + `eval/scoring.md` для
      дополнительных творческих задач.
- [ ] Итерировать профиль/skill, пока метрики и ручные оценки по held-out не пройдут порог;
      результаты и пороги → `data/style-skill/results/06-eval.md`.
- [ ] write tests for the holdout-comparison script
- [ ] run project tests - must pass before next task

### Task 7: Блог отдельно

- [ ] Прогнать те же шаги (нормализация → очистка → метрики → эталоны/структуры/анти-стиль)
      по блогу отдельно, результирующие доки с префиксом `blog-` →
      `data/style-skill/results/07-blog-*.md`.
- [ ] write tests / переиспользовать тесты скриптов на блог-корпусе
- [ ] run project tests - must pass before next task

### Task 8: Сравнение каналов и блога + примеры

- [ ] Сравнить стиль каналов и блога → `data/style-skill/results/08-channels-vs-blog.md`.
- [ ] Сгенерировать несколько примеров постов на основе стиля (каналы и блог отдельно) →
      `data/style-skill/results/08-generated-examples.md`.
- [ ] run project tests - must pass before next task

### Task 9: Verify acceptance criteria

- [ ] verify all requirements from Overview are implemented (корпус→анализ→skill→eval→блог→сравнение)
- [ ] подтвердить, что held-out метрики и ручные оценки прошли заданные пороги
- [ ] run full project test suite
- [ ] run project linter - all issues must be fixed

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- Корпус каналов/блога скачивается вручную ДО запуска (интерактивная Telegram-авторизация),
  см. Precondition в Context.
- Установленный skill `~/.claude/skills/popstas-post-style/` — вне git этого репозитория;
  проверить вручную после прогона.
