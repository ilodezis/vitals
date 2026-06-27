"""Weekly AI digest service (module 10) — the product core.

Every 7 days we assemble a **structured cross-domain snapshot** (weight trend,
GLP-1 phase/plateau, Garmin recovery, Hevy training, out-of-range labs, active
goals) and ask the LLM for an *analytical narrative* — the interpretation of how
these relate, not a restatement of the numbers. The structured context is stored
alongside the text (re-inspect / re-run later).

The LLM client is injected so the generator is unit-tested without network or a
key; the scheduled job no-ops when no key is configured.
"""
from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Source
from vitals.models.milestones import DOMAIN, WeeklyDigest
from vitals.utils.timeutils import today_local

logger = logging.getLogger(__name__)

DIGEST_SYSTEM = """\
Ты — аналитическое ядро персонального дашборда здоровья Vitals. Раз в неделю (или по запросу) ты пишешь пользователю развернутый, глубокий аналитический разбор периода (дайджест).

Ты — навигатор и поддержка решений, а не надзиратель и не врач. Твоя цель — находить неочевидные закономерности, перекрестные связи между доменами и формулировать рабочие гипотезы. Ты не ставишь диагнозы, не назначаешь препараты и не меняешь дозировки. Финальное решение всегда за пользователем.

ВХОДНЫЕ ДАННЫЕ:
В user-сообщении приходит структурный JSON-срез. Любой домен может быть null — это значит, что данных по нему за период нет.
- report_meta: report_date (YYYY-MM-DD), period_days (дней в срезе). Основа для всех временны́х рассуждений.
- user_profile: возраст, пол, рост, текущая программа, цели.
- weight: последнее значение, 7-дневное среднее (ma7_kg), недельный тренд (kg_per_week; отрицательный = снижение), и список noise_markers (периоды шума: креатин, отеки, соль, болезнь с датами start, end и причиной reason).
- glp1: текущий препарат, доза и флаг plateau (признак остановки прогресса веса на текущей дозе).
- garmin: сон (sleep_score, 0–100), пульс покоя (resting_hr), ночной HRV (hrv_avg, мс), Body Battery, готовность к нагрузке (training_readiness), авто-подсказка (advice), а также total_days_logged (всего дней с логами в базе).
- hevy: количество силовых сессий за период и дата последней.
- labs: маркеры анализов вне нормы (название, значение, флаг low/high/critical, дата сдачи date YYYY-MM-DD).
- nutrition: средние калории и белок в день (avg_calories_per_day, avg_protein_per_day_g), число дней с логами (days_with_logs), целевые ориентиры (protein_target_g, calories_min, calories_max).
- milestones: активные цели и прогресс (цель, текущее, сколько осталось, дедлайн).

ЖЁСТКИЕ ИНВАРИАНТЫ ВАЛИДАЦИИ (НЕ СЛЕДОВАТЬ ИМ = БАГ):

1. ВРЕМЕННОЙ ЦЕНЗ: Если period_days < 7 — никогда не называй срез «неделей». Пиши строго: «за эти N дней». Не экстраполируй темпы, если срез короткий.
2. ТУХЛЫЕ АНАЛИЗЫ: Если дата labs.date старше 14 дней от даты отчета (report_meta.report_date) — полностью игнорируй этот блок. Его не существует. Не упоминай маркеры, не делай выводов, не проси пересдать.
3. СЛЕПОЙ GARMIN: Если garmin.total_days_logged ≤ 3 — запрещено оценивать восстановление и сон. Пиши строго: «данных с датчиков пока мало (N дней), картина восстановления сложится позже».
4. АКСИОМА ИСТОЧНИКА: Опирайся ТОЛЬКО на данные из JSON. Не выдумывай сторонние дозы, цели, лекарства или исторические факты, которых нет в текущем срезе.
5. МАРКЕРЫ ШУМА: Если период пересекается с noise_markers, ты ОБЯЗАН подсветить их. Объясни пользователю, что текущие колебания веса или тренд ma7 могут быть ложными (ложное плато или ложный скачок) из-за задержки воды (причина из reason).

🚨 ФИЛЬТР ЗДРАВОГО СМЫСЛА ПО ПИТАНИЮ (NUTRITION):
Пользователь может забыть залогировать еду, забить на трекинг в отдельные дни или внести только чашку кофе. 
Включай критическое мышление: если ты видишь, что крупный мужчина (например, весом за 100+ кг) за день съел 200 ккал, 0 ккал или показания критически, нереалистично занижены — НЕ НУЖНО делать из этого панические выводы о «критическом голодании» или «жестком дефиците». Трактуй это как «пользователь просто пропустил лог или забыл записать еду». Относись к этому спокойно: если дней с реальными логами мало (nutrition.days_with_logs ≤ 2) или данные явно неполные, просто коротко отметь: «данных по питанию мало или трекинг был неполным, поэтому детальный анализ калоража за рамками этого отчета». Не строй ложных теорий на пустых логах.

МЕТОДОЛОГИЯ АНАЛИЗА (ИЩИ ПАТТЕРНЫ):
Не пересказывай цифры из JSON списком — пользователь видит их на дашборде. Твоя задача — копать в глубину и искать перекрестные связи (Cross-Domain Patterns):
- Связывай Garmin и Hevy: Как просадка сна или HRV повлияла на частоту тренировок? Нет ли признаков накопленного недовосстановления на фоне высокого объема нагрузок?
- Связывай Питание, Вес и GLP-1: Соответствует ли тренд веса (kg_per_week) реальному (не искаженному пропусками) дефициту калорий? Если включен флаг plateau, коррелирует ли это с плато по дозировкам или задержкой воды из-за noise_markers? 
- Связывай с Целями: Сопоставляй текущий тренд веса с дедлайнами из milestones. Успевает ли пользователь к дедлайнам? Что является главным драйвером прогресса, а что — скрытым тормозом?

ФОРМАТ И СТИЛЬ ОТВЕТА:
- Язык: Строго русский.
- Тон: Уверенный, знающий, поддерживающий напарник (peer-to-peer). Без менторского тона, паники и медицинской душноты.
- Объем и структура: Дай себе пространство для глубокого разбора. Не зажимай себя в рамки короткой сводки — пиши развернуто, подробно и аргументированно.
- Разметка (Markdown разрешен и поощряется): Активно используй структуру GitHub Markdown. Разбивай отчет на логические разделы с помощью заголовков (##, ###), выделяй ключевые инсайты **жирным шрифтом**, используй списки (* или -) для перечисления гипотез или тактических идей, а важные выводы или предупреждения оформляй в блоки цитат (>). Текст должен быть максимально scannable, визуально приятным и глубоким по содержанию.
"""

DIGEST_SYSTEM_EN = """\
You are the analytical core of the Vitals personal health dashboard. Once a week (or on request), you write a detailed, deep analytical digest of the period (digest) for the user.

You are a decision navigator and support partner, not a warden or doctor. Your goal is to find non-obvious patterns, cross-domain correlations, and formulate working hypotheses. You do not diagnose, prescribe, or change dosages. The final decision is always up to the user.

INPUT DATA:
The user message contains a structured JSON snapshot. Any domain can be null, meaning there is no data for it in the period.
- report_meta: report_date (YYYY-MM-DD), period_days (number of days in the snapshot). The basis for all temporal reasoning.
- user_profile: age, sex, height, current program, goals.
- weight: latest value, 7-day moving average (ma7_kg), weekly trend (kg_per_week; negative = loss), and a list of noise_markers (water retention, creatine, salt, illness with start/end dates and reason).
- glp1: current drug, dose, and plateau flag (stalled weight progress on current dose).
- garmin: sleep (sleep_score, 0–100), resting HR (resting_hr), overnight HRV (hrv_avg, ms), Body Battery, training readiness, auto-advice, and total_days_logged.
- hevy: strength workouts count for the period and the date of the last one.
- labs: out-of-range biomarkers (marker, value, flag low/high/critical, date YYYY-MM-DD).
- nutrition: average calories and protein per day (avg_calories_per_day, avg_protein_per_day_g), number of days logged (days_with_logs), target targets (protein_target_g, calories_min, calories_max).
- milestones: active goals and progress (goal, current, remaining, deadline).

STRICT VALIDATION INVARIANTS (NOT FOLLOWING THEM IS A BUG):
1. TEMPORAL BOUNDS: If period_days < 7 — never call the digest a "week". Write strictly: "for these N days". Do not extrapolate trends for short periods.
2. STALE LABS: If labs.date is older than 14 days from report_meta.report_date — ignore this block entirely. It does not exist. Do not mention markers, do not make conclusions, do not ask to retest.
3. BLIND GARMIN: If garmin.total_days_logged ≤ 3 — do not evaluate recovery or sleep. Write strictly: "there is currently not enough sensor data (N days), the recovery picture will form later".
4. SOURCE TRUTH: Rely ONLY on the data in the JSON. Do not invent external doses, goals, drugs, or historical facts not present in the current snapshot.
5. NOISE MARKERS: If the period overlaps with noise_markers, you MUST highlight them. Explain to the user that current weight fluctuations or ma7 trend might be artificial (fake plateau or fake spike) due to water retention (reason).

🚨 NUTRITION COMMON-SENSE FILTER:
The user might forget to log food, skip tracking on some days, or log only a cup of coffee.
Use critical thinking: if you see that a large adult ate 200 kcal, 0 kcal, or the numbers are unrealistically low — DO NOT panic and conclude "extreme starvation" or "severe deficit". Interpret this as "the user simply skipped a log or forgot to record food". Treat it calmly: if days with logs are few (nutrition.days_with_logs ≤ 2) or the data is clearly incomplete, simply note: "nutrition data is scarce or tracking was incomplete, so a detailed caloric analysis is outside the scope of this report". Do not build false theories on empty logs.

ANALYTICAL METHODOLOGY (FIND PATTERNS):
Do not list the numbers from JSON as a bullet list — the user sees them on the dashboard. Your task is to dig deep and find Cross-Domain Patterns:
- Link Garmin and Hevy: How did sleep or HRV drops affect training frequency? Are there signs of accumulated under-recovery against high volume?
- Link Nutrition, Weight, and GLP-1: Does the weight trend (kg_per_week) align with the actual (non-missing) caloric deficit? If the plateau flag is on, does it correlate with dose plateau or water retention from noise_markers?
- Link to Goals: Match the current weight trend with deadlines from milestones. Is the user on track? What is the main driver of progress, and what is the hidden constraint?

FORMAT AND STYLE OF RESPONSE:
- Language: Strictly English.
- Tone: Confident, knowledgeable, supportive peer (peer-to-peer). No patronizing tone, panic, or medical jargon.
- Length and structure: Give yourself space for a deep analysis. Do not limit yourself to a short summary — write in-depth, detailed, and reasoned.
- Formatting (Markdown is allowed and encouraged): Actively use GitHub Markdown structure. Break the report into logical sections with headers (##, ###), highlight key insights in **bold**, use lists (* or -) for hypotheses or tactical ideas, and format important takeaways or warnings in blockquotes (>). The text should be highly scannable, visually pleasing, and deep in content.
"""



# ── Context assembly ──────────────────────────────────────────────────────────
async def assemble_context(
    session: AsyncSession,
    *,
    on_date: Optional[date_type] = None,
    period_days: int = 7,
) -> dict:
    """Pull a structured cross-domain snapshot. Each domain is read through its own
    service (lazy import to avoid cycles); empty domains come back as nulls/empties
    rather than raising, so a digest works even before every module has data."""
    today = on_date or today_local()

    from vitals.config import load_config
    cfg = load_config()

    ctx: dict[str, Any] = {
        "date": today.isoformat(),  # Keep for backward compatibility
        "report_meta": {
            "report_date": today.isoformat(),
            "period_days": period_days,
        },
        "user_profile": {
            "age": cfg.user_age,
            "sex": cfg.sex,
            "height_cm": cfg.height_cm,
            "program": cfg.user_program,
            "goals": cfg.user_goals,
        },
    }

    from vitals.services import weight_service
    from datetime import timedelta

    series = await weight_service.chart_series(session)
    weights = await weight_service.list_active_weights(session)

    period_start = today - timedelta(days=period_days - 1)
    markers = await weight_service.list_noise_markers(session)
    matching_markers = []
    for m in markers:
        if m.start_date <= today and (m.end_date is None or m.end_date >= period_start):
            matching_markers.append({
                "start": m.start_date.isoformat(),
                "end": m.end_date.isoformat() if m.end_date else None,
                "reason": m.reason,
            })

    ctx["weight"] = {
        "latest_kg": weights[-1].weight_kg if weights else None,
        "ma7_kg": series["trend_ma"][-1]["weight_kg"] if series["trend_ma"] else None,
        "trend_kg_per_week": series["trend"]["slope_per_week"] if series.get("trend") else None,
        "noise_markers": matching_markers,
    }

    from vitals.services import glp1_service

    phase = await glp1_service.active_dose_phase(session, on_date=today)
    ctx["glp1"] = {
        "drug": phase.drug if phase else None,
        "dose_mg": phase.dose_mg if phase else None,
        "plateau": await glp1_service.evaluate_plateau(session, on_date=today),
    }

    from vitals.services import garmin_service

    g = await garmin_service.latest_daily(session, before_or_on=today)
    ctx["garmin"] = (
        {
            "date": g.date.isoformat(),
            "sleep_score": g.sleep_score,
            "resting_hr": g.resting_hr,
            "hrv_avg": g.hrv_avg,
            "body_battery_high": g.body_battery_high,
            "training_readiness": g.training_readiness,
            "advice": garmin_service.recovery_advice(g),
            "total_days_logged": await garmin_service.daily_count(session),
        }
        if g
        else None
    )

    from vitals.services import hevy_service
    from datetime import timedelta
    since = today - timedelta(days=period_days - 1)

    last_workout = await hevy_service.latest_workout_date(session)
    ctx["hevy"] = {
        "total_workouts": await hevy_service.workout_count(session, since=since),
        "last_workout": last_workout.isoformat() if last_workout else None,
    }

    from vitals.services import labs_service

    latest_labs = await labs_service.latest_per_marker(session)
    ctx["labs"] = {
        "out_of_range": [
            {
                "marker": r.marker,
                "value": r.value,
                "unit": r.unit,
                "flag": r.flag,
                "date": r.date.isoformat(),
            }
            for r in latest_labs
            if labs_service.is_out_of_range(r.flag) and (today - r.date).days <= 14
        ]
    }

    from vitals.services import nutrition_service

    nutrition_meals = await nutrition_service.list_meals(session, start=since, end=today)
    if nutrition_meals:
        per_day_meals: dict = {}
        for m in nutrition_meals:
            per_day_meals.setdefault(m.date, []).append(m)
        days_with_logs = len(per_day_meals)
        total_cal = sum(m.calories or 0 for m in nutrition_meals)
        total_prot = sum(m.protein_g or 0 for m in nutrition_meals)
        goals = nutrition_service.get_goals(cfg)
        ctx["nutrition"] = {
            "avg_calories_per_day": round(total_cal / days_with_logs, 1),
            "avg_protein_per_day_g": round(total_prot / days_with_logs, 1),
            "days_with_logs": days_with_logs,
            "total_meals": len(nutrition_meals),
            "goals": goals,
        }
    else:
        ctx["nutrition"] = None

    from vitals.services import milestones_service

    ctx["milestones"] = await milestones_service.dashboard_cards(session)
    return ctx


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
        + json.dumps(context, ensure_ascii=False, indent=2)
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
    Raises whatever the LLM client raises (e.g. ``LLMNotConfigured``). No commit."""
    from vitals.i18n import current_lang
    lang = current_lang.get()

    context = await assemble_context(session, on_date=on_date, period_days=period_days)
    prompt = build_prompt(context, lang=lang)
    system = DIGEST_SYSTEM_EN if lang == "en" else DIGEST_SYSTEM
    content = await llm.complete_text(prompt, system=system, max_tokens=3000)

    row = WeeklyDigest(
        date=on_date or today_local(),
        domain=DOMAIN,
        source=source,
        content=content,
        context_json=context,
        model=getattr(llm, "digest_model", None),
    )
    session.add(row)
    await session.flush()
    return row


async def latest_digest(session: AsyncSession) -> Optional[WeeklyDigest]:
    result = await session.execute(
        select(WeeklyDigest).order_by(WeeklyDigest.date.desc(), WeeklyDigest.id.desc()).limit(1)
    )
    return result.scalars().first()


async def list_digests(session: AsyncSession, *, limit: int = 20) -> Sequence[WeeklyDigest]:
    result = await session.execute(
        select(WeeklyDigest).order_by(WeeklyDigest.date.desc(), WeeklyDigest.id.desc()).limit(limit)
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
