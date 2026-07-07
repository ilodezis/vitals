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
from vitals.integrations.llm_client import LLMEmptyResponse
from vitals.models.milestones import DOMAIN, WeeklyDigest
from vitals.utils.timeutils import today_local

logger = logging.getLogger(__name__)

DIGEST_SYSTEM = """\
Ты пишешь периодический разбор для пользователя дашборда здоровья Vitals.

Пользователь — молодой парень, который разбирается в теме (рекомпозиция, GLP-1, силовые, Garmin). Ему не нужны объяснения базовых понятий. Ему нужен взгляд сверху: что реально происходит, куда всё идёт, и на что обратить внимание.

РОЛЬ: ты — напарник, который шарит. Не врач, не коуч, не ментор. Говоришь прямо, без воды, без паники, без покровительственного тона. Если данных мало — так и скажи, без натягивания выводов.

ВХОДНЫЕ ДАННЫЕ (JSON):
Любой домен может быть null (нет данных). Не выдумывай того, чего нет.
- report_meta: дата отчёта, period_days (дней в срезе)
- user_profile: возраст, рост, программа, цели
- weight: последний замер, скользящее среднее (ma7_kg) + дата последней MA-точки (ma7_date), тренд (kg_per_week), noise_markers
  ВАЖНО: если активен noise_marker, то ma7_date — это последний чистый день ДО начала шума, а не сегодня. Не сравнивай latest_kg и ma7_kg как если бы они были одновременными. Разрыв между ними объясняется давностью MA, а не текущим шумом.
- glp1: препарат, доза, plateau
- body_comp: последний BIA/InBody-скан (date, device, metrics: % жира, скелетно-мышечная масса, безжировая масса, висцеральный жир, фазовый угол, балл). Может быть null (скана нет). Это отдельный источник состава тела (BIA); сосуществует с оценкой по замерам (Navy) в weight — не смешивай и не суммируй их.
- garmin: sleep_score, resting_hr, hrv_avg, body_battery_high, training_readiness, total_days_logged
- hevy: тренировок за период, дата последней
- labs: маркеры вне нормы (marker, value, flag, date)
- nutrition: avg калории/белок в день, days_with_logs, цели
- milestones: активные цели с прогрессом и дедлайнами

ИНВАРИАНТЫ (нарушение = баг):
1. period_days < 7 → не называй «неделей», пиши «за N дней». Не экстраполируй.
2. labs.date > 14 дней от report_date → блок не существует, не упоминай.
3. garmin.total_days_logged ≤ 3 → не оценивай сон/восстановление, просто скажи что данных пока мало.
4. Опирайся ТОЛЬКО на данные из JSON. Ничего не выдумывай.
5. Если период пересекается с noise_markers — обязательно подсвети, что тренд веса может быть искажён (причина из reason).
   - direction="up"      → масштаб ЗАВЫШЕН шумом (загрузка креатином, скачок натрия, задержка воды). Реальный темп потери жира ЛУЧШЕ, чем показывает тренд; после конца маркера жди откат вверх на скользящем среднем + замедление видимого снижения — это нормально и НЕ означает потерю темпа.
   - direction="down"    → масштаб ЗАНИЖЕН (обезвоживание, болезнь). Реальная ситуация ХУЖЕ чем числа.
   - direction=null/"neutral" → направление неизвестно, просто отметь что данные зашумлены.

ПИТАНИЕ: пользователь часто забивает на трекинг. Если days_with_logs мало или калории нереалистично низкие — это пропущенный лог, а не голодовка. Не паникуй, просто отметь что данных мало.

ЧТО ПИСАТЬ:
Не пересказывай цифры — пользователь видит их на дашборде. Твоя задача — интерпретация и связи между доменами:
- Как сон/HRV соотносятся с нагрузкой и восстановлением?
- Тренд веса реальный или искажён шумом?
- Успевает ли к дедлайну цели? Что тормозит?
- Есть ли что-то, что стоит скорректировать?

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
Any domain can be null (no data). Don't invent what isn't there.
- report_meta: report date, period_days
- user_profile: age, height, program, goals
- weight: latest reading, moving average (ma7_kg) + date of last MA point (ma7_date), trend (kg_per_week), noise_markers
  IMPORTANT: if a noise_marker is active, ma7_date is the last clean day BEFORE the noise started — not today. Do NOT compare latest_kg and ma7_kg as if they are simultaneous. Any gap between them reflects how stale the MA is, not current noise.
- glp1: drug, dose, plateau flag
- body_comp: latest BIA/InBody scan (date, device, metrics: body-fat %, skeletal muscle mass, lean body mass, visceral fat, phase angle, score). Can be null (no scan taken). This is a separate BIA body-composition source; it coexists with the tape/Navy estimate in weight — don't conflate or sum them.
- garmin: sleep_score, resting_hr, hrv_avg, body_battery_high, training_readiness, total_days_logged
- hevy: workouts in period, last workout date
- labs: out-of-range markers (marker, value, flag, date)
- nutrition: avg calories/protein per day, days_with_logs, targets
- milestones: active goals with progress and deadlines

INVARIANTS (breaking = bug):
1. period_days < 7 → don't call it a "week", say "these N days". Don't extrapolate.
2. labs.date > 14 days from report_date → block doesn't exist, don't mention.
3. garmin.total_days_logged ≤ 3 → don't evaluate sleep/recovery, just say not enough data yet.
4. Use ONLY data from the JSON. Don't invent anything.
5. If period overlaps noise_markers — must flag that weight trend may be distorted (reason from marker).
   - direction="up"      → scale INFLATED by noise (creatine loading, sodium spike, water retention). Real fat-loss pace is BETTER than the trend shows; after the marker ends expect the moving average to bounce up and visible loss to slow — that is normal and does NOT mean progress has stalled.
   - direction="down"    → scale DEFLATED (dehydration, illness). Real situation is WORSE than numbers.
   - direction=null/"neutral" → direction unknown, just note data is noisy.

NUTRITION: user often skips tracking. Low days_with_logs or unrealistically low calories = missed log, not starvation. Don't panic, just note data is sparse.

WHAT TO WRITE:
Don't restate numbers — user sees them on the dashboard. Your job is interpretation and cross-domain connections:
- How does sleep/HRV relate to training load and recovery?
- Is the weight trend real or noise-distorted?
- On track for goal deadlines? What's the bottleneck?
- Anything worth adjusting?

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
                # direction: which way the scale is biased vs real fat trend.
                # up   = scale inflated (creatine/sodium) → real loss is better
                # down = scale deflated (dehydration)     → real situation worse
                # null = unknown / treat as neutral
                "direction": m.direction,
            })

    last_ma = series["trend_ma"][-1] if series["trend_ma"] else None
    ctx["weight"] = {
        "latest_kg": weights[-1].weight_kg if weights else None,
        "ma7_kg": last_ma["weight_kg"] if last_ma else None,
        # Date the MA7 was last calculated. During a noise period ALL measurements
        # inside it are excluded from the MA, so ma7_date will be the last clean
        # day BEFORE the noise started — potentially weeks ago. Do NOT compare
        # latest_kg directly to ma7_kg as if they describe the same moment.
        "ma7_date": last_ma["date"] if last_ma else None,
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

    from vitals.services import body_scan_service
    from vitals.services.analytics.body_metrics import (
        HEADLINE_KEYS,
        METRIC_REGISTRY,
        lbm_from_scan,
    )

    # Body composition (BIA/InBody). Latest scan only — the headline metrics that
    # matter for recomp. Separate source from the Navy tape estimate in `weight`;
    # coexist, never summed. Null when the owner has taken no scan.
    scan = await body_scan_service.latest_scan(session)
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
        ctx["body_comp"] = {
            "date": scan.date.isoformat(),
            "device": scan.device,
            "metrics": comp_metrics,
        }
    else:
        ctx["body_comp"] = None

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
    Raises whatever the LLM client raises (e.g. ``LLMNotConfigured``), or
    ``LLMEmptyResponse`` if the model comes back blank twice in a row. No commit."""
    from vitals.i18n import current_lang
    lang = current_lang.get()

    context = await assemble_context(session, on_date=on_date, period_days=period_days)
    prompt = build_prompt(context, lang=lang)
    system = DIGEST_SYSTEM_EN if lang == "en" else DIGEST_SYSTEM

    content = await llm.complete_text(prompt, system=system, max_tokens=3000)
    if not content:
        # Seen in prod: the upstream occasionally returns a blank message with no
        # error at all. One retry clears it in practice; if it's still empty,
        # fail loudly instead of silently persisting nothing.
        content = await llm.complete_text(prompt, system=system, max_tokens=3000)
    if not content:
        raise LLMEmptyResponse("LLM returned an empty digest narrative twice in a row")

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
