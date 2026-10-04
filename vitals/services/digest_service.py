"""Period AI digest service (module 10) — the product core.

For each report we assemble a versioned, module-aware **structured cross-domain
snapshot** with one authoritative date window and ask the LLM for an *analytical
narrative* — the interpretation of how the domains relate, not a restatement of
the numbers. The structured context is stored alongside the text so it can be
re-inspected or re-run later.

The LLM client is injected so the generator is unit-tested without network or a
key; the scheduled job no-ops when no key is configured.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vitals.enums import DigestKind, Source
from vitals.integrations.llm_client import LLMEmptyResponse
from vitals.models.milestones import DOMAIN, WeeklyDigest
from vitals.utils.timeutils import today_local

logger = logging.getLogger(__name__)

# Output budget for one narrative. Was 6000 and prod hit it: a reasoning model
# (claude-opus-5) spends part of the same budget on thinking tokens, so the
# visible digest got cut mid-sentence. Russian is ~2 chars/token, and a full
# cross-domain digest runs 8-10k chars, so leave headroom for both.
_DIGEST_MAX_TOKENS = 16000

# Row budget per day of window for the signals block. The service's own default
# (200) is a screen's worth; a 90-day window quietly lost everything older than
# the 200th newest row while the block still read as the whole period.
# ponytail: a budget, not "all rows" — raise it if a day ever produces more.
_SIGNALS_PER_DAY = 50
_BODY_MEASUREMENT_LIMIT = 6
_BODY_SCAN_LIMIT = 3
_GARMIN_ACTIVITY_LIMIT = 500
_HEVY_SESSION_LIMIT = 300
_TREATMENT_EVENT_LIMIT = 500
_SKINCARE_EVENT_LIMIT = 500
_LAB_HISTORY_PER_MARKER = 3
_GENETICS_LIMIT = 200
_TIMELINE_LIMIT = 200

_REPORT_BODY_METRIC_KEYS = frozenset(
    {
        "weight",
        "skeletal_muscle_mass",
        "body_fat_mass",
        "body_fat_pct",
        "lean_body_mass",
        "fat_free_mass",
        "protein",
        "minerals",
        "total_body_water",
        "intracellular_water",
        "extracellular_water",
        "ecw_tbw_ratio",
        "visceral_fat_area",
        "visceral_fat_level",
        "phase_angle",
        "inbody_score",
        "bmr",
        "waist_hip_ratio",
        "segmental_lean",
        "segmental_fat",
    }
)

_DOMAIN_MODULE = {
    "weight": "weight",
    "body_comp": "body_comp",
    "glp1": "glp1",
    "supplements": "supplements",
    "genetics": "genetics",
    "skincare": "skincare",
    "workouts": "hevy",
    "garmin": "garmin",
    "labs": "labs",
    "nutrition": "nutrition",
    "hrt": "hrt",
    "timeline": "timeline",
    "signals": "signals",
    "environment": "environment",
    "milestones": "reports",
    "system": "reports",
}

CONTEXT_SCHEMA_VERSION = 2
REPORT_MODE_CLOSED = "closed_period"
REPORT_MODE_BRIEF = "daily_brief"
MIN_PERIOD_DAYS = 1
MAX_PERIOD_DAYS = 90


@dataclass(frozen=True)
class ReportWindow:
    """One authoritative set of date boundaries for every context query."""

    report_date: date_type
    period_start: date_type
    period_end: date_type
    previous_start: date_type
    previous_end: date_type
    period_days: int
    mode: str


def report_window(
    *,
    on_date: Optional[date_type] = None,
    period_days: int = 7,
    mode: str = REPORT_MODE_CLOSED,
    max_period_days: int = MAX_PERIOD_DAYS,
) -> ReportWindow:
    """Validate and resolve the report window without touching the database.

    A period report contains completed days. A daily brief is the one explicit
    exception: it is a current-day snapshot, and its caller opts into that mode
    instead of overloading ``period_days == 1`` with two meanings.
    """
    if isinstance(period_days, bool) or not isinstance(period_days, int):
        raise ValueError("period_days must be an integer")
    if not MIN_PERIOD_DAYS <= period_days <= max_period_days:
        raise ValueError(
            f"period_days must be between {MIN_PERIOD_DAYS} and {max_period_days}"
        )
    if mode not in {REPORT_MODE_CLOSED, REPORT_MODE_BRIEF}:
        raise ValueError(f"unsupported report mode: {mode}")
    if mode == REPORT_MODE_BRIEF and period_days != 1:
        raise ValueError("daily_brief mode requires period_days=1")

    local_today = today_local()
    report_date = on_date or local_today
    if report_date > local_today:
        raise ValueError("on_date cannot be in the future")

    period_end = report_date
    if mode == REPORT_MODE_CLOSED and report_date == local_today:
        period_end -= timedelta(days=1)
    period_start = period_end - timedelta(days=period_days - 1)
    previous_end = period_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    return ReportWindow(
        report_date=report_date,
        period_start=period_start,
        period_end=period_end,
        previous_start=previous_start,
        previous_end=previous_end,
        period_days=period_days,
        mode=mode,
    )


def _period_name(on_date: date_type, window: ReportWindow) -> Optional[str]:
    if window.period_start <= on_date <= window.period_end:
        return "current"
    if window.previous_start <= on_date <= window.previous_end:
        return "previous"
    return None


def _coverage(
    *,
    module: str,
    enabled: bool,
    dates: Sequence[date_type] = (),
    window: ReportWindow,
    rows: Optional[int] = None,
    truncated: bool = False,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Describe what a block could see, so absence is not guessed from null."""
    dated = list(dates)
    current_rows = sum(
        1 for value in dated if window.period_start <= value <= window.period_end
    )
    previous_rows = sum(
        1 for value in dated if window.previous_start <= value <= window.previous_end
    )
    total_rows = len(dated) if rows is None else rows
    latest_date = max(dated) if dated else None
    out: dict[str, Any] = {
        "module": module,
        "enabled": enabled,
        "status": "disabled" if not enabled else ("available" if total_rows else "empty"),
        "rows": total_rows,
        "current_rows": current_rows,
        "previous_rows": previous_rows,
        "first_date": min(dated).isoformat() if dated else None,
        "last_date": latest_date.isoformat() if latest_date else None,
        "freshness_days": (
            (window.period_end - latest_date).days if latest_date else None
        ),
        "truncated": bool(truncated),
    }
    if extra:
        out.update(extra)
    return out


def _resolved_day_context(row) -> dict[str, Any]:
    planned = dict(row.planned or {})
    answers = dict(row.answers or {})
    resolved = {**planned, **answers}
    return {
        "date": row.date.isoformat(),
        "answers": answers,
        "planned": planned,
        "resolved": resolved,
        "answered_keys": sorted(answers),
        "source": row.source,
        "source_by_field": {
            key: (row.source if key in answers else "template") for key in resolved
        },
    }


async def _bounded_scalars(
    session: AsyncSession, stmt, limit: int
) -> tuple[list[Any], bool]:
    """Execute ``limit + 1`` so every output cap is observable in coverage."""
    rows = list((await session.execute(stmt.limit(limit + 1))).scalars().all())
    return rows[:limit], len(rows) > limit


_GARMIN_DAILY_FIELDS = (
    "sleep_seconds",
    "sleep_score",
    "deep_sleep_seconds",
    "light_sleep_seconds",
    "rem_sleep_seconds",
    "awake_seconds",
    "awake_count",
    "restless_moments",
    "avg_sleep_stress",
    "avg_sleep_hr",
    "spo2_lowest",
    "respiration_lowest",
    "respiration_highest",
    "body_battery_change",
    "breathing_disruption",
    "sleep_need_actual",
    "resting_hr",
    "avg_hr",
    "max_hr",
    "min_hr",
    "hrv_avg",
    "hrv_status",
    "avg_respiration",
    "spo2_avg",
    "avg_stress",
    "max_stress",
    "body_battery_high",
    "body_battery_low",
    "steps",
    "floors_climbed",
    "active_calories",
    "bmr_calories",
    "total_calories",
    "intensity_minutes_moderate",
    "intensity_minutes_vigorous",
    "training_readiness",
    "vo2max",
    "training_status",
    "acute_load",
    "load_ratio",
)


def _garmin_daily_row(row) -> dict[str, Any]:
    out = {"date": row.date.isoformat(), "source": row.source}
    out.update({key: getattr(row, key) for key in _GARMIN_DAILY_FIELDS})
    out["sleep_start"] = row.sleep_start.isoformat() if row.sleep_start else None
    out["sleep_end"] = row.sleep_end.isoformat() if row.sleep_end else None
    out["sleep_hours"] = (
        round(row.sleep_seconds / 3600, 2) if row.sleep_seconds is not None else None
    )
    return out


def _garmin_activity_row(row) -> dict[str, Any]:
    return {
        "date": row.date.isoformat(),
        "external_id": row.external_id,
        "activity_type": row.activity_type,
        "name": row.name,
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "duration_min": (
            round(row.duration_seconds / 60, 1)
            if row.duration_seconds is not None
            else None
        ),
        "distance_km": (
            round(row.distance_m / 1000, 3) if row.distance_m is not None else None
        ),
        "calories": row.calories,
        "avg_hr": row.avg_hr,
        "max_hr": row.max_hr,
        "elevation_gain_m": row.elevation_gain_m,
        "avg_power": row.avg_power,
        "training_effect_aerobic": row.training_effect_aerobic,
        "training_effect_anaerobic": row.training_effect_anaerobic,
        "hr_zone_seconds": row.hr_zone_seconds,
        "source": row.source,
    }


_SKINCARE_FLAGS = (
    "retinoid",
    "azelaic",
    "peel",
    "niacinamide_spf",
    "moisturizer",
    "vitamin_c",
    "benzoyl_peroxide",
)


def _skincare_log_row(row, window: ReportWindow) -> dict[str, Any]:
    return {
        "date": row.date.isoformat(),
        "period": _period_name(row.date, window),
        "applied": [key for key in _SKINCARE_FLAGS if getattr(row, key)],
        "note": row.note,
        "source": row.source,
    }


_NUTRITION_FIELDS = (
    ("calories", "calories"),
    ("protein_g", "protein_g"),
    ("fat_g", "fat_g"),
    ("carbs_g", "carbs_g"),
)


def _nutrition_day_totals(meals: Sequence[Any]) -> dict[str, Optional[float]]:
    """Sum only recorded nutrients; an unfilled macro is not a measured zero."""
    out: dict[str, Optional[float]] = {}
    for key, attr in _NUTRITION_FIELDS:
        values = [getattr(meal, attr) for meal in meals if getattr(meal, attr) is not None]
        out[key] = round(sum(values), 1) if values else None
    return out

DIGEST_SYSTEM = """\
Ты пишешь периодический разбор для пользователя дашборда здоровья Vitals.

Пользователь — молодой парень, который разбирается в теме (рекомпозиция, GLP-1, силовые, Garmin). Ему не нужны объяснения базовых понятий. Ему нужен взгляд сверху: что реально происходит, куда всё идёт, и на что обратить внимание.

РОЛЬ: ты — напарник, который шарит. Не врач, не коуч, не ментор. Говоришь прямо, без воды, без паники, без покровительственного тона. Если данных мало — так и скажи, без натягивания выводов.

ВХОДНЫЕ ДАННЫЕ (JSON):
Контекст имеет schema_version=2. Любой домен может быть null, но null сам по себе НЕ означает «пользователь не ведёт данные»: сначала читай coverage.
- report_meta: report_date, mode, period_start / period_end, previous_start / previous_end и period_days. closed_period состоит из ПОЛНОСТЬЮ ЗАКРЫТЫХ дней и заканчивается вчера, если отчёт сделан сегодня; daily_brief — отдельный текущий день. Период называй по period_start–period_end.
- coverage: по каждому домену enabled/status, число строк текущего и прошлого окон, first_date/last_date, freshness_days (возраст последней записи относительно period_end) и truncated. Говорить «данных нет» можно только если модуль enabled, status=empty и truncated=false. disabled — сознательно отключено; truncated — данных может быть больше. metric_samples и period_stats.sample_counts — реальные знаменатели отдельных показателей.
- days: ТАБЛИЦА ПО ДНЯМ — одна строка на каждый день периода, где домены УЖЕ СВЕДЕНЫ: полный компактный Garmin daily, вес и замеры, все макросы, отдельные массивы garmin_activities и hevy_workouts, GLP-1/ГЗТ события, уход, resolved day context и signals. Отсутствующий ключ = данных за день нет. Legacy workout — только одна Hevy-сессия для совместимости; для анализа используй массив hevy_workouts.
  ЭТО ГЛАВНЫЙ ИНСТРУМЕНТ ДЛЯ СВЯЗЕЙ. Читай таблицу по столбцам и ищи совпадения со сдвигом: тренировка → сон и HRV следующей ночи; exposure вечером → метрика наутро; тяжёлый день или офис → восстановление; дни с низкими калориями → шаги, стресс, вес через 2-3 дня. Называй связь С ДАТАМИ («после сессии 28-го HRV просел на две ночи») — без дат это не наблюдение, а общая фраза. Если совпадение однократное — так и скажи, что это одно совпадение, а не закономерность.
- user_profile: возраст, рост, программа, цели
- weight: последний замер as-of period_end, MA7 и тренд, noise_markers, последние антропометрические measurements и measurement_delta
  ВАЖНО: если активен noise_marker, то ma7_date — это последний чистый день ДО начала шума, а не сегодня. Не сравнивай latest_kg и ma7_kg как если бы они были одновременными. Разрыв между ними объясняется давностью MA, а не текущим шумом.
- glp1: активная фаза as-of period_end, plateau, пересекающие два окна phases, injections и side_effects с period=current/previous
- body_comp: последний BIA/InBody-скан плюс scans и deltas_from_previous_scan. Это отдельный источник состава тела (BIA); сосуществует с Navy в weight — не смешивай их.
- garmin: ПОСЛЕДНИЙ день as-of period_end со всеми компактными daily-полями и activities за текущее/прошлое окна (без intraday/splits). Для аэробной нагрузки смотри duration/distance/training effect и HR zones.
  ВАЖНО: это один день. Разброс, тренд и «нормально/ненормально» читай по таблице days и по period_stats, а не по нему. total_days_logged — сколько дней Garmin лежит в базе ЗА ВСЮ ИСТОРИЮ, а не длина этого отчёта: он говорит только о том, есть ли вообще история. Никогда не называй его размером выборки отчёта («N дней истории, цифрам можно верить»).
- hevy: total_workouts — тренировок ВНУТРИ периода; last_workout — дата последней; mean_gap_days — средний интервал между сессиями; sessions — сессии за период И за столько же дней до него (in_period=false — сессия до начала среза). У каждой: volume_kg (тоннаж рабочих подходов), working_sets, duration_min, exercises.
  ВАЖНО: ритм тренировок — это mean_gap_days и интервалы между датами в sessions, а не total_workouts. Счётчик зависит от того, в какой день сделан отчёт: две сессии с разрывом в 5-7 дней попадают то в один срез, то в разные. Поэтому total_workouts как показатель режима просто не используй.
  ТО ЖЕ САМОЕ КАСАЕТСЯ ОБЪЁМА. Сравнивай volume_per_session_kg — тоннаж ОДНОЙ сессии. Сумма за период (training_volume_kg) двигается вместе со счётчиком сессий: одна тренировка против двух даёт «−51% объёма», хотя сессии были одинаковые. Никогда не выноси дельту суммы в вывод и не называй её падением объёма; если сессий в окнах разное количество, разница суммы — это разница в количестве сессий, и она не стоит отдельной фразы.
  Молча. Не объясняй читателю, как устроено окно, не пиши «формально столько, но фактически иначе», не сообщай, что счётчик вводит в заблуждение. Он не просил разбор методики — он просил разбор своего состояния. Сразу говори по факту: «ходишь раз в 3-4 дня, объём сессии держится» — и дальше.
- training: Garmin и Hevy намеренно разделены по источникам. Они могут описывать одну сессию; не складывай их в число уникальных тренировок без совпадения времени/типа.
- labs: results_in_period содержит ВСЕ результаты периода, out_of_range — только свежие последние отклонения, trends — последние 3 точки, retest — только сохранённый интервал/срок пересдачи. Никогда не придумывай срок пересдачи, если retest_interval_days отсутствует.
- period_stats: {current, previous} — симметричные средние восстановления, активности, веса, Hevy/Garmin и всех макросов. ЭТО ГЛАВНЫЙ БЛОК для изменений. У каждого среднего есть знаменатель в sample_counts.
  ЗНАМЕНАТЕЛИ, прежде чем делать вывод о пропусках: days — длина окна (все дни закрытые), garmin_days / nutrition_days_logged — на скольких из них реально стоят цифры. Разница, построенная на двух днях против семи, — это разница в покрытии данных, а не в организме, и назвать её надо именно так. Про покрытие пиши, только если оно реально мешает выводу: «данные есть за все дни» — не наблюдение, а отчёт о самом себе.
- nutrition: средние калории/белок/жиры/углеводы, покрытие и поздние приёмы пищи
- hrt: cycle.items и schedule — назначенный протокол, planned_administrations — план, doses — факт текущего окна, comparison_doses — факт прошлого; side_effects тоже разделены. Связывай вмешательство со сном/HRV, анализами, кожей и настроением, но не давай назначения доз.
- supplements: текущий справочник, а не дневной adherence-log; skincare: продукты, реальные daily logs и observations; genetics: только курированные impact/interpretation/action_notes; alerts: активные предупреждения as-of среза.
- timeline: ручные события и только не дублирующие доменные блоки derived lifecycle events. certainty=audit_timestamp означает приблизительную дату изменения справочника.
- signals: что пользователь сам сказал о своём состоянии, в хронологическом порядке. kind=state (есть всегда, value_num 1-5: «энергии ноль»), symptom (случилось, value_num 1-5: «голова раскалывается»), exposure (сделал/принял, at_time — время суток: «кофе в 22»). note — исходная формулировка. Единственный блок, который объясняет ПОЧЕМУ цифры такие: ищи связи «exposure вечером → метрика Garmin наутро» и «симптом держится N дней подряд → что ещё в эти дни». Это его слова, а не измерение — не считай их точными числами и не строй на одной записи вывод.
- day_context: planned — догадка шаблона, answers — ручные переопределения, resolved — их итог; source_by_field показывает силу каждого поля. Вывод на одном template-поле не строй.
- milestones: активные цели с прогрессом и дедлайнами

ИНВАРИАНТЫ (нарушение = баг):
1. period_days < 7 → не называй «неделей», пиши «за N дней». Не экстраполируй.
2. Ограничение 14 дней относится только к labs.out_of_range. results_in_period и trends могут быть старше; сроки пересдачи разрешено брать только из labs.retest.
3. garmin.total_days_logged ≤ 3 → не оценивай сон/восстановление, просто скажи что данных пока мало.
4. Опирайся ТОЛЬКО на данные из JSON. Ничего не выдумывай.
5. Если текущее или прошлое окно пересекается с noise_markers (см. periods) — обязательно учитывай, какое из сравнений веса искажено (причина из reason).
   - direction="up"      → масштаб ЗАВЫШЕН шумом (загрузка креатином, скачок натрия, задержка воды). Реальный темп потери жира ЛУЧШЕ, чем показывает тренд; после конца маркера жди откат вверх на скользящем среднем + замедление видимого снижения — это нормально и НЕ означает потерю темпа.
   - direction="down"    → масштаб ЗАНИЖЕН (обезвоживание, болезнь). Реальная ситуация ХУЖЕ чем числа.
   - direction=null/"neutral" → направление неизвестно, просто отметь что данные зашумлены.

ПИТАНИЕ: пользователь часто забивает на трекинг. Если days_with_logs мало или калории нереалистично низкие — это пропущенный лог, а не голодовка. Не паникуй, просто отметь что данных мало.

ЧТО ПИСАТЬ:
Главный критерий: отчёт бесполезен, если пользователь мог получить то же самое, открыв дашборд. Все текущие значения он уже видит — там они крупнее и свежее. Ты нужен ради того, чего на экране нет физически, в этом порядке приоритета:

1. ИЗМЕНЕНИЕ. Что сдвинулось против прошлого периода и насколько (period_stats.current vs previous). Пересказ текущего значения без дельты — впустую потраченный абзац.
2. СВЯЗЬ МЕЖДУ ДОМЕНАМИ. Это то, чего он ждёт и чего пока не получает. Работай по таблице days: бери день, где один столбец заметно отклонился, и смотри, что стояло в остальных столбцах в этот день и в соседние. Тренировка ↔ сон и HRV следующей ночи; exposure вечером ↔ метрика наутро; тяжёлый день или офис ↔ восстановление; провал калорий ↔ шаги, стресс, вес через пару дней; HRT/добавки ↔ анализы, кожа, настроение.
   Связь без дат не считается. «Сон связан с нагрузкой» — пустая фраза, её можно написать не глядя в данные. «28-го сессия на 11 т, в ночь после неё HRV 41 против обычных 53, и это повторилось 1-го» — наблюдение. Если ни одного такого совпадения в данных нет — скажи об этом одной строкой и не подменяй его общими словами о том, как связаны домены вообще.
   Минимум одна такая проверенная по датам связь на отчёт, если данные вообще позволяют её найти.
3. ДРЕЙФ И ТРАЕКТОРИЯ. Куда всё идёт, если ничего не менять: labs.trends внутри нормы, наклон веса против дедлайна цели, тоннаж от периода к периоду.
4. ПРОТИВОРЕЧИЯ. Где данные спорят друг с другом или с его словами — сигнал говорит одно, метрика другое; тренд ускорился, а питание не менялось. Назвать противоречие ценнее, чем натянуть на него объяснение.
5. ЧЕГО НЕ ХВАТАЕТ. Какой цифры не хватило, чтобы ответить на важный вопрос, и что залогировать, чтобы в следующий раз ответ был.

Не открывай отчёт пересказом текущих значений. Первая же мысль должна быть выводом, которого нет на экране.
Честность важнее полноты: если по домену дельта в пределах шума или данных мало — так и скажи одной строкой и иди дальше. Отсутствие вывода — нормальный вывод; выдуманная связь — нет.

КАК ПИСАТЬ:
- Язык: русский.
- Тон: прямой, уверенный, дружеский. Как если бы знающий друг скинул голосовое с разбором. Без канцелярита, без «давай разберём», без «важно отметить».
- Объём: пиши развёрнуто, с аргументацией. Копай вглубь, не ограничивайся парой предложений на тему. Но если по конкретному домену данных мало или сказать нечего — не тяни, отметь коротко и иди дальше.
- Структура свободная. Группируй по смыслу, а не по доменам. Если по домену нечего сказать — не создавай для него секцию. Заголовки (##) — короткие, по делу, можно с одним подходящим эмодзи в начале.
- Используй **жирный** для ключевых цифр и выводов, > для важных предупреждений, списки для перечислений. Табличные данные — GFM pipe-таблицы (| ... | с |---|---| разделителем).
- Эмодзи: используй умеренно и к месту. Один эмодзи в заголовке секции — ок. В тексте — только если реально добавляет смысл (⚠️ для предупреждений, ✅ для ок-статуса). Не засыпай текст эмодзи, но и не избегай их.
"""

DIGEST_SYSTEM_EN = """\
You write periodic digests for a user of the Vitals health dashboard.

The user is a young guy who knows his stuff (recomp, GLP-1, lifting, Garmin). He doesn't need basic concepts explained. He needs the big picture: what's actually happening, where things are headed, and what to watch.

ROLE: you're a knowledgeable peer. Not a doctor, not a coach, not a mentor. Speak directly, no fluff, no panic, no patronizing. If data is thin — say so, don't stretch conclusions.

INPUT DATA (JSON):
The context has schema_version=2. Any domain may be null, but null alone does NOT mean the user does not track it: read coverage first.
- report_meta: report_date, mode, period_start / period_end, previous_start / previous_end and period_days. closed_period contains FULLY CLOSED days and ends yesterday when generated today; daily_brief is the explicit current-day mode. Name the period by period_start–period_end.
- coverage: enabled/status, current/previous row counts, first_date/last_date, freshness_days (age of the latest row relative to period_end), and truncated for every domain. Say "there is no data" only when the module is enabled, status=empty and truncated=false. disabled is an owner choice; truncated means more data may exist. metric_samples and period_stats.sample_counts are the real denominators for individual metrics.
- days: THE DAY TABLE — one row per day with a compact full Garmin daily row, weight and measurements, every macro, separate garmin_activities and hevy_workouts arrays, GLP-1/HRT events, skincare, resolved day context and signals. A missing key means no value for that day. Legacy workout is only one Hevy session for compatibility; use hevy_workouts for analysis.
  THIS IS THE MAIN TOOL FOR FINDING LINKS. Read it column-wise and look for shifted coincidences: a session → next night's sleep and HRV; an evening exposure → the next morning's metric; a heavy or office day → recovery; low-calorie days → steps, stress, weight two or three days later. Name the link WITH DATES ("after the session on the 28th, HRV sat two nights below its usual") — without dates it isn't an observation, it's a generality. If a coincidence happens once, say it happened once rather than calling it a pattern.
- user_profile: age, height, program, goals
- weight: latest reading as of period_end, MA7 and trend, noise_markers, recent anthropometric measurements and measurement_delta
  IMPORTANT: if a noise_marker is active, ma7_date is the last clean day BEFORE the noise started — not today. Do NOT compare latest_kg and ma7_kg as if they are simultaneous. Any gap between them reflects how stale the MA is, not current noise.
- glp1: active phase as of period_end, plateau, phases overlapping both windows, injections and side_effects labelled period=current/previous
- body_comp: latest BIA/InBody scan plus scans and deltas_from_previous_scan. BIA coexists with the Navy estimate in weight; never conflate them.
- garmin: the LAST day as of period_end with every compact daily field and activities from both windows (no intraday/splits). Read aerobic load from duration/distance/training effect and HR zones.
  IMPORTANT: this is one day. Read spread, trend and "normal/abnormal" off the days table and period_stats, not off it. total_days_logged is how many Garmin days sit in the database IN TOTAL, not the length of this report: it only says whether history exists at all. Never present it as the report's sample size ("N days of history, so the numbers are trustworthy").
- hevy: total_workouts — workouts INSIDE the period; last_workout — date of the latest; mean_gap_days — average interval between sessions; sessions — sessions in the period AND in the equally long stretch before it (in_period=false — before the window starts). Each carries volume_kg (working-set tonnage), working_sets, duration_min, exercises.
  IMPORTANT: training cadence is mean_gap_days and the intervals between dates in sessions, not total_workouts. The counter depends on which day the report was generated: two sessions 5-7 days apart land in one slice or in two. So don't use total_workouts as a measure of the routine at all.
  THE SAME GOES FOR VOLUME. Compare volume_per_session_kg — the tonnage of ONE session. The period sum (training_volume_kg) moves with the session count: one session against two reads as "volume down 51%" when both sessions were identical. Never headline the delta of the sum or call it a drop in volume; when the windows hold different numbers of sessions, the difference in the sum is a difference in session count and doesn't deserve a sentence.
  Silently. Don't explain how the window works, don't write "formally X but actually Y", don't announce that the counter is misleading. He didn't ask for a critique of the method — he asked about his own state. Just say the fact: "you train every 3-4 days, volume is holding" — and move on.
- training: Garmin and Hevy remain source-separated. They may describe one session; never add them into a unique-workout count without matching time/type.
- labs: results_in_period has EVERY result measured in the period; out_of_range has only fresh latest abnormalities; trends has the last 3 points; retest contains the only allowed follow-up cadence. Never invent a retest interval when retest_interval_days is absent.
- period_stats: {current, previous} — symmetric recovery, activity, weight, Hevy/Garmin and all-macro averages. THIS IS THE KEY BLOCK for change. Every mean has its denominator in sample_counts.
  DENOMINATORS, before concluding anything about missed days: days is the window length (every day in it is closed), garmin_days / nutrition_days_logged is how many of them actually carry numbers. A difference built on two days against seven is a difference in coverage, not in the body, and must be called that. Only mention coverage when it actually limits a conclusion — "data is present for every day" is not an observation, it's a status report about yourself.
- nutrition: average calories/protein/fat/carbs, coverage and late meals
- hrt: cycle.items/schedule are the prescribed plan; planned_administrations are planned; doses are current-window facts and comparison_doses are previous-window facts; side effects are split likewise. Relate the intervention to sleep/HRV, labs, skin and mood, but do not prescribe doses.
- supplements is a current catalog, not a daily adherence log; skincare has products, actual daily logs and observations; genetics contains curated impact/interpretation/action_notes only; alerts are active warnings as of the slice.
- timeline: manual events plus only derived lifecycle events not duplicated by first-class blocks. certainty=audit_timestamp means an approximate catalog-change date.
- signals: what the user said about how he felt, in chronological order. kind=state (always present, value_num 1-5), symptom (happened, value_num 1-5), exposure (did/took it, at_time = time of day). note is his original wording. The only block that explains WHY the numbers look like they do: look for "exposure in the evening → Garmin metric next morning" and "symptom running N days straight → what else those days had". These are his words, not measurements — don't treat them as exact figures and don't build a conclusion on a single row.
- day_context: planned is the template guess, answers are manual overrides, resolved is the effective result, and source_by_field carries the strength of each field. Do not build a conclusion on one template-only field.
- milestones: active goals with progress and deadlines

INVARIANTS (breaking = bug):
1. period_days < 7 → don't call it a "week", say "these N days". Don't extrapolate.
2. The 14-day rule applies only to labs.out_of_range. results_in_period and trends can be older; retest timing may come only from labs.retest.
3. garmin.total_days_logged ≤ 3 → don't evaluate sleep/recovery, just say not enough data yet.
4. Use ONLY data from the JSON. Don't invent anything.
5. If either window overlaps noise_markers (see periods), account for which side of the weight comparison is distorted (reason from marker).
   - direction="up"      → scale INFLATED by noise (creatine loading, sodium spike, water retention). Real fat-loss pace is BETTER than the trend shows; after the marker ends expect the moving average to bounce up and visible loss to slow — that is normal and does NOT mean progress has stalled.
   - direction="down"    → scale DEFLATED (dehydration, illness). Real situation is WORSE than numbers.
   - direction=null/"neutral" → direction unknown, just note data is noisy.

NUTRITION: user often skips tracking. Low days_with_logs or unrealistically low calories = missed log, not starvation. Don't panic, just note data is sparse.

WHAT TO WRITE:
The test that matters: the report is useless if the user could have got the same thing by opening the dashboard. He already sees every current value there — bigger and fresher. You exist for what the screen physically cannot show, in this order of priority:

1. CHANGE. What moved against the previous period and by how much (period_stats.current vs previous). Restating a current value without a delta is a wasted paragraph.
2. CROSS-DOMAIN LINKS. This is what he is waiting for and not getting. Work off the days table: take a day where one column moved noticeably and look at what the other columns held that day and the days around it. Training ↔ next night's sleep and HRV; an evening exposure ↔ the next morning's metric; a heavy or office day ↔ recovery; a calorie dip ↔ steps, stress, weight a couple of days later; HRT/supplements ↔ labs, skin, mood.
   A link without dates doesn't count. "Sleep is related to load" is an empty sentence anyone could write without opening the data. "The session on the 28th ran 11 t, HRV that night was 41 against a usual 53, and it repeated on the 1st" is an observation. If no such coincidence exists in the data — say so in one line rather than substituting generalities about how domains relate.
   At least one date-checked link per report, whenever the data allows one to be found.
3. DRIFT AND TRAJECTORY. Where this ends up if nothing changes: labs.trends inside the normal range, the weight slope against a goal deadline, tonnage period over period.
4. CONTRADICTIONS. Where the data argues with itself or with his own words — a signal says one thing and the metric another; the trend accelerated while nutrition didn't move. Naming a contradiction beats inventing an explanation for it.
5. WHAT'S MISSING. Which number you needed and didn't have to answer an important question, and what to log so the answer exists next time.

Don't open the report by restating current values. The first thought should already be a conclusion that isn't on the screen.
Honesty over completeness: if a domain's delta is within noise or its data is thin — say so in one line and move on. No conclusion is a valid conclusion; an invented connection is not.

HOW TO WRITE:
- Language: English.
- Tone: direct, confident, friendly. Like a knowledgeable friend sending a voice note with their take. No corporate speak, no "let's dive in", no "it's important to note".
- Length: write with depth and reasoning. Dig into the why, don't just skim. But if a specific domain has thin data or nothing to say — note it briefly and move on.
- Free structure. Group by insight, not by domain. If a domain has nothing to say — skip it. Headers (##) — short, to the point, one fitting emoji at the start is fine.
- Use **bold** for key numbers and conclusions, > for important warnings, lists for enumerations. Tabular data — GFM pipe tables (| ... | with |---|---| separator).
- Emoji: use sparingly and meaningfully. One emoji per section header — fine. In body text — only when it genuinely adds meaning (⚠️ for warnings, ✅ for ok status). Don't spam emoji, but don't avoid them either.
"""



# ── Context assembly ──────────────────────────────────────────────────────────
async def assemble_context(
    session: AsyncSession,
    *,
    on_date: Optional[date_type] = None,
    period_days: int = 7,
    mode: str = REPORT_MODE_CLOSED,
    enabled_modules: Optional[dict[str, bool]] = None,
    max_period_days: int = MAX_PERIOD_DAYS,
) -> dict:
    """Build the versioned, date-bounded context shared by report consumers.

    Optional domains are gated before their queries run. Empty, disabled, and
    truncated sources remain distinguishable through the ``coverage`` block.
    """
    window = report_window(
        on_date=on_date,
        period_days=period_days,
        mode=mode,
        max_period_days=max_period_days,
    )
    today = window.report_date
    period_start = window.period_start
    period_end = window.period_end
    prev_start = window.previous_start
    prev_end = window.previous_end

    from vitals.services import modules_service

    if enabled_modules is None:
        enabled = await modules_service.get_enabled_modules(session)
    else:
        enabled = {
            key: (
                True
                if spec.category == "core"
                else bool(enabled_modules.get(key, False))
            )
            for key, spec in modules_service.MODULE_REGISTRY.items()
        }

    def module_on(key: str) -> bool:
        spec = modules_service.MODULE_REGISTRY[key]
        return spec.category == "core" or bool(enabled.get(key))

    def domain_visible(domain: str) -> bool:
        """Apply the owning module's gate to secondary cross-domain surfaces."""
        module_key = _DOMAIN_MODULE.get(domain)
        return bool(module_key and module_on(module_key))

    from vitals.config import load_config
    cfg = load_config()

    ctx: dict[str, Any] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "date": today.isoformat(),  # Keep for backward compatibility
        "report_meta": {
            "report_date": today.isoformat(),
            "period_days": period_days,
            "mode": mode,
            # What the window actually covers, so the narrative dates the period
            # rather than the moment it was generated in.
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "previous_start": prev_start.isoformat(),
            "previous_end": prev_end.isoformat(),
        },
        "coverage": {},
        "user_profile": {
            "age": cfg.user_age,
            "sex": cfg.sex,
            "height_cm": cfg.height_cm,
            "program": cfg.user_program,
            "goals": cfg.user_goals,
        },
    }

    from vitals.services import weight_service

    # Protocol phases have their own bounded block below; the chart helper is
    # used only for weight trend math here, so do not perform its overlay query.
    series = await weight_service.chart_series(
        session, end=period_end, include_glp1=False
    )
    all_weights = list(await weight_service.list_active_weights(session, end=period_end))
    weights = [w for w in all_weights if prev_start <= w.date <= period_end]

    markers = await weight_service.list_noise_markers(session)
    matching_markers = []
    for m in markers:
        if m.start_date <= period_end and (
            m.end_date is None or m.end_date >= prev_start
        ):
            marker_periods = []
            if m.start_date <= period_end and (
                m.end_date is None or m.end_date >= period_start
            ):
                marker_periods.append("current")
            if m.start_date <= prev_end and (
                m.end_date is None or m.end_date >= prev_start
            ):
                marker_periods.append("previous")
            matching_markers.append({
                "start": m.start_date.isoformat(),
                "end": m.end_date.isoformat() if m.end_date else None,
                "periods": marker_periods,
                "reason": m.reason,
                # direction: which way the scale is biased vs real fat trend.
                # up   = scale inflated (creatine/sodium) → real loss is better
                # down = scale deflated (dehydration)     → real situation worse
                # null = unknown / treat as neutral
                "direction": m.direction,
            })

    last_ma = series["trend_ma"][-1] if series["trend_ma"] else None
    latest_weight = all_weights[-1] if all_weights else None
    ctx["weight"] = {
        "latest_kg": latest_weight.weight_kg if latest_weight else None,
        # When that measurement was taken. ``latest_kg`` is the newest weight as
        # of this report's period_end; without the date an old value reads as if
        # it were measured today.
        "latest_date": latest_weight.date.isoformat() if latest_weight else None,
        "ma7_kg": last_ma["weight_kg"] if last_ma else None,
        # Date the MA7 was last calculated. During a noise period ALL measurements
        # inside it are excluded from the MA, so ma7_date will be the last clean
        # day BEFORE the noise started — potentially weeks ago. Do NOT compare
        # latest_kg directly to ma7_kg as if they describe the same moment.
        "ma7_date": last_ma["date"] if last_ma else None,
        "trend_kg_per_week": series["trend"]["slope_per_week"] if series.get("trend") else None,
        "noise_markers": matching_markers,
    }

    from vitals.models.weight import BodyMeasurement

    measurement_rows = list(
        (
            await session.execute(
                select(BodyMeasurement)
                .where(BodyMeasurement.date <= period_end)
                .order_by(BodyMeasurement.date.desc(), BodyMeasurement.id.desc())
                .limit(_BODY_MEASUREMENT_LIMIT + 1)
            )
        ).scalars().all()
    )
    measurements_truncated = len(measurement_rows) > _BODY_MEASUREMENT_LIMIT
    measurement_rows = measurement_rows[:_BODY_MEASUREMENT_LIMIT]
    measurement_history = [
        {
            "date": row.date.isoformat(),
            "neck_cm": row.neck_cm,
            "waist_cm": row.waist_cm,
            "hips_cm": row.hips_cm,
            "body_fat_pct": row.body_fat_pct,
            "lbm_kg": row.lbm_kg,
            "note": row.note,
            "source": row.source,
        }
        for row in reversed(measurement_rows)
    ]
    measurement_delta = None
    if len(measurement_history) >= 2:
        previous_measurement, latest_measurement = measurement_history[-2:]
        measurement_delta = {
            key: (
                round(latest_measurement[key] - previous_measurement[key], 2)
                if latest_measurement[key] is not None
                and previous_measurement[key] is not None
                else None
            )
            for key in ("neck_cm", "waist_cm", "hips_cm", "body_fat_pct", "lbm_kg")
        }
        measurement_delta["from_date"] = previous_measurement["date"]
        measurement_delta["to_date"] = latest_measurement["date"]
    ctx["weight"]["measurements"] = measurement_history or None
    ctx["weight"]["measurement_delta"] = measurement_delta
    ctx["coverage"]["weight"] = _coverage(
        module="weight",
        enabled=True,
        dates=[row.date for row in all_weights],
        window=window,
        truncated=measurements_truncated,
        extra={
            "measurement_rows": len(measurement_rows),
            "measurement_limit": _BODY_MEASUREMENT_LIMIT,
            "measurements_truncated": measurements_truncated,
        },
    )

    from vitals.services import glp1_service

    glp1_enabled = module_on("glp1")
    glp1_injections: list[Any] = []
    glp1_effects: list[Any] = []
    glp1_phases: list[Any] = []
    glp1_truncated = False
    injections_truncated = False
    effects_truncated = False
    phases_truncated = False
    if glp1_enabled:
        from vitals.models.glp1 import DosePhase, Injection, SideEffect

        glp1_injections, injections_truncated = await _bounded_scalars(
            session,
            select(Injection)
            .where(Injection.date >= prev_start, Injection.date <= period_end)
            .order_by(Injection.date, Injection.id),
            _TREATMENT_EVENT_LIMIT,
        )
        glp1_effects, effects_truncated = await _bounded_scalars(
            session,
            select(SideEffect)
            .where(SideEffect.date >= prev_start, SideEffect.date <= period_end)
            .order_by(SideEffect.date, SideEffect.id),
            _TREATMENT_EVENT_LIMIT,
        )
        glp1_phases, phases_truncated = await _bounded_scalars(
            session,
            select(DosePhase)
            .where(
                DosePhase.start_date <= period_end,
                or_(DosePhase.end_date.is_(None), DosePhase.end_date >= prev_start),
            )
            .order_by(DosePhase.start_date, DosePhase.id),
            _TREATMENT_EVENT_LIMIT,
        )
        glp1_truncated = any(
            (injections_truncated, effects_truncated, phases_truncated)
        )
        phase = await glp1_service.active_dose_phase(session, on_date=period_end)
        ctx["glp1"] = {
            # Legacy headline fields.
            "drug": phase.drug if phase else None,
            "dose_mg": phase.dose_mg if phase else None,
            "plateau": await glp1_service.evaluate_plateau(
                session, on_date=period_end
            ),
            "active_phase": (
                {
                    "start_date": phase.start_date.isoformat(),
                    "end_date": phase.end_date.isoformat() if phase.end_date else None,
                    "drug": phase.drug,
                    "dose_mg": phase.dose_mg,
                    "note": phase.note,
                    "source": phase.source,
                }
                if phase
                else None
            ),
            "phases": [
                {
                    "start_date": row.start_date.isoformat(),
                    "end_date": row.end_date.isoformat() if row.end_date else None,
                    "drug": row.drug,
                    "dose_mg": row.dose_mg,
                    "note": row.note,
                    "source": row.source,
                }
                for row in glp1_phases
            ] or None,
            "injections": [
                {
                    "date": row.date.isoformat(),
                    "period": _period_name(row.date, window),
                    "drug": row.drug,
                    "dose_mg": row.dose_mg,
                    "site": row.site,
                    "note": row.note,
                    "source": row.source,
                }
                for row in glp1_injections
            ] or None,
            "side_effects": [
                {
                    "date": row.date.isoformat(),
                    "period": _period_name(row.date, window),
                    "effect_type": row.effect_type,
                    "severity": row.severity,
                    "note": row.note,
                    "source": row.source,
                }
                for row in glp1_effects
            ] or None,
        }
    else:
        ctx["glp1"] = None
    ctx["coverage"]["glp1"] = _coverage(
        module="glp1",
        enabled=glp1_enabled,
        dates=[
            *(row.date for row in (*glp1_injections, *glp1_effects)),
            *(row.start_date for row in glp1_phases),
        ],
        window=window,
        rows=len(glp1_injections) + len(glp1_effects) + len(glp1_phases),
        truncated=glp1_truncated,
        extra={
            "event_limit_per_collection": _TREATMENT_EVENT_LIMIT,
            "phase_rows": len(glp1_phases),
            "injections_truncated": injections_truncated,
            "side_effects_truncated": effects_truncated,
            "phases_truncated": phases_truncated,
        },
    )

    from vitals.services.analytics.body_metrics import (
        HEADLINE_KEYS,
        METRIC_REGISTRY,
        lbm_from_scan,
    )

    body_comp_enabled = module_on("body_comp")
    scans: list[Any] = []
    scans_truncated = False
    if body_comp_enabled:
        from vitals.models.body_scan import BodyScan

        scans, scans_truncated = await _bounded_scalars(
            session,
            select(BodyScan)
            .where(BodyScan.date <= period_end)
            .options(selectinload(BodyScan.metrics))
            .order_by(BodyScan.date.desc(), BodyScan.id.desc()),
            _BODY_SCAN_LIMIT,
        )
    scan = scans[0] if scans else None
    if scan is not None:
        by_key = {m.metric_key: m for m in scan.metrics}
        comp_metrics: dict[str, Any] = {}
        for k in HEADLINE_KEYS:
            m = by_key.get(k)
            if m is not None:
                spec = METRIC_REGISTRY.get(k)
                comp_metrics[k] = {
                    "value": m.value,
                    "unit": m.unit or (spec.unit if spec else None),
                }
        lbm = lbm_from_scan(scan.metrics)
        if lbm is not None:
            comp_metrics["lean_body_mass"] = {"value": lbm, "unit": "кг"}
        scan_history = []
        for history_scan in reversed(scans):
            metrics = []
            for metric in history_scan.metrics:
                if metric.metric_key not in _REPORT_BODY_METRIC_KEYS:
                    continue
                spec = METRIC_REGISTRY.get(metric.metric_key)
                metrics.append(
                    {
                        "key": metric.metric_key,
                        "value": metric.value,
                        "unit": metric.unit or (spec.unit if spec else None),
                        "segment": metric.segment,
                        "ref_low": metric.ref_low,
                        "ref_high": metric.ref_high,
                    }
                )
            derived_lbm = lbm_from_scan(history_scan.metrics)
            if derived_lbm is not None and not any(
                item["key"] == "lean_body_mass" and item["segment"] is None
                for item in metrics
            ):
                metrics.append(
                    {
                        "key": "lean_body_mass",
                        "value": derived_lbm,
                        "unit": "кг",
                        "segment": None,
                        "ref_low": None,
                        "ref_high": None,
                    }
                )
            scan_history.append(
                {
                    "date": history_scan.date.isoformat(),
                    "device": history_scan.device,
                    "metrics": metrics,
                    "source": history_scan.source,
                }
            )

        deltas = []
        if len(scan_history) >= 2:
            previous_metrics = {
                (item["key"], item["segment"]): item["value"]
                for item in scan_history[-2]["metrics"]
            }
            for item in scan_history[-1]["metrics"]:
                previous_value = previous_metrics.get((item["key"], item["segment"]))
                if previous_value is None:
                    continue
                deltas.append(
                    {
                        "key": item["key"],
                        "segment": item["segment"],
                        "value": round(item["value"] - previous_value, 3),
                        "unit": item["unit"],
                    }
                )
        ctx["body_comp"] = {
            "date": scan.date.isoformat(),
            "device": scan.device,
            "metrics": comp_metrics,
            "scans": scan_history,
            "deltas_from_previous_scan": deltas or None,
        }
    else:
        ctx["body_comp"] = None
    ctx["coverage"]["body_comp"] = _coverage(
        module="body_comp",
        enabled=body_comp_enabled,
        dates=[row.date for row in scans],
        window=window,
        truncated=scans_truncated,
        extra={"scan_limit": _BODY_SCAN_LIMIT},
    )

    from vitals.services import garmin_service
    from vitals.models.garmin import GarminActivity, GarminDaily

    g = await garmin_service.latest_daily(session, before_or_on=period_end)
    garmin_rows = list(
        await garmin_service.list_daily_between(session, prev_start, period_end)
    )
    garmin_activities, garmin_activities_truncated = await _bounded_scalars(
        session,
        select(GarminActivity)
        .where(
            GarminActivity.date >= prev_start,
            GarminActivity.date <= period_end,
        )
        .order_by(GarminActivity.date, GarminActivity.start_time, GarminActivity.id),
        _GARMIN_ACTIVITY_LIMIT,
    )
    total_days_logged = int(
        (
            await session.execute(
                select(func.count())
                .select_from(GarminDaily)
                .where(
                    GarminDaily.date <= period_end,
                    or_(
                        GarminDaily.sleep_score.is_not(None),
                        GarminDaily.sleep_seconds.is_not(None),
                        GarminDaily.resting_hr.is_not(None),
                        GarminDaily.hrv_avg.is_not(None),
                        GarminDaily.body_battery_high.is_not(None),
                        GarminDaily.avg_stress.is_not(None),
                        GarminDaily.steps.is_not(None),
                        GarminDaily.active_calories.is_not(None),
                    ),
                )
            )
        ).scalar()
        or 0
    )
    if g or garmin_activities:
        garmin_headline = _garmin_daily_row(g) if g else {"date": None}
        garmin_headline.update(
            {
                "advice": garmin_service.recovery_advice(g),
                "total_days_logged": total_days_logged,
                "activities": [
                    {
                        **_garmin_activity_row(row),
                        "period": _period_name(row.date, window),
                    }
                    for row in garmin_activities
                ]
                or None,
            }
        )
        ctx["garmin"] = garmin_headline
    else:
        ctx["garmin"] = None

    def garmin_metric_counts(start: date_type, end: date_type) -> dict[str, int]:
        rows = [row for row in garmin_rows if start <= row.date <= end]
        return {
            key: sum(getattr(row, key) is not None for row in rows)
            for key in _GARMIN_DAILY_FIELDS
        }

    garmin_headline_outside_windows = bool(
        g is not None and all(row.id != g.id for row in garmin_rows)
    )
    ctx["coverage"]["garmin"] = _coverage(
        module="garmin",
        enabled=True,
        dates=[
            *(row.date for row in garmin_rows),
            *(row.date for row in garmin_activities),
            *([g.date] if garmin_headline_outside_windows else []),
        ],
        window=window,
        rows=(
            len(garmin_rows)
            + len(garmin_activities)
            + int(garmin_headline_outside_windows)
        ),
        truncated=garmin_activities_truncated,
        extra={
            "daily_rows": len(garmin_rows),
            "activity_rows": len(garmin_activities),
            "headline_outside_windows": garmin_headline_outside_windows,
            "activity_limit": _GARMIN_ACTIVITY_LIMIT,
            "activities_truncated": garmin_activities_truncated,
            "metric_samples": {
                "current": garmin_metric_counts(period_start, period_end),
                "previous": garmin_metric_counts(prev_start, prev_end),
            },
        },
    )

    from vitals.services import hevy_service

    since = period_start
    hevy_enabled = module_on("hevy")
    hevy_rows: list[Any] = []
    hevy_truncated = False
    if hevy_enabled:
        from vitals.models.hevy import HevyExercise, HevyWorkout

        hevy_rows, hevy_truncated = await _bounded_scalars(
            session,
            select(HevyWorkout)
            .where(HevyWorkout.date >= prev_start, HevyWorkout.date <= period_end)
            .options(
                selectinload(HevyWorkout.exercises).selectinload(HevyExercise.sets)
            )
            .order_by(HevyWorkout.date, HevyWorkout.start_time, HevyWorkout.id),
            _HEVY_SESSION_LIMIT,
        )
        last_workout = (
            await session.execute(
                select(func.max(HevyWorkout.date)).where(
                    HevyWorkout.date <= period_end
                )
            )
        ).scalar()
    else:
        last_workout = None
    sessions = [
        {
            **hevy_service.workout_summary(row),
            "in_period": row.date >= since,
            "period": _period_name(row.date, window),
            "source": row.source,
        }
        for row in hevy_rows
    ]
    # The gap between sessions is the one training number a window edge cannot
    # move. Handed only a count, the narrative had to explain the boundary to say
    # anything true — and nobody wants a paragraph about window boundaries.
    gaps = [
        (date_type.fromisoformat(b["date"]) - date_type.fromisoformat(a["date"])).days
        for a, b in zip(sessions, sessions[1:])
    ]
    ctx["hevy"] = (
        {
            "total_workouts": sum(1 for row in sessions if row["in_period"]),
            "last_workout": last_workout.isoformat() if last_workout else None,
            "mean_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "gap_samples": len(gaps),
            "sessions": sessions or None,
        }
        if hevy_enabled
        else None
    )
    hevy_latest_outside_windows = bool(
        last_workout is not None
        and all(row.date != last_workout for row in hevy_rows)
    )
    ctx["coverage"]["hevy"] = _coverage(
        module="hevy",
        enabled=hevy_enabled,
        dates=[
            *(row.date for row in hevy_rows),
            *([last_workout] if hevy_latest_outside_windows else []),
        ],
        window=window,
        rows=len(hevy_rows) + int(hevy_latest_outside_windows),
        truncated=hevy_truncated,
        extra={
            "session_limit": _HEVY_SESSION_LIMIT,
            "session_rows_in_windows": len(hevy_rows),
            "latest_outside_windows": hevy_latest_outside_windows,
        },
    )

    from vitals.services import labs_service
    from vitals.models.labs import LabMarker, LabResult

    # Every result in the two comparison windows is retained. Older history is
    # bounded to the latest points per marker, which is all the trend block can
    # emit; this avoids loading an unbounded lifetime table just to slice it in
    # Python afterwards.
    lab_window_rows = list(
        (
            await session.execute(
                select(LabResult)
                .where(
                    LabResult.date >= prev_start,
                    LabResult.date <= period_end,
                )
                .order_by(LabResult.date.desc(), LabResult.id.desc())
            )
        ).scalars().all()
    )
    ranked_lab_ids = (
        select(
            LabResult.id.label("id"),
            func.row_number()
            .over(
                partition_by=LabResult.marker,
                order_by=(LabResult.date.desc(), LabResult.id.desc()),
            )
            .label("history_rank"),
        )
        .where(LabResult.date <= period_end)
        .subquery()
    )
    recent_lab_rows = list(
        (
            await session.execute(
                select(LabResult)
                .join(ranked_lab_ids, LabResult.id == ranked_lab_ids.c.id)
                .where(ranked_lab_ids.c.history_rank <= _LAB_HISTORY_PER_MARKER)
                .order_by(LabResult.date.desc(), LabResult.id.desc())
            )
        ).scalars().all()
    )
    lab_rows_by_id = {
        row.id: row for row in (*lab_window_rows, *recent_lab_rows)
    }
    lab_rows = sorted(
        lab_rows_by_id.values(),
        key=lambda row: (row.date, row.id),
        reverse=True,
    )
    total_lab_rows_as_of = int(
        (
            await session.execute(
                select(func.count())
                .select_from(LabResult)
                .where(LabResult.date <= period_end)
            )
        ).scalar()
        or 0
    )
    labs_truncated = total_lab_rows_as_of > len(lab_rows)
    marker_rows: dict[str, list[Any]] = {}
    for row in lab_rows:
        marker_rows.setdefault(row.marker, []).append(row)
    marker_catalog = {
        row.name: row
        for row in (
            await session.execute(select(LabMarker).order_by(LabMarker.name))
        ).scalars().all()
    }
    latest_labs = [rows[0] for rows in marker_rows.values()]
    results_in_period = [
        row for row in lab_rows if period_start <= row.date <= period_end
    ]
    retest_rows = []
    for marker, rows in marker_rows.items():
        latest = rows[0]
        catalog = marker_catalog.get(marker)
        interval = catalog.retest_interval_days if catalog else None
        next_retest = latest.date + timedelta(days=interval) if interval else None
        deferred = bool(
            catalog
            and catalog.defer_until is not None
            and catalog.defer_until > period_end
        )
        retest_rows.append(
            {
                "marker": marker,
                "latest_date": latest.date.isoformat(),
                "tier": catalog.tier if catalog else None,
                "retest_interval_days": interval,
                "next_retest_date": next_retest.isoformat() if next_retest else None,
                "defer_until": (
                    catalog.defer_until.isoformat()
                    if catalog and catalog.defer_until
                    else None
                ),
                "due": bool(next_retest and next_retest <= period_end and not deferred),
                "note": catalog.note if catalog else None,
            }
        )

    ctx["labs"] = {
        "out_of_range": [
            {
                "marker": row.marker,
                "value": row.value,
                "unit": row.unit,
                "flag": row.flag,
                "date": row.date.isoformat(),
                "ref_low": row.ref_low,
                "ref_high": row.ref_high,
                "lab_name": row.lab_name,
                "note": row.note,
                "source": row.source,
            }
            for row in latest_labs
            if labs_service.is_out_of_range(row.flag)
            and 0 <= (period_end - row.date).days <= 14
        ],
        "results_in_period": [
            {
                "marker": row.marker,
                "value": row.value,
                "unit": row.unit,
                "flag": row.flag,
                "date": row.date.isoformat(),
                "ref_low": row.ref_low,
                "ref_high": row.ref_high,
                "lab_name": row.lab_name,
                "note": row.note,
                "source": row.source,
            }
            for row in reversed(results_in_period)
        ]
        or None,
        "trends": [
            {
                "marker": marker,
                "unit": rows[0].unit,
                "ref_low": rows[0].ref_low,
                "ref_high": rows[0].ref_high,
                "points": [
                    {
                        "date": row.date.isoformat(),
                        "value": row.value,
                        "flag": row.flag,
                    }
                    for row in reversed(rows[:_LAB_HISTORY_PER_MARKER])
                ],
            }
            for marker, rows in marker_rows.items()
            if len(rows) >= 2
        ]
        or None,
        "retest": retest_rows or None,
    }
    ctx["coverage"]["labs"] = _coverage(
        module="labs",
        enabled=True,
        dates=[row.date for row in lab_rows],
        window=window,
        truncated=labs_truncated,
        extra={
            "markers": len(marker_rows),
            "history_limit_per_marker": _LAB_HISTORY_PER_MARKER,
            "total_rows_as_of_period_end": total_lab_rows_as_of,
        },
    )

    from vitals.services import nutrition_service

    # Two periods of meals: the block below is about this one, the comparison at
    # the end needs the one before it, and one read covers both.
    nutrition_enabled = module_on("nutrition")
    all_meals = list(
        await nutrition_service.list_meals(
            session, start=prev_start, end=period_end
        )
    ) if nutrition_enabled else []
    all_meals_by_date: dict[date_type, list[Any]] = {}
    for meal in all_meals:
        all_meals_by_date.setdefault(meal.date, []).append(meal)
    nutrition_totals_by_date = {
        on_date: _nutrition_day_totals(day_meals)
        for on_date, day_meals in all_meals_by_date.items()
    }
    nutrition_meals = [m for m in all_meals if m.date >= since]
    if nutrition_meals:
        current_totals = [
            totals
            for on_date, totals in nutrition_totals_by_date.items()
            if period_start <= on_date <= period_end
        ]
        days_with_logs = len(current_totals)
        meals_after_21 = sum(
            bool(m.eaten_at and m.eaten_at.hour >= 21) for m in nutrition_meals
        )
        goals = nutrition_service.get_goals(cfg)
        ctx["nutrition"] = {
            "avg_calories_per_day": _mean(
                totals["calories"] for totals in current_totals
            ),
            "avg_protein_per_day_g": _mean(
                totals["protein_g"] for totals in current_totals
            ),
            "avg_fat_per_day_g": _mean(
                totals["fat_g"] for totals in current_totals
            ),
            "avg_carbs_per_day_g": _mean(
                totals["carbs_g"] for totals in current_totals
            ),
            "days_with_logs": days_with_logs,
            "total_meals": len(nutrition_meals),
            "meals_after_21": meals_after_21,
            "metric_samples": {
                key: sum(totals[key] is not None for totals in current_totals)
                for key, _attr in _NUTRITION_FIELDS
            },
            "goals": goals,
        }
    else:
        ctx["nutrition"] = None
    ctx["coverage"]["nutrition"] = _coverage(
        module="nutrition",
        enabled=nutrition_enabled,
        dates=[row.date for row in all_meals],
        window=window,
        extra={
            "metric_samples": {
                period: {
                    key: sum(
                        totals[key] is not None
                        for on_date, totals in nutrition_totals_by_date.items()
                        if start <= on_date <= end
                    )
                    for key, _attr in _NUTRITION_FIELDS
                }
                for period, start, end in (
                    ("current", period_start, period_end),
                    ("previous", prev_start, prev_end),
                )
            }
        },
    )

    # Supplements / skincare / genetics / active alerts — enabled domains the
    # digest used to ignore, so cross-domain reasoning it promises (e.g. "started
    # ashwagandha → sleep/HRV shifted", "introduced a retinoid → skin reacted")
    # had no data to work with. Each domain is read through its own service (lazy
    # import); empty → null.
    from vitals.services import supplements_service

    supplements_enabled = module_on("supplements")
    all_supps = list(
        await supplements_service.list_supplements(session, active_only=False)
    ) if supplements_enabled else []
    active_supps = [row for row in all_supps if row.active]
    ctx["supplements"] = (
        [
            {
                "key": s.key,
                "name": s.name,
                "dose": s.dose,
                "timing": s.timing,
                "evidence": s.evidence,
                "contraindications": s.contraindications,
                "note": s.note,
                "source": s.source,
                # The table is a current catalog, not a dated adherence log.
                "state_is_current_catalog": True,
            }
            for s in active_supps
        ]
        if active_supps
        else None
    )
    ctx["coverage"]["supplements"] = _coverage(
        module="supplements",
        enabled=supplements_enabled,
        window=window,
        rows=len(all_supps),
        extra={
            "active_rows": len(active_supps),
            "historical_state_reliable": False,
        },
    )

    from vitals.services import skincare_service
    from vitals.models.skincare import SkincareLog, SkincareObservation

    skincare_enabled = module_on("skincare")
    if skincare_enabled:
        skin_logs, skin_logs_truncated = await _bounded_scalars(
            session,
            select(SkincareLog)
            .where(
                SkincareLog.date >= prev_start,
                SkincareLog.date <= period_end,
            )
            .order_by(SkincareLog.date.desc(), SkincareLog.id.desc()),
            _SKINCARE_EVENT_LIMIT,
        )
        skin_obs, skin_obs_truncated = await _bounded_scalars(
            session,
            select(SkincareObservation)
            .where(
                SkincareObservation.date >= prev_start,
                SkincareObservation.date <= period_end,
            )
            .order_by(
                SkincareObservation.date.desc(),
                SkincareObservation.id.desc(),
            ),
            _SKINCARE_EVENT_LIMIT,
        )
        skin_logs.reverse()
        skin_obs.reverse()
        all_products = list(
            await skincare_service.list_products(session, active_only=False)
        )
        active_products = [row for row in all_products if row.active]
    else:
        skin_logs = []
        skin_obs = []
        all_products = []
        active_products = []
        skin_logs_truncated = False
        skin_obs_truncated = False
    current_skin_obs = [row for row in skin_obs if row.date >= period_start]
    current_skin_logs = [row for row in skin_logs if row.date >= period_start]
    if current_skin_obs or current_skin_logs or active_products:
        ctx["skincare"] = {
            "recent_observations": [
                {
                    "date": o.date.isoformat(),
                    "inflammation": o.inflammation,
                    "pih": o.pih,
                    "zone": o.zone,
                    "note": o.note,
                    "source": o.source,
                }
                for o in current_skin_obs
            ],
            "active_products": len(active_products),
            "products": [
                {
                    "name": product.name,
                    "type": product.type,
                    "active_ingredient": product.active_ingredient,
                    "default_time": product.default_time,
                    "schedule_days": product.schedule_days,
                    "usage_instructions": product.usage_instructions,
                    "state_is_current_catalog": True,
                }
                for product in active_products
            ]
            or None,
            "logs": [_skincare_log_row(row, window) for row in current_skin_logs]
            or None,
            "comparison_logs": [
                _skincare_log_row(row, window)
                for row in skin_logs
                if row.date <= prev_end
            ]
            or None,
            "comparison_observations": [
                {
                    "date": row.date.isoformat(),
                    "inflammation": row.inflammation,
                    "pih": row.pih,
                    "zone": row.zone,
                    "note": row.note,
                    "source": row.source,
                }
                for row in skin_obs
                if row.date <= prev_end
            ]
            or None,
        }
    else:
        ctx["skincare"] = None
    ctx["coverage"]["skincare"] = _coverage(
        module="skincare",
        enabled=skincare_enabled,
        dates=[row.date for row in (*skin_logs, *skin_obs)],
        window=window,
        rows=len(skin_logs) + len(skin_obs) + len(all_products),
        truncated=skin_logs_truncated or skin_obs_truncated,
        extra={
            "product_rows": len(active_products),
            "event_limit_per_collection": _SKINCARE_EVENT_LIMIT,
            "logs_truncated": skin_logs_truncated,
            "observations_truncated": skin_obs_truncated,
            "historical_product_state_reliable": False,
        },
    )

    genetics_enabled = module_on("genetics")
    variants: list[Any] = []
    genetics_truncated = False
    if genetics_enabled:
        from vitals.models.genetics import GeneticVariant

        variants, genetics_truncated = await _bounded_scalars(
            session,
            select(GeneticVariant)
            .where(
                or_(
                    GeneticVariant.marker.is_not(None),
                    GeneticVariant.impact.is_not(None),
                    GeneticVariant.interpretation.is_not(None),
                    GeneticVariant.action_notes.is_not(None),
                )
            )
            .order_by(GeneticVariant.gene, GeneticVariant.rsid),
            _GENETICS_LIMIT,
        )
    ctx["genetics"] = [
        {
            "marker": row.marker,
            "gene": row.gene,
            "rsid": row.rsid,
            "genotype": row.genotype,
            "impact": row.impact,
            "impact_domain": row.impact_domain,
            "interpretation": row.interpretation,
            "action_notes": row.action_notes,
            "source": row.source,
        }
        for row in variants
    ] or None
    ctx["coverage"]["genetics"] = _coverage(
        module="genetics",
        enabled=genetics_enabled,
        window=window,
        rows=len(variants),
        truncated=genetics_truncated,
    )

    from vitals.services import alerts_service

    active_alerts = [
        row
        for row in await alerts_service.list_active(session)
        if row.created_at.date() <= period_end
        and domain_visible(row.domain)
    ]
    ctx["alerts"] = (
        [
            {
                "severity": a.severity,
                "domain": a.domain,
                "message": a.message,
                "alert_key": a.alert_key,
            }
            for a in active_alerts
        ]
        if active_alerts
        else None
    )
    ctx["coverage"]["alerts"] = _coverage(
        module="reports",
        enabled=True,
        window=window,
        rows=len(active_alerts),
    )

    # HRT — the strongest intervention in the lake and, until now, invisible to the
    # digest: a compound change and the sleep/labs/skin shift that follows it could
    # never be connected. Active protocol + doses inside the period + side effects.
    from vitals.services import hrt_cycle_service, hrt_service
    from vitals.models.hrt import HrtDose, HrtSideEffect

    hrt_enabled = module_on("hrt")
    cycle = None
    hrt_all_doses: list[Any] = []
    hrt_effects: list[Any] = []
    planned_hrt: list[dict[str, Any]] = []
    hrt_truncated = False
    doses_truncated = False
    hrt_effects_truncated = False
    planned_truncated = False
    compound_names: dict[str, dict[str, Any]] = {}
    if hrt_enabled:
        cycle = await hrt_cycle_service.active_cycle(session, on_date=period_end)
        hrt_all_doses, doses_truncated = await _bounded_scalars(
            session,
            select(HrtDose)
            .where(HrtDose.date >= prev_start, HrtDose.date <= period_end)
            .order_by(HrtDose.date, HrtDose.id),
            _TREATMENT_EVENT_LIMIT,
        )
        hrt_effects, hrt_effects_truncated = await _bounded_scalars(
            session,
            select(HrtSideEffect)
            .where(
                HrtSideEffect.date >= prev_start,
                HrtSideEffect.date <= period_end,
            )
            .order_by(HrtSideEffect.date, HrtSideEffect.id),
            _TREATMENT_EVENT_LIMIT,
        )
        compounds = await hrt_service.list_compounds(session, active_only=False)
        compound_names = {
            row.key: {
                "name": row.name,
                "name_ru": row.name_ru,
                "class": row.compound_class,
                "route": row.route,
                "half_life_hours": row.half_life_hours,
            }
            for row in compounds
        }
        if cycle is not None:
            all_planned = await hrt_cycle_service.planned_administrations(
                session, start=prev_start, end=period_end, cycle=cycle
            )
            planned_truncated = len(all_planned) > _TREATMENT_EVENT_LIMIT
            planned_hrt = all_planned[:_TREATMENT_EVENT_LIMIT]
        hrt_truncated = any(
            (doses_truncated, hrt_effects_truncated, planned_truncated)
        )

    def hrt_dose_row(row) -> dict[str, Any]:
        meta = compound_names.get(row.compound_key) or {}
        return {
            "date": row.date.isoformat(),
            "period": _period_name(row.date, window),
            "compound_key": row.compound_key,
            "compound": meta.get("name"),
            "compound_ru": meta.get("name_ru"),
            "dose": row.dose,
            "unit": row.unit,
            "site": row.site,
            "note": row.note,
            "source": row.source,
        }

    hrt_doses = [row for row in hrt_all_doses if row.date >= period_start]
    previous_hrt_doses = [row for row in hrt_all_doses if row.date <= prev_end]
    current_hrt_effects = [row for row in hrt_effects if row.date >= period_start]
    previous_hrt_effects = [row for row in hrt_effects if row.date <= prev_end]
    ctx["hrt"] = (
        {
            "cycle": (
                {
                    "kind": cycle.kind,
                    "name": cycle.name,
                    "start_date": cycle.start_date.isoformat(),
                    "end_date": cycle.end_date.isoformat() if cycle.end_date else None,
                    "note": cycle.note,
                    "compounds": [item.compound_key for item in cycle.items],
                    "items": [
                        {
                            "compound_key": item.compound_key,
                            **(compound_names.get(item.compound_key) or {}),
                            "unit": item.unit,
                            "start_offset_days": item.start_offset_days,
                            "schedule": item.schedule,
                            "note": item.note,
                        }
                        for item in cycle.items
                    ],
                }
                if cycle is not None
                else None
            ),
            # Legacy current-period fields.
            "doses": [hrt_dose_row(row) for row in hrt_doses],
            "side_effects": [
                {
                    "date": row.date.isoformat(),
                    "period": "current",
                    "effect_type": row.effect_type,
                    "severity": row.severity,
                    "note": row.note,
                    "source": row.source,
                }
                for row in current_hrt_effects
            ],
            "comparison_doses": [
                hrt_dose_row(row) for row in previous_hrt_doses
            ]
            or None,
            "comparison_side_effects": [
                {
                    "date": row.date.isoformat(),
                    "period": "previous",
                    "effect_type": row.effect_type,
                    "severity": row.severity,
                    "note": row.note,
                    "source": row.source,
                }
                for row in previous_hrt_effects
            ]
            or None,
            "planned_administrations": [
                {
                    "date": item["date"].isoformat(),
                    "period": _period_name(item["date"], window),
                    "compound_key": item["compound_key"],
                    "compound": (
                        compound_names.get(item["compound_key"]) or {}
                    ).get("name"),
                    "dose": item["dose"],
                    "unit": item["unit"],
                }
                for item in planned_hrt
            ]
            or None,
        }
        if (cycle is not None or hrt_all_doses or hrt_effects)
        else None
    )
    ctx["coverage"]["hrt"] = _coverage(
        module="hrt",
        enabled=hrt_enabled,
        dates=[
            *(row.date for row in (*hrt_all_doses, *hrt_effects)),
            *([cycle.start_date] if cycle is not None else []),
        ],
        window=window,
        rows=(
            len(hrt_all_doses)
            + len(hrt_effects)
            + len(planned_hrt)
            + int(cycle is not None)
        ),
        truncated=hrt_truncated,
        extra={
            "event_limit_per_collection": _TREATMENT_EVENT_LIMIT,
            "cycle_rows": int(cycle is not None),
            "planned_rows": len(planned_hrt),
            "doses_truncated": doses_truncated,
            "side_effects_truncated": hrt_effects_truncated,
            "planned_truncated": planned_truncated,
        },
    )

    # Timeline — manual annotations (illness, travel, protocol change) overlapping
    # the period. These are exactly the "why" behind a wobble in every other domain,
    # so the narrative has to see them.
    from vitals.services import timeline_service

    timeline_enabled = module_on("timeline")
    timeline_entries: list[dict[str, Any]] = []
    if timeline_enabled:
        annotations = await timeline_service.list_annotations(
            session, start=since, end=period_end
        )
        timeline_entries.extend(
            {
                "date": row.date.isoformat(),
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "kind": row.kind,
                "domain": row.domain,
                "title": row.title,
                "note": row.note,
                "source": "manual",
                "ref": f"annotation:{row.id}",
                "certainty": "exact",
            }
            for row in annotations
            if domain_visible(row.domain)
        )

        # Only lifecycle facts not already represented by a first-class context
        # block are added here. ``updated_at`` is explicitly labelled as an audit
        # timestamp, because these catalogs do not have a true stop-history table.
        for row in all_supps:
            started = row.created_at.date()
            if since <= started <= period_end:
                timeline_entries.append(
                    {
                        "date": started.isoformat(),
                        "end_date": None,
                        "kind": "supplement_started",
                        "domain": "supplements",
                        "title": row.name,
                        "note": None,
                        "source": "derived",
                        "ref": f"supplement_started:{row.id}",
                        "certainty": "audit_timestamp",
                    }
                )
            stopped = row.updated_at.date()
            if not row.active and since <= stopped <= period_end:
                timeline_entries.append(
                    {
                        "date": stopped.isoformat(),
                        "end_date": None,
                        "kind": "supplement_stopped",
                        "domain": "supplements",
                        "title": row.name,
                        "note": None,
                        "source": "derived",
                        "ref": f"supplement_stopped:{row.id}",
                        "certainty": "audit_timestamp",
                    }
                )
        for row in all_products:
            added = row.created_at.date()
            if since <= added <= period_end:
                timeline_entries.append(
                    {
                        "date": added.isoformat(),
                        "end_date": None,
                        "kind": "skincare_product_added",
                        "domain": "skincare",
                        "title": row.name,
                        "note": row.active_ingredient,
                        "source": "derived",
                        "ref": f"skincare_added:{row.id}",
                        "certainty": "audit_timestamp",
                    }
                )
            removed = row.updated_at.date()
            if not row.active and since <= removed <= period_end:
                timeline_entries.append(
                    {
                        "date": removed.isoformat(),
                        "end_date": None,
                        "kind": "skincare_product_removed",
                        "domain": "skincare",
                        "title": row.name,
                        "note": None,
                        "source": "derived",
                        "ref": f"skincare_removed:{row.id}",
                        "certainty": "audit_timestamp",
                    }
                )
        genetics_by_day: dict[date_type, int] = {}
        for row in variants:
            imported = row.created_at.date()
            if since <= imported <= period_end:
                genetics_by_day[imported] = genetics_by_day.get(imported, 0) + 1
        for imported, count in genetics_by_day.items():
            timeline_entries.append(
                {
                    "date": imported.isoformat(),
                    "end_date": None,
                    "kind": "genetics_import",
                    "domain": "genetics",
                    "title": f"{count} curated variants imported",
                    "note": None,
                    "source": "derived",
                    "ref": f"genetics_import:{imported.isoformat()}",
                    "certainty": "audit_timestamp",
                }
            )

    # Signals — the day in his own words. Every other block is a measurement; this
    # is the only one that can say *why* a measurement moved: "кофе в 22" the night
    # before the HRV dip, a headache running through a week of bad sleep. Read
    # chronologically, because a narrative reads a period forward. Rows tapped
    # "не то" are excluded by the service — a misparse is not evidence, even
    # though it stays on the table as material for the key revision.
    from vitals.services import signals_service
    signals_enabled = module_on("signals")
    signal_limit = min(period_days * _SIGNALS_PER_DAY, 1000)
    raw_signals = (
        await signals_service.list_signals(
            session,
            start=since,
            end=period_end,
            limit=signal_limit + 1,
        )
        if signals_enabled
        else []
    )
    signals_truncated = len(raw_signals) > signal_limit
    # ``list_signals`` is newest first; the model reads the period forward.
    signals = list(raw_signals[:signal_limit])
    ctx["signals"] = [signal_row(row) for row in reversed(signals)] or None
    ctx["coverage"]["signals"] = _coverage(
        module="signals",
        enabled=signals_enabled,
        dates=[row.date for row in signals],
        window=window,
        truncated=signals_truncated,
        extra={"signal_limit": signal_limit},
    )

    from vitals.enums import MilestoneStatus
    from vitals.models.milestones import Milestone

    milestone_rows = list(
        (
            await session.execute(
                select(Milestone).order_by(
                    Milestone.deadline.is_(None), Milestone.deadline, Milestone.id
                )
            )
        ).scalars().all()
    )
    active_milestones = [
        row
        for row in milestone_rows
        if row.status == MilestoneStatus.ACTIVE.value
        and row.created_at.date() <= period_end
        and domain_visible(row.domain)
    ]

    latest_navy_bf = next(
        (
            row["body_fat_pct"]
            for row in reversed(measurement_history)
            if row["body_fat_pct"] is not None
        ),
        None,
    )
    latest_bia_bf = None
    if scan is not None:
        latest_bia_bf = next(
            (
                metric.value
                for metric in scan.metrics
                if metric.metric_key == "body_fat_pct" and metric.segment is None
            ),
            None,
        )

    milestone_context = []
    for row in active_milestones:
        current = None
        if row.domain == "weight" and row.target_value is not None and latest_weight:
            current = latest_weight.weight_kg
        elif row.domain == "body_comp" and row.target_value is not None:
            current = latest_bia_bf if latest_bia_bf is not None else latest_navy_bf
        milestone_context.append(
            {
                "id": row.id,
                "name": row.name,
                "domain": row.domain,
                "status": row.status,
                "target_value": row.target_value,
                "target_unit": row.target_unit,
                "deadline": row.deadline.isoformat() if row.deadline else None,
                "days_left": (
                    (row.deadline - period_end).days if row.deadline else None
                ),
                "current": round(current, 2) if current is not None else None,
                "remaining": (
                    round(current - row.target_value, 2)
                    if current is not None and row.target_value is not None
                    else None
                ),
                "note": row.note,
                "state_is_current_catalog": True,
            }
        )
    ctx["milestones"] = milestone_context
    ctx["coverage"]["milestones"] = _coverage(
        module="reports",
        enabled=True,
        window=window,
        rows=len(active_milestones),
        extra={"historical_state_reliable": False},
    )

    if timeline_enabled:
        for row in milestone_rows:
            if not domain_visible(row.domain):
                continue
            created = row.created_at.date()
            if since <= created <= period_end:
                timeline_entries.append(
                    {
                        "date": created.isoformat(),
                        "end_date": None,
                        "kind": "milestone_created",
                        "domain": row.domain,
                        "title": row.name,
                        "note": row.note,
                        "source": "derived",
                        "ref": f"milestone_created:{row.id}",
                        "certainty": "audit_timestamp",
                    }
                )
            resolved = row.updated_at.date()
            if row.status in {
                MilestoneStatus.ACHIEVED.value,
                MilestoneStatus.MISSED.value,
            } and since <= resolved <= period_end:
                timeline_entries.append(
                    {
                        "date": resolved.isoformat(),
                        "end_date": None,
                        "kind": f"milestone_{row.status}",
                        "domain": row.domain,
                        "title": row.name,
                        "note": row.note,
                        "source": "derived",
                        "ref": f"milestone_{row.status}:{row.id}",
                        "certainty": "audit_timestamp",
                    }
                )

    timeline_entries.sort(key=lambda item: (item["date"], item["ref"]))
    timeline_truncated = len(timeline_entries) > _TIMELINE_LIMIT
    timeline_entries = timeline_entries[-_TIMELINE_LIMIT:]
    ctx["timeline"] = timeline_entries or None
    ctx["coverage"]["timeline"] = _coverage(
        module="timeline",
        enabled=timeline_enabled,
        dates=[date_type.fromisoformat(item["date"]) for item in timeline_entries],
        window=window,
        truncated=timeline_truncated,
        extra={"event_limit": _TIMELINE_LIMIT},
    )

    # Day context — what each day was *made of*: office or remote, gym or not, how
    # heavy it turned out. Every other block says what the body did; this says what
    # the week asked of it, which is the whole difference between "HRV fell" and
    # "HRV fell across three heavy office days in a row". Read straight off the
    # model: the domain's service resolves one day at a time (the bot only ever
    # needs today), and a period read has no other caller.
    from vitals.models.signals import DayContext

    day_rows = list(
        (
            await session.execute(
                select(DayContext)
                .where(DayContext.date >= since, DayContext.date <= period_end)
                .order_by(DayContext.date)
            )
        ).scalars().all()
    ) if signals_enabled else []
    ctx["day_context"] = [
        _resolved_day_context(row) for row in day_rows
    ] or None
    ctx["coverage"]["day_context"] = _coverage(
        module="signals",
        enabled=signals_enabled,
        dates=[row.date for row in day_rows],
        window=window,
    )

    # Placeholder until the bedroom-air nights are summarised into the digest.
    ctx["environment"] = None

    # ── The join ──────────────────────────────────────────────────────────────
    # One row per day with every domain on it. The report kept reading as a stack
    # of separate domains because that is exactly what it was handed: recovery in
    # one shape, meals as an average, training as dated sessions, the day itself
    # somewhere else. Finding "the night after a heavy session" in that meant
    # joining five differently-shaped blocks by date in its head, and it simply
    # didn't. The join is arithmetic, so it belongs here, not in the prompt — what
    # arrives is the table a person would draw before looking for a pattern.
    if mode != REPORT_MODE_BRIEF:
        by_date_workouts: dict[str, list[dict[str, Any]]] = {}
        for workout in sessions:
            if workout["in_period"]:
                by_date_workouts.setdefault(workout["date"], []).append(workout)
        by_date_activities: dict[date_type, list[Any]] = {}
        for activity in garmin_activities:
            if period_start <= activity.date <= period_end:
                by_date_activities.setdefault(activity.date, []).append(activity)
        by_date_day = {r.date: r for r in day_rows}
        by_date_garmin = {r.date: r for r in garmin_rows}  # one row per date
        by_date_weight = {x.date: x for x in weights}
        period_measurements = list(
            (
                await session.execute(
                    select(BodyMeasurement)
                    .where(
                        BodyMeasurement.date >= period_start,
                        BodyMeasurement.date <= period_end,
                    )
                    .order_by(BodyMeasurement.date)
                )
            ).scalars().all()
        )
        by_date_measurement = {row.date: row for row in period_measurements}
        meals_by_date = all_meals_by_date
        signals_by_date: dict = {}
        for s in signals:
            signals_by_date.setdefault(s.date, []).append(s)
        skin_logs_by_date = {row.date: row for row in skin_logs}
        skin_obs_by_date: dict[date_type, list[Any]] = {}
        for row in skin_obs:
            skin_obs_by_date.setdefault(row.date, []).append(row)
        glp1_injections_by_date: dict[date_type, list[Any]] = {}
        for row in glp1_injections:
            glp1_injections_by_date.setdefault(row.date, []).append(row)
        glp1_effects_by_date: dict[date_type, list[Any]] = {}
        for row in glp1_effects:
            glp1_effects_by_date.setdefault(row.date, []).append(row)
        hrt_doses_by_date: dict[date_type, list[Any]] = {}
        for row in hrt_all_doses:
            hrt_doses_by_date.setdefault(row.date, []).append(row)
        hrt_effects_by_date: dict[date_type, list[Any]] = {}
        for row in hrt_effects:
            hrt_effects_by_date.setdefault(row.date, []).append(row)

        ctx["days"] = []
        for i in range(period_days):
            d = period_start + timedelta(days=i)
            g_row = by_date_garmin.get(d)
            meals = meals_by_date.get(d) or []
            day_row = by_date_day.get(d)
            workouts = by_date_workouts.get(d.isoformat(), [])
            activities = by_date_activities.get(d, [])
            measurement = by_date_measurement.get(d)
            nutrition_day = _nutrition_day_totals(meals)
            day: dict[str, Any] = {
                "date": d.isoformat(),
                "weekday": d.strftime("%a"),
                "weight_kg": (
                    by_date_weight[d].weight_kg if d in by_date_weight else None
                ),
                "calories": nutrition_day["calories"],
                "protein_g": nutrition_day["protein_g"],
                "fat_g": nutrition_day["fat_g"],
                "carbs_g": nutrition_day["carbs_g"],
                "meal_count": len(meals) or None,
                "last_meal_time": max(
                    (m.eaten_at for m in meals if m.eaten_at), default=None
                ).strftime("%H:%M") if any(m.eaten_at for m in meals) else None,
                "workout": (
                    {
                        "title": workouts[-1]["title"],
                        "volume_kg": workouts[-1]["volume_kg"],
                        "working_sets": workouts[-1]["working_sets"],
                        "duration_min": workouts[-1]["duration_min"],
                    }
                    if workouts
                    else None
                ),
                "hevy_workouts": [
                    {
                        "title": row["title"],
                        "program": row["program"],
                        "start_time": row["start_time"],
                        "volume_kg": row["volume_kg"],
                        "working_sets": row["working_sets"],
                        "duration_min": row["duration_min"],
                    }
                    for row in workouts
                ]
                or None,
                "garmin_activities": [
                    _garmin_activity_row(row) for row in activities
                ]
                or None,
                "day": (
                    _resolved_day_context(day_row)["resolved"] if day_row else None
                ),
                # Labels only — the full wording, with his own phrasing, stays in
                # the signals block. Here they exist so a signal is visible on the
                # same line as the metric it might explain.
                "signals": [
                    (
                        f"{signals_service.normalize_key(s.key)}@{s.at_time.strftime('%H:%M')}"
                        if s.at_time
                        else signals_service.normalize_key(s.key)
                    )
                    for s in signals_by_date.get(d, [])
                ] or None,
                "body_measurement": (
                    {
                        "neck_cm": measurement.neck_cm,
                        "waist_cm": measurement.waist_cm,
                        "hips_cm": measurement.hips_cm,
                        "body_fat_pct": measurement.body_fat_pct,
                        "lbm_kg": measurement.lbm_kg,
                    }
                    if measurement
                    else None
                ),
                "glp1_injections": [
                    {"drug": row.drug, "dose_mg": row.dose_mg, "site": row.site}
                    for row in glp1_injections_by_date.get(d, [])
                ]
                or None,
                "glp1_side_effects": [
                    {"type": row.effect_type, "severity": row.severity}
                    for row in glp1_effects_by_date.get(d, [])
                ]
                or None,
                "hrt_doses": [
                    {
                        "compound_key": row.compound_key,
                        "dose": row.dose,
                        "unit": row.unit,
                    }
                    for row in hrt_doses_by_date.get(d, [])
                ]
                or None,
                "hrt_side_effects": [
                    {"type": row.effect_type, "severity": row.severity}
                    for row in hrt_effects_by_date.get(d, [])
                ]
                or None,
                "skincare": (
                    _skincare_log_row(skin_logs_by_date[d], window)["applied"]
                    if d in skin_logs_by_date
                    else None
                ),
                "skin_observations": [
                    {
                        "inflammation": row.inflammation,
                        "pih": row.pih,
                        "zone": row.zone,
                    }
                    for row in skin_obs_by_date.get(d, [])
                ]
                or None,
            }
            if g_row is not None:
                garmin_day = _garmin_daily_row(g_row)
                day.update(
                    {
                        key: value
                        for key, value in garmin_day.items()
                        if key not in {"date", "source"} and value is not None
                    }
                )
            ctx["days"].append(
                {
                    key: value
                    for key, value in day.items()
                    if value is not None
                }
            )

    def training_source_stats(start: date_type, end: date_type) -> dict[str, Any]:
        period_activities = [
            row for row in garmin_activities if start <= row.date <= end
        ]
        period_hevy = [
            row
            for row in sessions
            if start.isoformat() <= row["date"] <= end.isoformat()
        ]
        return {
            "garmin": {
                "activities": len(period_activities),
                "duration_min": round(
                    sum(row.duration_seconds or 0 for row in period_activities) / 60,
                    1,
                )
                or None,
                "distance_km": round(
                    sum(row.distance_m or 0 for row in period_activities) / 1000,
                    2,
                )
                or None,
            },
            "hevy": {
                "sessions": len(period_hevy),
                "duration_min": sum(
                    row["duration_min"] or 0 for row in period_hevy
                )
                or None,
                "volume_per_session_kg": _mean(
                    row["volume_kg"] for row in period_hevy
                ),
                "volume_samples": sum(
                    row["volume_kg"] is not None for row in period_hevy
                ),
            },
        }

    ctx["training"] = {
        "deduplication": (
            "Garmin activities and Hevy sessions are source-separated; do not "
            "sum them as unique workouts without matching timestamps/types."
        ),
        "current": training_source_stats(period_start, period_end),
        "previous": training_source_stats(prev_start, prev_end),
    }

    # ── The comparison ────────────────────────────────────────────────────────
    # The reason the report was worth reading and wasn't: handed only current
    # values, a narrative can do nothing but read them back, and the dashboard
    # already did that better. Change is the part that isn't on any screen —
    # so the period and the period before it are reduced to the same shape and
    # handed over together. Weight was the one domain that already carried its
    # own history (MA + slope), and the one domain the digest ever said anything
    # about; this gives every other domain the same footing.
    if mode != REPORT_MODE_BRIEF:
        ctx["period_stats"] = {
            "current": _window_stats(
                period_start,
                period_end,
                garmin_rows,
                weights,
                all_meals,
                sessions,
                garmin_activities,
            ),
            "previous": _window_stats(
                prev_start,
                prev_end,
                garmin_rows,
                weights,
                all_meals,
                sessions,
                garmin_activities,
            ),
        }
    return ctx


def _mean(values) -> Optional[float]:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 1) if present else None


_GARMIN_NUMERIC_STATS = (
    ("sleep_score", "sleep_score", 1.0),
    ("sleep_hours", "sleep_seconds", 1 / 3600),
    ("deep_sleep_hours", "deep_sleep_seconds", 1 / 3600),
    ("light_sleep_hours", "light_sleep_seconds", 1 / 3600),
    ("rem_sleep_hours", "rem_sleep_seconds", 1 / 3600),
    ("awake_hours", "awake_seconds", 1 / 3600),
    ("awake_count", "awake_count", 1.0),
    ("restless_moments", "restless_moments", 1.0),
    ("avg_sleep_stress", "avg_sleep_stress", 1.0),
    ("avg_sleep_hr", "avg_sleep_hr", 1.0),
    ("respiration_lowest", "respiration_lowest", 1.0),
    ("respiration_highest", "respiration_highest", 1.0),
    ("sleep_need_hours", "sleep_need_actual", 1 / 60),
    ("resting_hr", "resting_hr", 1.0),
    ("avg_hr", "avg_hr", 1.0),
    ("max_hr", "max_hr", 1.0),
    ("min_hr", "min_hr", 1.0),
    ("hrv_avg", "hrv_avg", 1.0),
    ("avg_respiration", "avg_respiration", 1.0),
    ("spo2_avg", "spo2_avg", 1.0),
    ("spo2_lowest", "spo2_lowest", 1.0),
    ("avg_stress", "avg_stress", 1.0),
    ("max_stress", "max_stress", 1.0),
    ("body_battery_high", "body_battery_high", 1.0),
    ("body_battery_low", "body_battery_low", 1.0),
    ("body_battery_change", "body_battery_change", 1.0),
    ("steps", "steps", 1.0),
    ("floors_climbed", "floors_climbed", 1.0),
    ("active_calories", "active_calories", 1.0),
    ("bmr_calories", "bmr_calories", 1.0),
    ("total_calories", "total_calories", 1.0),
    ("intensity_minutes_moderate", "intensity_minutes_moderate", 1.0),
    ("intensity_minutes_vigorous", "intensity_minutes_vigorous", 1.0),
    ("training_readiness", "training_readiness", 1.0),
    ("vo2max", "vo2max", 1.0),
    ("acute_load", "acute_load", 1.0),
    ("load_ratio", "load_ratio", 1.0),
)

_GARMIN_STAT_COLS = tuple(attr for _key, attr, _scale in _GARMIN_NUMERIC_STATS)


def _window_stats(
    start, end, garmin_rows, weights, meals, sessions, garmin_activities=()
) -> dict:
    """One window reduced to the numbers worth comparing against another window.

    Symmetric on purpose: the model gets two identical shapes to subtract, rather
    than this period's rows plus an invitation to recall the last one — which is
    where a narrative starts supplying the half it doesn't have.

    Every count carries the denominator it should be read against — how many days
    actually carry numbers, not how many dates the window spans.
    """
    g = [r for r in garmin_rows if start <= r.date <= end]
    w = [x for x in weights if start <= x.date <= end]
    m = [x for x in meals if start <= x.date <= end]
    s = [x for x in sessions if start.isoformat() <= x["date"] <= end.isoformat()]
    a = [x for x in garmin_activities if start <= x.date <= end]
    meals_by_date: dict[date_type, list[Any]] = {}
    for meal in m:
        meals_by_date.setdefault(meal.date, []).append(meal)
    nutrition_days = [
        _nutrition_day_totals(day_meals) for day_meals in meals_by_date.values()
    ]
    logged_days = len(nutrition_days)
    days = (end - start).days + 1
    garmin_means = {
        key: _mean(
            getattr(row, attr) * scale
            for row in g
            if getattr(row, attr) is not None
        )
        for key, attr, scale in _GARMIN_NUMERIC_STATS
    }
    sample_counts = {
        key: sum(getattr(row, attr) is not None for row in g)
        for key, attr, _scale in _GARMIN_NUMERIC_STATS
    }
    sample_counts.update(
        {
            "weight_kg": len(w),
            "volume_per_session_kg": sum(
                row["volume_kg"] is not None for row in s
            ),
            "calories_per_day": sum(
                row["calories"] is not None for row in nutrition_days
            ),
            "protein_per_day_g": sum(
                row["protein_g"] is not None for row in nutrition_days
            ),
            "fat_per_day_g": sum(
                row["fat_g"] is not None for row in nutrition_days
            ),
            "carbs_per_day_g": sum(
                row["carbs_g"] is not None for row in nutrition_days
            ),
            "garmin_activity_duration_min": sum(
                row.duration_seconds is not None for row in a
            ),
            "garmin_activity_distance_km": sum(
                row.distance_m is not None for row in a
            ),
            "garmin_aerobic_effect": sum(
                row.training_effect_aerobic is not None for row in a
            ),
            "garmin_anaerobic_effect": sum(
                row.training_effect_anaerobic is not None for row in a
            ),
        }
    )
    latest_training_status = next(
        (row.training_status for row in reversed(g) if row.training_status), None
    )
    latest_hrv_status = next(
        (row.hrv_status for row in reversed(g) if row.hrv_status), None
    )
    out = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        **garmin_means,
        "training_status_latest": latest_training_status,
        "hrv_status_latest": latest_hrv_status,
        # Days with numbers on them, not rows. A row is written for a date before
        # the watch has scored anything for it, so counting rows reported seven
        # Garmin days behind means that were computed from six.
        "garmin_days": sum(
            1 for r in g if any(getattr(r, c) is not None for c in _GARMIN_STAT_COLS)
        ),
        "weight_kg": _mean(x.weight_kg for x in w),
        "workouts": len(s),
        "garmin_activities": len(a),
        "garmin_activity_duration_min": (
            round(sum(row.duration_seconds or 0 for row in a) / 60, 1) or None
        ),
        "garmin_activity_distance_km": (
            round(sum(row.distance_m or 0 for row in a) / 1000, 2) or None
        ),
        "garmin_aerobic_effect": _mean(
            row.training_effect_aerobic for row in a
        ),
        "garmin_anaerobic_effect": _mean(
            row.training_effect_anaerobic for row in a
        ),
        # Tonnage per session, not per window. Summed over a window it inherits the
        # window's arbitrariness exactly as the count does: one session against two
        # reads as "volume down 51%" when both sessions were the same size. Per
        # session the number is a fact about training; summed it is a fact about
        # where the window edge fell. The sum is kept, one rung below.
        "volume_per_session_kg": _mean(x["volume_kg"] for x in s),
        "training_volume_kg": sum(x["volume_kg"] or 0 for x in s) or None,
        "calories_per_day": _mean(row["calories"] for row in nutrition_days),
        "protein_per_day_g": _mean(row["protein_g"] for row in nutrition_days),
        "fat_per_day_g": _mean(row["fat_g"] for row in nutrition_days),
        "carbs_per_day_g": _mean(row["carbs_g"] for row in nutrition_days),
        "nutrition_days_logged": logged_days,
        "sample_counts": sample_counts,
    }
    return out


def signal_row(signal) -> dict:
    """One signal as the model sees it.

    Shared with the daily brief, which reads the same rows over a wider window —
    two shapes for the same block would mean two prompt descriptions to keep in
    step, and the one that drifted would drift silently.
    """
    from vitals.services import signals_service

    return {
        "date": signal.date.isoformat(),
        "kind": signal.kind,
        "key": signals_service.normalize_key(signal.key),
        "stored_key": (
            signal.key
            if signals_service.normalize_key(signal.key) != signal.key
            else None
        ),
        "value_num": signal.value_num,
        "unit": signal.unit,
        # The hour is what makes an exposure correlatable at all: "кофе в 22" and
        # "кофе в 9" are opposite facts wearing the same key.
        "at_time": signal.at_time.strftime("%H:%M") if signal.at_time else None,
        "note": signal.note,
    }


def build_prompt(context: dict, lang: str = "ru") -> str:
    """Render the structured context into the user prompt for the narrative."""
    import json

    if lang == "en":
        prefix = "Structured data snapshot for the period (JSON):\n\n"
        suffix = "\n\nWrite an analytical digest based on this data."
    else:
        prefix = "Структурный срез данных за период (JSON):\n\n"
        suffix = "\n\nНапиши аналитический разбор по этим данным."

    return (
        prefix
        # Context v2 carries substantially more signal; compact JSON keeps the
        # model's budget for analysis instead of indentation whitespace.
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        + suffix
    )


# ── Generation ────────────────────────────────────────────────────────────────
async def generate_digest(
    session: AsyncSession,
    llm: Any,
    *,
    on_date: Optional[date_type] = None,
    period_days: int = 7,
    source: str = Source.MANUAL.value,
) -> WeeklyDigest:
    """Assemble context, get the narrative from the LLM, and persist the digest.
    Raises whatever the LLM client raises (e.g. ``LLMNotConfigured``), or
    ``LLMEmptyResponse`` if the model comes back blank twice in a row. No commit."""
    from vitals.i18n import current_lang
    lang = current_lang.get()

    context = await assemble_context(session, on_date=on_date, period_days=period_days)
    prompt = build_prompt(context, lang=lang)
    system = DIGEST_SYSTEM_EN if lang == "en" else DIGEST_SYSTEM

    content = await llm.complete_text(prompt, system=system, max_tokens=_DIGEST_MAX_TOKENS)
    if not content:
        # Seen in prod: the upstream occasionally returns a blank message with no
        # error at all. One retry clears it in practice; if it's still empty,
        # fail loudly instead of silently persisting nothing.
        content = await llm.complete_text(prompt, system=system, max_tokens=_DIGEST_MAX_TOKENS)
    if not content:
        raise LLMEmptyResponse("LLM returned an empty digest narrative twice in a row")

    row = WeeklyDigest(
        date=on_date or today_local(),
        domain=DOMAIN,
        source=source,
        kind=DigestKind.WEEKLY.value,
        content=content,
        context_json=context,
        model=getattr(llm, "digest_model", None),
    )
    session.add(row)
    await session.flush()
    return row


async def latest_digest(
    session: AsyncSession, *, kind: str = DigestKind.WEEKLY.value
) -> Optional[WeeklyDigest]:
    """The most recent narrative of one kind. Defaults to the weekly digest, so a
    daily brief can never show up where a weekly one is expected."""
    result = await session.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.kind == kind)
        .order_by(WeeklyDigest.date.desc(), WeeklyDigest.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def list_digests(
    session: AsyncSession, *, limit: int = 20, kind: str = DigestKind.WEEKLY.value
) -> Sequence[WeeklyDigest]:
    result = await session.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.kind == kind)
        .order_by(WeeklyDigest.date.desc(), WeeklyDigest.id.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ── Scheduler job ─────────────────────────────────────────────────────────────
async def digest_job(session_factory, redis=None) -> None:
    """Weekly digest generation. No-ops when no OpenRouter key is configured so the
    scheduler never logs spurious failures."""
    from vitals.config import load_config
    from vitals.integrations.llm_client import LLMClient

    if not load_config().openrouter_api_key:
        return
    async with session_factory() as session:
        from vitals.services.language_service import get_language
        from vitals.i18n import current_lang
        lang = await get_language(session, redis)
        current_lang.set(lang)

        await generate_digest(session, LLMClient(), source=Source.SCHEDULER.value)
        await session.commit()
