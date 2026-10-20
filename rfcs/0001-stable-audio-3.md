# RFC 0001 — Stable Audio 3 в Remiqora

Статус: принят; фазы 1 и 2 реализованы в ветке `feat/stable-audio-3` (сервер `external/sa3-server`, движок в оркестраторе, страница Stable Audio 3, выбор «движок · модель» в аранжировщике). Фаза 3 (панель «Сэмплы») тоже реализована. Фаза 4 (скачивание весов из приложения, setup-скрипты, desktop-установщик, README) реализована с отступлениями от раздела 8, они описаны там же.

## 1. Зачем

Stable Audio 3 (Stability AI, май 2026, открытые веса small/medium) закрывает то, чего нет ни у ACE-Step, ни у YuE2:

| Что даёт | Где в Remiqora |
|---|---|
| Честный **inpainting** и **continuation** по аудио-контексту | режимы Repaint и Continue в AI-аранжировщике |
| **Audio-to-audio** с регулируемым `init_noise_level` | режим Cover (ползунок силы = noise level) |
| **Звуковые эффекты, one-shot и сэмплы** (Freesound в датасете) | новая панель «Сэмплы» в редакторе |
| Инструментал без тяги к песенной форме, 44.1 кГц стерео | страница генерации, как у ACE-Step |
| Скорость: 8 шагов ≈ 0.5 с на RTX 4080, загрузка модели ≈ 40 с, ≈ 6 ГБ VRAM | варианты пачками по 4 без ожидания |

Чего не даёт: вокала и текста (только инструментал), режима Lego (партия поверх микса), треков длиннее 380 с (medium) / 120 с (small).

Модели: `medium` (1.4B, GPU + flash-attn, музыка и SFX), `small-music` (433M), `small-sfx` (433M, работает даже на CPU). Лицензия: Stability AI Community License (бесплатно до $1M годового дохода) + Gemma Terms для текстового энкодера. Веса на Hugging Face закрыты (gated, авто-одобрение после принятия условий).

## 2. Принципы

1. **Тот же контракт движка, что у ACE-Step и YuE2**: отдельный процесс с HTTP API, запускаемый оркестратором, проксируемый через `/api/<prefix>/*`. Оркестратор, прокси, таблица треков и измерители памяти подхватывают его автоматически, когда он появляется в `MODELS` (см. `backend/app/config.py`).
2. **Свой сервер, а не Gradio**. У Stable Audio 3 нет HTTP API, только Python-пакет и Gradio с `share=True`. Пишем тонкий FastAPI-сервер (наш код, MIT), который оборачивает `StableAudioModel.generate`.
3. **Аранжировщик не узнаёт о новой модели ничего, кроме имени движка**. Геометрия контекста (`ctxStart/ctxEnd/regionStart/regionEnd`), `holdRange`, швы (`SEAM`), `variantClip`, `insertVariants` остаются как есть. Сервер возвращает аудио в той же форме, что ACE-Step: для repaint/continue полный контекст от `ctxStart`, для cover кусок той же длины, что вход, от `regionStart`.
4. **Строгая взаимная исключительность движков сохраняется** в первой фазе. Совместное проживание SA3 (6 ГБ) с ACE-Step turbo откладываем: найденные в `manager.py` дыры конкурентного режима (`stop_active`, Unload и выход из desktop гасят только `active_model`) надо чинить отдельно.
5. **Одна точка входа для пользователя**: движок появляется в шапке, на главной и в аранжировщике так же, как существующие, со всеми состояниями «не установлен / остановлен / запускается».

## 3. Сервер `sa3-server`

### 3.1 Где живёт

Новый uv-проект в репозитории: `external/sa3-server/` (в отличие от ACE-Step и audio.cpp это наш код, он коммитится). Состав:

```
external/sa3-server/
  pyproject.toml        # зависимости: stable-audio-3 (git, pin 77e0398), fastapi, uvicorn, python-multipart, soundfile
  sa3_server/
    __init__.py
    main.py             # FastAPI app, CLI: --host --port --models-dir --preload
    engine.py           # загрузка моделей, очередь, генерация
    jobs.py             # реестр задач, статусы, отмена
    audio.py            # wav I/O, нормализация, обрезка до duration
```

`[tool.uv]` закрепляет индекс PyTorch (cu128 на Windows/Linux, как делает `setup_models.ps1` для Demucs) и платформенный источник flash-attn:

```toml
[project]
dependencies = [
  "stable-audio-3 @ git+https://github.com/Stability-AI/stable-audio-3@77e0398c26f7d22d801ec1bb036307e8b231f741",
  "fastapi>=0.115", "uvicorn>=0.30", "python-multipart", "soundfile>=0.13",
  "flash-attn @ https://huggingface.co/lldacing/flash-attention-windows-wheel/resolve/main/flash_attn-2.7.4.post1%2Bcu128torch2.7.0cxx11abiFALSE-cp312-cp312-win_amd64.whl ; sys_platform == 'win32'",
]
requires-python = ">=3.12,<3.13"
```

На Linux flash-attn ставится из prebuilt-колёс mjun0812 той же парой (torch 2.7.1 / cu128 / cp312); на macOS medium недоступен, доступны только small-модели (без flash-attn).

Переопределение для локальной разработки (например, когда GitHub недоступен): `uv add --editable <path-to-stable-audio-3-checkout>` в этой папке без коммита, либо `STABLE_AUDIO_DIR` на уже готовое окружение.

### 3.2 Конфигурация

Переменные в `backend/.env` (по образцу `ACE_STEP_*`):

| Переменная | Значение по умолчанию | Смысл |
|---|---|---|
| `STABLE_AUDIO_DIR` | `E:\AI\StableAudio` (Windows), `~/AI/StableAudio` | папка uv-проекта сервера |
| `STABLE_AUDIO_API_PORT` | `8002` | порт сервера |
| `STABLE_AUDIO_DEVICE` | пусто | `CUDA_VISIBLE_DEVICES` для процесса |
| `STABLE_AUDIO_MODELS` | `medium,small-sfx` | какие чекпойнты сервер готов поднимать |
| `HF_HOME` | наследуется | где лежат веса (кэш Hugging Face) |

Команда процесса: `uv run sa3-server --host 127.0.0.1 --port 8002`, `cwd = STABLE_AUDIO_DIR`, env `PYTHONUTF8=1`, `HF_HUB_OFFLINE=1` (веса уже скачаны; скачивание — отдельный сценарий, см. 7.3).

### 3.3 Жизненный цикл и здоровье

- Сервер поднимается за секунды **без** загрузки весов и отвечает `GET /health` → `200 {"ok": true, "loaded": ["medium"] | []}`. Оркестратор считает процесс здоровым при любом коде < 500, поэтому «running» в шапке появляется быстро, как у ACE-Step с `ON_DEMAND_MODEL_LOAD`.
- Сразу после старта фоновый поток прогревает модель по умолчанию (`--preload medium`). Задача, пришедшая раньше, ждёт загрузки в очереди; в её статусе `stage: "loading_model"`, фронтенд показывает уже существующую подпись «первая генерация дольше».
- Одна резидентная модель за раз (переключение `medium` ↔ `small-sfx` выгружает предыдущую; `torch.cuda.empty_cache()`). На картах ≥ 12 ГБ допускаем две (medium 6 ГБ + small 2 ГБ) — флаг `--max-resident 2`.
- Остановка: обработчики `SIGTERM`/`SIGBREAK` (оркестратор шлёт `CTRL_BREAK_EVENT` на Windows), отменяем очередь, освобождаем GPU, выходим за ≤ 20 с (`shutdown_timeout`).
- Одна рабочая нить на GPU: задачи выполняются строго по очереди; `batch_size` до 4 внутри одной задачи.

### 3.4 HTTP API

Префикс `/v1`, JSON-ответы в «голом» виде (без конверта `{code,data}` как у ACE-Step, он нам не нужен).

| Метод и путь | Тело | Ответ |
|---|---|---|
| `GET /health` | — | `{ok, loaded: [...]}` |
| `GET /v1/models` | — | `[{id, label, installed, loaded, device, max_seconds, tasks: [...]}]` |
| `POST /v1/models/load` | `{model}` | `{loaded: [...]}` |
| `POST /v1/jobs` | multipart, см. ниже | `{job_id, queue_position}` |
| `POST /v1/jobs/query` | `{ids: [...]}` | `[{job_id, status, stage, progress, files: [...], error, seed}]` |
| `POST /v1/jobs/{id}/cancel` | — | `{job_id, status}` |
| `GET /v1/files/{name}` | — | `audio/wav` (поддержка `Range`) |

Поля `POST /v1/jobs` (multipart, числа строками, как принимает ACE-Step):

| Поле | Тип | Описание |
|---|---|---|
| `task` | `text` \| `a2a` \| `inpaint` | режим генерации |
| `model` | `medium` \| `small-music` \| `small-sfx` | чекпойнт |
| `prompt` | str | текст |
| `negative_prompt` | str | игнорируется post-trained моделями, принимается для `-base` |
| `duration` | float | длина результата, с (для `inpaint` — полная длина, включая продолжение) |
| `steps` | int | 8 по умолчанию |
| `cfg_scale` | float | 1.0 |
| `seed` | int | −1 = случайный; в ответе возвращается фактический |
| `batch_size` | int 1–4 | число вариантов |
| `init_noise_level` | float 0–1 | только `a2a` |
| `mask_start`, `mask_end` | float, повторяемые | только `inpaint`, секунды от начала `audio` |
| `audio` | file | контекст для `a2a`/`inpaint` (wav/flac/mp3, перекодируем через soundfile; mp3 — через ffmpeg, как в `routes_yue2_upload.py`) |
| `chunked_decode` | bool | по умолчанию выключен на ≥ 12 ГБ VRAM |

Статусы задачи: `queued` → `running` (`stage`: `loading_model` \| `encoding` \| `sampling` \| `decoding`, `progress` 0–100 по шагам семплера) → `done` \| `failed` \| `cancelled`. Отмена: кооперативная флагом между шагами семплера (8 шагов за полсекунды, так что фактически мгновенная) и жёсткая для задач в очереди.

Выход: `files` — список `/v1/files/<job>_<i>.wav`, стерео 44.1 кГц float → int16 с пиковым ограничением −0.5 дБ (без нормализации громкости, чтобы не ломать швы repaint).

### 3.5 Семантика результата по режимам

| `task` | Вход | Выход |
|---|---|---|
| `text` | — | `duration` секунд |
| `a2a` | `audio` длиной L | ровно L секунд (обрезаем хвост `duration_padding_sec`) |
| `inpaint` | `audio` длиной L, маски, `duration` D ≥ L | D секунд: участки вне масок равны входу, маски и продолжение (L..D) сгенерированы |

Это ровно то, на что рассчитан `variantClip()` в `AiPartPanel.vue`: repaint/continue кладутся от `ctxStart`, cover от `regionStart`.

## 4. Регистрация движка в бэкенде

Правки по отчёту о двухдвижковых допущениях:

- `config.py`: `STABLE_AUDIO_*` переменные, `MODELS["stable_audio"] = ModelDefinition(id="stable_audio", label="Stable Audio 3", proxy_prefix="sa3", proxy_target="http://127.0.0.1:8002", processes=[ProcessSpec(name="stable_audio_api", cwd=STABLE_AUDIO_DIR, cmd=[UV_BIN, "run", "sa3-server", ...], extra_path_dirs=[FFMPEG_BIN_DIR], env={...}, health_url=".../health", startup_timeout=120)])`.
- `ALLOW_CONCURRENT_MODELS`: обобщить до «все устройства заданы и попарно различны» (три переменные вместо двух). Семантика не меняется.
- `routes_orchestrator.py`: гейт `if req.model == "stable_audio" and not features.has_stable_audio(): 409`.
- `features.py`: `has_stable_audio()` = есть `STABLE_AUDIO_DIR/.venv` **и** в кэше HF есть хотя бы один снапшот `models--stabilityai--stable-audio-3-*` с `model.safetensors`. В `snapshot()` ключи `stable_audio` и `stable_audio_models: ["medium", "small-sfx"]`.
- `tagging.py`: `AI_MODELS` += `stable_audio`; примечание о лицензии (Community License) в теге по образцу YuE2.
- `routes_tracks.py`, `db.py`, `routes_proxy.py`, `sysinfo.py`: без правок, всё по `MODELS`.

## 5. Фронтенд: движок в оболочке

Минимум, без которого движок нельзя включить из UI:

- `types.ts`: `ModelId = 'ace_step' | 'yue2' | 'stable_audio'`.
- `useModelSwitch.ts`: `MODEL_ROUTES.stable_audio = 'stable-audio'`, `MODEL_LABELS`, и проверка установленности через карту `MODEL_FEATURE: Record<ModelId, FeatureId | null>` вместо `if (id === 'yue2')`.
- `AppHeader.vue`: третья вкладка. Предлагаю переписать вкладки движков на `v-for` по `ENGINES = [{id, icon, descKey}]` вместо третьего скопированного блока; LoRA остаётся отдельной вкладкой после ACE-Step. Строка `header.engineStart` «(другая модель остановится)» → «(запущенная модель остановится)».
- `HomeView.vue`: `MODEL_IDS` += `stable_audio`, сетка `sm:grid-cols-2 lg:grid-cols-3`, `home.descStableAudio`.
- `features.ts`: `FeatureId` += `stableAudio`, явная ветка в `has()` (сейчас цепочка тернарников проваливается в `ace_base`).
- `system.ts`/`ResourceMeters.vue`: `MemoryHolder` += `stable_audio`, цвет в `HOLDER_COLORS`, подпись `resources.holder.stable_audio`.
- `LibraryPicker.vue`: фильтр `stable_audio`, подписи `library.filters/origin`.
- `AppHelpModal.vue`: таблица сравнения `Row{ace, yue}` → `Row{ace, yue, sa3}` (одна колонка «Stable Audio 3»); раздел `header.helpSections.stableAudio`.
- `router.ts`: `/stable-audio` → `views/stable-audio/StableAudioPage.vue`.

### 5.1 Страница `Stable Audio 3`

Шапка переключает движки, поэтому у движка должна быть страница. Делаем по образцу YuE2Page (`NotInstalled` / `ModelOfflineBanner` / форма + лента треков), но форма простая:

```
┌ Создать звук ────────────────────────────────┐  Ваши треки (лента, фильтр model = stable_audio)
│ [ Музыка ] [ Сэмплы и SFX ]                  │
│ Модель: ( medium ▾ )     ← small-sfx в SFX   │
│ Описание  [....................................] │
│   подсказка: английский, жанр, инструменты, BPM │
│ Длительность  ──●────── 0:30   (SFX: 0.5–10 с) │
│ Вариантов  (1) (2) (4)      Seed [-1] [🎲]      │
│ ▸ Дополнительно: шаги 8, cfg 1.0, negative     │
│            [ ✦ Сгенерировать ]                 │
└───────────────────────────────────────────────┘
```

Результат: `saveTrack({model: 'stable_audio', title: первые 60 символов промпта, params: {task:'text', model, prompt, duration, steps, cfg, seed}})`, как делает `stores/yue2.ts`. Карточки треков переиспользуют компоненты ACE-ленты (play, скачать, в редактор, удалить).

## 6. Аранжировщик: второй движок для Repaint / Continue / Cover

### 6.1 Что видит пользователь

Один новый элемент управления: селект **«Модель»** в нижнем ряду формы (сейчас там `base`/`turbo`) превращается в селект **«Движок · модель»** с группами:

```
Модель  ( ACE-Step · turbo        ▾ )
          ACE-Step · turbo
          ACE-Step · base
          Stable Audio 3 · medium
```

Почему не отдельный переключатель движка в верхнем ряду: верхний ряд уже плотный (заголовок, 4 режима, подсказка, варианты, кнопка, закрыть), а в узком правом доке режимы и так переносятся 2×2. Модель и движок — одно решение «кем генерировать», ему место в одном селекте.

Логика:

- Список групп зависит от режима: для **Lego** только ACE-Step (SA3 не умеет партию поверх микса); для Repaint/Continue/Cover обе группы. Движок без установленных весов показывается серым с подписью «не установлен».
- Выбор запоминается **на режим** в `localStorage` (`remiqora_arranger_models`), чтобы repaint мог по умолчанию идти в SA3, а lego в ACE base. Значение по умолчанию: ACE turbo (текущее поведение); после первой удачной SA3-генерации ничего не меняем, выбор пользователя.
- Если выбранный движок не запущен, блок под верхним рядом показывает уже существующий offline-паттерн с кнопкой **«Запустить Stable Audio 3»** (`orchestrator.switchModel('stable_audio')`); подпись предупреждает, что ACE-Step остановится. Lego при активном SA3 показывает «Запустить ACE-Step».
- Для SA3 скрываются: текст и язык вокала (`showLyrics = engine === 'ace'`), заметка про lego base. Остаются: описание, «модель слышит», «где», ползунок близости (cover), тональность, темп, варианты.
- Подсказки режимов (`modeHints`) получают вариант для SA3: «Stable Audio дорисует участок по контексту слева и справа», «…продолжит трек от этой точки».

### 6.2 Логика запроса

В `utils/aiParts.ts`:

```ts
export const AI_ENGINES = ['ace', 'sa3'] as const
export type AiEngine = (typeof AI_ENGINES)[number]
export const ENGINE_MODES: Record<AiEngine, readonly AiMode[]> = { ace: AI_MODES, sa3: ['repaint', 'continue', 'cover'] }
export const ENGINE_MAX_CONTEXT_SEC: Record<AiEngine, number> = { ace: 600, sa3: 380 }
export const ENGINE_MODEL_ID: Record<AiEngine, ModelId> = { ace: 'ace_step', sa3: 'stable_audio' }
```

`AiPartRequest` получает `engine: AiEngine`; `model` хранит имя чекпойнта внутри движка (`medium`). `spans()` и `generate()` берут лимит контекста из `ENGINE_MAX_CONTEXT_SEC[engine]` (для SA3 continue c `CONTINUE_CTX = 240` + 16 тактов при 120 BPM = 272 с, укладывается; при длинных продолжениях `ctxLen` уменьшается той же формулой).

Сборка запроса для SA3 (`stores/aiParts.ts`, `buildSa3Request`):

| Режим | `task` | Поля |
|---|---|---|
| repaint | `inpaint` | `audio = context.wav`, `mask_start = regionStart − ctxStart`, `mask_end = regionEnd − ctxStart`, `duration = ctxEnd − ctxStart` |
| continue | `inpaint` | `audio = context.wav` (длина `ctxEnd − ctxStart`), `mask_start = mask_end = длина контекста`, `duration = regionEnd − ctxStart` |
| cover | `a2a` | `audio = context.wav`, `init_noise_level = coverStrength`, `duration = regionEnd − regionStart` |

Общее: `prompt = "TrackType: Music, VocalType: Instrumental. " + caption + (key ? ", in " + key : "") + ", " + bpm + " BPM"`, `steps = 8`, `cfg_scale = 1`, `seed = −1`, `batch_size = count`, `model = models[mode]`.

Шкала ползунка Cover: у ACE-Step `audio_cover_strength` 0 = далеко, 1 = близко; у SA3 `init_noise_level` 1 = полностью новое. Передаём `init_noise_level = 1 − coverStrength`, чтобы подпись «ближе к оригиналу» означала одно и то же.

### 6.3 Опрос и результаты

`_poll()` в `stores/aiParts.ts` группирует ожидающие задачи по движку и делает один `query` на движок за тик (2 с). Ответ SA3 маппится 1:1 на `AiPartStatus`; `progress` берётся из ответа; `files` превращаются в `'/api/sa3' + file` (вместо жёсткого `'/api/ace' + p.file`). `cancel()` ветвится по движку. `_persist()` не меняется (сохраняем как `model: 'editor'`, `params.ai_part = true`, плюс `params.engine`).

`insertVariants()`, `holdRange`, `variantClip`, швы — без изменений благодаря п. 3.5.

### 6.4 Известная проблема уровня громкости (оба движка)

`renderContext()` нормализует контекст к пику 0.9, а результат кладётся рядом с оригиналом без обратной компенсации; при тихом оригинале шов repaint слышен скачком громкости. Это существующее поведение ACE-пути. Предложение (отдельный коммит): `renderContext` возвращает применённый коэффициент, `_persist`/`variantClip` масштабируют вариант на обратный через `gain` клипа. Для SA3 это важнее, потому что участки вне маски возвращаются «как есть», и разница становится заметнее.

## 7. Панель «Сэмплы» в редакторе (SFX)

### 7.1 Что это

Третья докуемая панель рядом с AI-аранжировщиком и микшером, кнопка в тулбаре **«Сэмплы»** (иконка волны). Назначение: сгенерировать удар, уход, райзер, фоли, атмосферу или луп и положить его на таймлайн, не выходя из проекта.

```
┌ ≡ Сэмплы ?                            [ ✦ Сгенерировать ]  ✕ ┐
│ [ One-shot ] [ Луп ] [ Текстура ]     Вариантов (1)(2)(4)      │
│ Описание  [ punchy 808 kick, short decay, slight saturation ]  │
│ Длина  One-shot: ──●── 2.0 с │ Луп: (1)(2)(4)(8) тактов │ Текстура: 10–30 с │
│ Модель ( small-sfx ▾ )   Куда: (● новая дорожка) (○ выбранная, от курсора) │
├────────────────────────────────────────────────────────────────┤
│ ▌kick A ▐▌▁▃▅▂▁ 2.0 с  [▶] [＋ На дорожку] [↓]   ▌kick B …     │  ← лента результатов, горизонтальный скролл
└────────────────────────────────────────────────────────────────┘
```

### 7.2 Логика

- Требует запущенного `stable_audio`; иначе тот же offline-блок с кнопкой запуска, что в аранжировщике.
- Модель по умолчанию `small-sfx` (2.3 ГБ, быстрая); `medium` в списке, если установлена, для «музыкальных» сэмплов.
- Промпт: One-shot/Текстура → `"TrackType: SFX. " + описание`; Луп → `"TrackType: Instrument, " + описание + ", " + bpm + " BPM, seamless loop"`. Длина лупа = `bars × 4 × 60 / bpm` (размер 4/4 как в аранжировщике, `time_signature: '4'`).
- Задачи живут в `stores/sfx.ts` (копия `submit/_poll/_persist` из `aiParts.ts` с движком `sa3` и `task: 'text'`), переживают скрытие панели, привязаны к `store.session`.
- Результаты **не вставляются автоматически**, в отличие от аранжировщика: сначала прослушивание в ленте результатов (`decodeStem` + общий `AudioContext`), потом кнопка «На дорожку». Причина: SFX коротки, вариантов много, автоматическая вставка четырёх дорожек по 2 секунды засоряет проект.
- Вставка: `store.insertLanes([{name: title, colorId: 'slate', clips: [clip]}])` (один шаг undo) либо `store.addClip(selectedLaneId, clip)`; `timelineStart = loopRegion.enabled ? loop.start : playheadSec`; `originalBpm = bpm генерации` (для лупов W-стретч работает), `warpEnabled` выключен; фейды 5 мс для one-shot.
- Сохранение в библиотеку: `saveTrack({model: 'editor', params: {sfx: true, kind, prompt, engine: 'sa3', bpm}})`; в `LibraryPicker` фильтр **«Сэмплы»** (`isSfx = params.sfx`), исключаются из «Все» так же, как AI-варианты. Невостребованные результаты чистятся при сохранении проекта по образцу `purgeDiscarded` (трек не на таймлайне и не помечен «оставить»).
- Док: `DockPanel = 'ai' | 'mixer' | 'sfx'`, `DEFAULTS.sfx = 'bottom'`, строка в `loadDocks()`, `rightDockUsed`, Teleport по образцу AI-панели, `editor.dock.moveSfx`.

### 7.3 Ограничения, о которых честно пишем в подсказке

- Луп не гарантированно бесшовный: модель не обучена на loop-points. Обрезаем ровно по тактам и ставим фейды 5 мс; для «музыкальных» лупов рекомендуем генерировать 2–4 такта и проверять на кольце.
- One-shot может прийти с тишиной в начале: сервер делает `trim_leading_silence` (порог −60 дБ) для `task: 'text'` с длиной ≤ 5 с.
- Веса `small-sfx` — отдельный gated-репозиторий, нужно принять условия и скачать.

## 8. Установка, веса, лицензия

- `setup_models.ps1/.sh/setup_linux.sh`: шаг «Stable Audio 3» = `uv sync` в `external/sa3-server` (копия в `$STABLE_AUDIO_DIR`, как Demucs), запись `STABLE_AUDIO_DIR` в `.env`. Флаг `-SkipStableAudio`.
- Веса не качаются скриптом автоматически (gated). Сценарий: пользователь принимает условия на трёх страницах `stabilityai/stable-audio-3-{medium,small-music,small-sfx}`, выполняет `uvx --from huggingface_hub hf auth login`, затем в приложении компонент `NotInstalled` для `stableAudio` показывает кнопку «Скачать medium (10.5 ГБ)» / «small-sfx (3.5 ГБ)». Скачивание делает **сервер** (`POST /v1/models/download {model}` → `huggingface_hub.snapshot_download` с токеном из кэша, прогресс в `GET /v1/models`), по образцу кнопки «Download Prompt Assistant». Если токена нет, сервер отвечает 401 с текстом инструкции, фронтенд показывает ссылки.
- Desktop: компонент `stable-audio` в `components.js` (uv sync сервера, без весов), фича `stableAudio` в `features.js`, `main.js`, `paths.js` (`engines/StableAudio`), `server.js` (`STABLE_AUDIO_DIR`), `manifest.json`, `renderer/app.js` + `i18n.js`, тест `features.test.js`.
- README/README.ru: разделы «What's inside», «AI arranger», «Built with» (Stability AI Community License + Gemma Terms, ссылка на условия), «Installation», «Known limitations» (gated weights, instrumental only, 380 с).

### 8.1 Как сделано в фазе 4 (отступления от плана выше)

- Качает не GPU-движок, а бэкенд: `backend/app/sa3_weights.py` запускает `python -m sa3_server.download <model> --json` из окружения sa3-server фоновым процессом и читает из него события JSON. Причина: для скачивания через сервер пришлось бы запускать Stable Audio 3, то есть выгружать работающий движок. API: `GET /api/sa3-weights`, `POST /api/sa3-weights/{model}/download`, `POST /api/sa3-weights/{model}/cancel`, `POST /api/sa3-weights/token`. Одно скачивание за раз.
- Токен вводится в приложении (`--login` проверяет его через `whoami` и сохраняет в `HF_HOME/token`), так что консоль не нужна вообще, в том числе для `hf auth login`. Без токена или с неверным токеном загрузчик отвечает кодом `login`, без принятой лицензии кодом `access`; страница показывает, что сделать.
- Компонент `Sa3Weights.vue` стоит на странице Stable Audio 3: вместо страницы, пока не скачано ни одной модели, и в раскрывающемся блоке «Модели» после. Стор `sa3Weights` следит за скачиванием на любой странице и обновляет `features`, когда модель появилась. Панель «Сэмплы» без моделей ведёт на эту страницу.
- Модель считается скачанной, когда в снапшоте есть и `model.safetensors`, и текстовый энкодер `t5gemma-b-b-ul2/model.safetensors` (каждый репозиторий несёт свою копию). Не качаются картинка карточки и `svd_bases.pt` base-репозиториев (нужен только обучению LoRA).
- huggingface_hub 2.x не докачивает файл с середины: каждый процесс пишет во временный файл с уникальным именем. Поэтому остановка сохраняет готовые файлы, а недокачанный начинается заново; его временный файл удаляется сразу после остановки и при следующем запуске.
- Base-чекпойнты открыты (не gated), основные три закрыты с автоматическим одобрением.
- setup-скрипты качают веса только по явной просьбе: `-StableAudioModels` (ps1), `--stable-audio-models=` (macOS), `STABLE_AUDIO_MODELS` (Linux).
- Desktop: фича `stableAudio` (по умолчанию выключена), компонент `stable-audio` копирует исходники сервера из ресурсов приложения в `engines/StableAudio` и делает `uv sync`; версия компонента = хеш исходников. Зависимость `stable-audio-3` взята архивом коммита вместо `git+https`, потому что на машинах пользователей десктопа обычно нет git.
- На Mac (MPS) и на CPU `medium` не предлагается и не прогревается: ему нужны CUDA и Flash Attention.

## 9. Фазы

| Фаза | Содержимое | Результат |
|---|---|---|
| **1. Движок** | `external/sa3-server`, `MODELS`, features, header/home/types/meters/library, страница `Stable Audio 3` с текстовой генерацией и лентой | движок переключается из шапки, генерирует треки в библиотеку |
| **2. Аранжировщик** | селект «движок · модель», `engine` в запросе и сторе, маппинг repaint/continue/cover, offline-блок, подсказки, гайд | repaint/continue/cover через SA3 ложатся на дорожки без правок геометрии |
| **3. Сэмплы** | `SfxPanel.vue`, `stores/sfx.ts`, док, фильтр библиотеки, тулбар, help | one-shot/луп/текстура из панели на таймлайн |
| **4. Распространение** | скачивание весов из приложения, setup-скрипты, desktop, README | установка без консоли, кроме `hf auth login` |
| Позже | совместное проживание с ACE-Step turbo по бюджету VRAM; `small-sfx` на CPU параллельно с GPU-движком; LoRA для SA3 | — |

Фазы 1 и 2 — один PR (≈ 1.5–2 дня), 3 — второй, 4 — третий. Каждая фаза проверяется в `dev.bat`: переключение из шапки, генерация, вставка в проект, undo, сохранение проекта, перезапуск.

## 10. Открытые вопросы

1. Префикс прокси: `sa3` (коротко) или `stable` (читаемо)? В документе `sa3`.
2. Значение по умолчанию для repaint/continue после установки SA3: оставить ACE turbo или сразу SA3? В документе — ACE, выбор запоминается.
3. Нужна ли странице `Stable Audio 3` вкладка «Сэмплы и SFX», если панель в редакторе уже умеет то же? Предлагаю оставить: страница нужна для библиотеки вне проекта.
4. Хранить результаты аранжировщика/сэмплов как `model: 'editor'` (как сейчас) или как `stable_audio`? Предлагаю `editor` + `params.engine`, чтобы фильтры библиотеки не зависели от движка.
