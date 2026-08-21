"""The morning brief: the first thing the product ever says on its own.

Assembly is the composer's job (:mod:`compose`); this module owns the two things
around it — the model's single paragraph, and what happens when there is nothing
worth saying.

  * **The model can fail and the brief still arrives.** Any exception from the LLM
    (no key, no balance, upstream down, blank completion) drops the narrative
    block and nothing else.
  * **An empty day is silence, not a brief.** No fresh Garmin row and no recovery
    numbers → nothing is sent and a passive ``info`` alert shows the gap in the
    web instead.

The brief is stored in ``weekly_digests`` with ``kind='daily_brief'``, so
/reports shows it and MCP can read the history, without a second table.

Sending is deliberately *not* done here: :func:`generate_brief` builds and
persists, and the caller decides what to do with it — the job sends it under the
budget, the "Собрать бриф" button shows it in the web and sends nothing, the
"Отправить тестовое" button sends one off-budget copy. One function, three
callers, no flags.
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_type, timedelta
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import DigestKind, Domain, Severity, Source
from vitals.i18n import t
from vitals.models.milestones import DOMAIN as DIGEST_DOMAIN, WeeklyDigest
from vitals.services import alerts_service, digest_service
from vitals.services.proactive import compose, day_plan
from vitals.utils.timeutils import now_local, today_local

logger = logging.getLogger(__name__)

EMPTY_DAY_ALERT_KEY = "brief_empty_day"

# Short by design: the header already carries every number, so a long tail would
# only restate them. Enough headroom that a reasoning model's thinking tokens
# don't eat the visible answer (the bug that truncated the weekly digest in prod).
_BRIEF_MAX_TOKENS = 2000

# The window his personal norm is averaged over, and the fewest days in it that
# still make an average. Two weeks is long enough to absorb one bad night and
# short enough to follow a cut that is actually moving his resting HR.
_BASELINE_DAYS = 14
_BASELINE_MIN_DAYS = 4

# How long past its scheduled time the job keeps re-checking for last night to
# land before it gives up and sends what there is. The brief fires on the clock,
# but the night it is about ends whenever he wakes up — five hours covers a lie-in
# without letting a watch that never syncs hold the morning hostage forever.
BRIEF_WAIT_HOURS = 5

BRIEF_SYSTEM = """\
Ты пишешь короткий утренний разбор для владельца дашборда здоровья Vitals.

Пользователь — молодой парень, который разбирается в теме (рекомпозиция, силовые,
Garmin). Базовые понятия объяснять не надо.

РОЛЬ: напарник, который шарит. Не врач, не коуч. Прямо, без воды, без паники.

ЗАДАЧА: 2-3 предложения. Что сегодня с организмом и что с этим делать сегодня.
Шапка сообщения уже напечатала и числа, и что сегодня за день (`day`) — пересказ
любого из них тратит одно из трёх предложений на то, что он прочитал строкой выше.
Не «сегодня тренировочный день», а что это значит при сегодняшних числах.
Если данных мало — скажи это одним предложением и не тяни.

`garmin.baseline` — его собственные средние за 14 дней по тем же метрикам.
Это ЕДИНСТВЕННОЕ, с чем можно сравнивать сегодняшние числа. «Просел», «повышен»,
«упал», «пробило восстановление» — только про метрику, у которой baseline есть и
от которой сегодня реально отличается. Метрику без baseline не сравнивай ни с
чем: у неё нет нормы, и «просадка» по ней — выдуманный факт, а не оценка.
Если сегодня всё близко к норме — скажи это прямо одним предложением. Ровный
день — это результат, а не повод сочинить динамику.

Если `garmin.night_pending` = true — Garmin ещё не разметил прошедшую ночь (часы
на спящей руке в момент сборки). Сна, HRV, пульса покоя и Body Battery за сегодня
НЕТ, и вывести их из соседних блоков нельзя. Скажи одним предложением, что ночь
ещё не подгрузилась, и дальше говори только про то, что в данных есть. Про
восстановление, тяжесть тренировки и «организм не отдохнул» в этом случае не
рассуждай вообще — это ровно тот выдуманный факт, который здесь запрещён.

Блок `day` — что за день сегодня (удалёнка, зал). Если его `source` = "template",
это догадка шаблона недели, а не ответ пользователя: учитывай мягко, не утверждай
как факт.

`day.yesterday` — каким вчерашний день оказался по факту, включая нагрузку
(лёгкий/обычный/тяжёлый). Это уже не догадка, а его ответ, и это первое
объяснение сегодняшних цифр: тяжёлый вчера и просевший HRV сегодня — связка,
а не совпадение. Про сегодняшнюю нагрузку данных нет и быть не может — не
выдумывай её.

`nutrition` — записи только за вчерашний закрытый день (`date`, `totals`,
`entries_logged`). Текущего утра в JSON нет. Низкий итог при малом числе строк
может означать неполный лог, а не доказанный дефицит.

Блок `signals` — что пользователь сам писал про себя, за вчера и сегодня. kind:
state (состояние, 1-5), symptom (симптом, 1-5), exposure (сделал/принял, at_time —
время). Здесь и лежит объяснение утренних чисел: вчерашний вечерний exposure
(«кофе в 22») — первое, с чем стоит сверить просевший сон или HRV. Это его слова,
а не измерение: одна запись — повод связать, а не поставить диагноз.

ОГРАНИЧЕНИЯ (нарушение = баг):
- Опирайся ТОЛЬКО на JSON. Ничего не выдумывай, новых чисел не вводи.
- Никаких заголовков, списков и разметки — обычный текст, его читают в мессенджере.
- Язык: русский.\
"""


# ── Assembly ──────────────────────────────────────────────────────────────────
async def build_context(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> dict:
    """Today's cross-domain snapshot, minus the protocol, plus the day context.

    The day context is the difference between "спал плохо — отдохни" and advice
    that knows there is a gym session and a heavy workday ahead, so it goes into
    the model's JSON as well as onto the header line.
    """
    ctx = await digest_service.assemble_context(
        session,
        on_date=on_date,
        period_days=1,
        mode=digest_service.REPORT_MODE_BRIEF,
    )
    ctx = compose.strip_protocol(ctx)
    today = on_date or today_local()
    # One-day window would cut the signals in half: "кофе в 22" is *yesterday's*
    # row and this morning's HRV is the thing it explains. Widened here rather
    # than in ``assemble_context`` because nothing else in the brief wants two
    # days — the header is strictly about today.
    #
    # Deliberately after ``strip_protocol``: that keeps the *stored* protocol out of
    # Telegram, and a signal is not stored protocol — it is a sentence he typed
    # into this very chat. Stripping it here would hide his own words from him.
    ctx["signals"] = await _signals_since_yesterday(session, today)
    ctx["nutrition"] = (
        await _yesterday_nutrition(session, today)
        if _nutrition_enabled(ctx)
        else None
    )
    # The one thing the brief could never do: compare. Handed a single day of
    # absolute numbers and asked what they mean, the model supplied the missing
    # half itself — "просадка SpO2 и повышенный пульс покоя" on a resting HR that
    # had not moved a beat. His own fortnight is what those words have to be true
    # against, so it goes in beside the numbers rather than being left implied.
    if ctx.get("garmin"):
        ctx["garmin"]["baseline"] = await _baseline(session, today)
    answers, answered = await day_plan.resolve(session, today)
    # Yesterday's answers, and only the ones he actually gave. How heavy a day was
    # is answered in the evening about the day just spent, so at 11:00 the newest
    # real load in the lake is yesterday's — and it is the first thing this
    # morning's HRV should be read against. The template's guess is filtered out:
    # a guess about a day that is already over explains nothing.
    yesterday_answers, yesterday_answered = await day_plan.resolve(
        session, today - timedelta(days=1)
    )
    ctx["day"] = {
        "answers": answers,
        # Which of them are his words rather than the template's guess. Stored as
        # a sorted list because this dict is persisted as JSON — and it is what
        # the brief's buttons read to re-ask only the questions still open.
        "answered": sorted(answered),
        # His answer or the template's guess — the model is told which, so it can
        # hedge on a guess instead of asserting it.
        "source": Source.MANUAL.value if answered else Source.TEMPLATE.value,
        "yesterday": {k: yesterday_answers[k] for k in sorted(yesterday_answered)} or None,
    }
    return ctx


async def _baseline(session: AsyncSession, on_date: date_type) -> Optional[dict]:
    """His own mean per metric over the days *before* today.

    Strictly before: today's number is the thing being judged, and folding it into
    the yardstick pulls the yardstick toward it — worst exactly on the outlier
    mornings the comparison exists for. ``None`` until there is enough history for
    a mean to mean anything; a "norm" off two nights is noise wearing the word.
    """
    from vitals.services import garmin_service

    rows = [
        row
        for row in await garmin_service.list_daily(session, limit=_BASELINE_DAYS + 1)
        if 0 < (on_date - row.date).days <= _BASELINE_DAYS
    ]
    baseline = {}
    for key in compose.BASELINE_KEYS:
        values = [v for v in (getattr(row, key, None) for row in rows) if v is not None]
        if len(values) >= _BASELINE_MIN_DAYS:
            baseline[key] = round(sum(values) / len(values), 1)
    return baseline or None


async def _signals_since_yesterday(session: AsyncSession, on_date: date_type) -> Optional[list]:
    """Today's signals plus yesterday's — the evening before is where exposures
    live, and the metric they explain is this morning's."""
    from vitals.services import signals_service

    rows = await signals_service.list_signals(
        session, start=on_date - timedelta(days=1), end=on_date
    )
    return [digest_service.signal_row(s) for s in reversed(rows)] or None


_NUTRITION_TOTAL_FIELDS = ("calories", "protein_g", "fat_g", "carbs_g")


def _nutrition_enabled(ctx: dict) -> bool:
    """Is the food log a module that is even on? Read off the coverage block so
    the answer is the same one ``assemble_context`` already settled."""
    return bool(((ctx.get("coverage") or {}).get("nutrition") or {}).get("enabled"))


async def _meals_logged_today(session: AsyncSession, on_date: date_type) -> bool:
    """Did anything land in the food log today — nothing about *how much*.

    The nutrition block is deliberately about yesterday, so the only thing left
    that can still say "this morning is alive" is the bare existence of a row.
    Counting the calories here would put the partial total back into the morning
    through the side door.
    """
    from vitals.services import nutrition_service

    return bool(await nutrition_service.list_meals_for_date(session, on_date))


async def _yesterday_nutrition(
    session: AsyncSession, on_date: date_type
) -> Optional[dict]:
    """Return yesterday's logged nutrition without today's partial total."""
    from vitals.config import load_config
    from vitals.services import nutrition_service

    yesterday = on_date - timedelta(days=1)
    meals = await nutrition_service.list_meals_for_date(session, yesterday)
    if not meals:
        return None

    totals = {}
    for field in _NUTRITION_TOTAL_FIELDS:
        values = [
            getattr(meal, field)
            for meal in meals
            if getattr(meal, field) is not None
        ]
        totals[field] = round(sum(values), 1) if values else None
    return {
        "date": yesterday.isoformat(),
        "calendar_day_closed": True,
        "entries_logged": len(meals),
        "totals": totals,
        "goals": nutrition_service.get_goals(load_config()),
    }


def build_prompt(ctx: dict) -> str:
    return (
        f"Данные для утреннего брифа на {ctx.get('date')} "
        "(JSON; не переноси значения между датами):\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2)
        + "\n\nНапиши утренний разбор: 2-3 предложения."
    )


async def narrative(llm: Any, ctx: dict) -> str:
    """The model's one block. Returns "" on any failure — never raises."""
    try:
        return await llm.complete_text(
            build_prompt(ctx),
            model=getattr(llm, "brief_model", None),
            system=BRIEF_SYSTEM,
            max_tokens=_BRIEF_MAX_TOKENS,
        )
    except Exception:
        logger.warning("brief narrative unavailable; sending the header alone", exc_info=True)
        return ""


async def generate_brief(
    session: AsyncSession,
    llm: Any,
    *,
    on_date: Optional[date_type] = None,
    source: str = Source.MANUAL.value,
) -> Optional[WeeklyDigest]:
    """Build the brief and store it. ``None`` = empty day, nothing built."""
    on_date = on_date or today_local()
    ctx = await build_context(session, on_date=on_date)
    logged_today = (
        await _meals_logged_today(session, on_date) if _nutrition_enabled(ctx) else False
    )
    if compose.is_empty_day(ctx, on_date=on_date, nutrition_logged_today=logged_today):
        logger.info("no brief for %s: no sleep and nothing new", on_date)
        return None
    # Unconditional, not a flag the caller may forget: whether to *wait* for the
    # night is the job's call, but nobody — job, web button, MCP — gets to build a
    # brief on numbers taken mid-night.
    if compose.night_pending(ctx, on_date=on_date):
        logger.info("brief for %s: last night is not scored, recovery dropped", on_date)
        ctx = compose.drop_unscored_night(ctx)

    blocks = compose.header_blocks(ctx)
    day = day_plan.day_block(ctx.get("day"))
    if day is not None:
        blocks.append(day)
    tail = await narrative(llm, ctx)
    if tail:
        blocks.append(compose.Block(compose.KIND_NARRATIVE, tail, 90))

    row = WeeklyDigest(
        date=on_date,
        domain=DIGEST_DOMAIN,
        source=source,
        kind=DigestKind.DAILY_BRIEF.value,
        content=compose.render(blocks),
        context_json=ctx,
        model=getattr(llm, "brief_model", None) if tail else None,
    )
    session.add(row)
    await session.flush()
    return row


def dedupe_key(on_date: date_type) -> str:
    """One brief per day, enforced in the delivery journal rather than hoped for."""
    return f"brief:{on_date.isoformat()}"


def last_attempt_hour(brief_hour: int) -> int:
    """The final hour of the retry window. Clamped to 23 so a late brief time can
    never schedule a fire past midnight — that one would be about the wrong day."""
    return min(brief_hour + BRIEF_WAIT_HOURS, 23)


async def night_scored(session: AsyncSession, on_date: date_type) -> bool:
    """Has Garmin closed last night yet? ``False`` = worth waiting for.

    No row for the day at all counts as *scored*: that is a watch that has not
    synced, or is not used at all, and holding the brief for it would make an
    optional device a hard dependency of the one proactive feature.
    """
    from vitals.services import garmin_service

    row = await garmin_service.get_daily(session, on_date)
    if row is None:
        return True
    return any(getattr(row, key, None) is not None for key in compose.NIGHT_SCORED_KEYS)


# ── Scheduler job ─────────────────────────────────────────────────────────────
async def brief_job(session_factory, redis=None) -> None:
    """The 11:00 brief — fired hourly across the wait window, sent once.

    Pulls Garmin first, on its own, instead of hoping the poll schedule happened
    to run this morning — last night's sleep is the whole point of the message.
    A Garmin failure is not a reason to stay quiet: the brief goes out with
    whatever is in the lake.

    11:00 is a guess at when he is up, and one morning it was wrong: the brief
    went out while he was still asleep, read the middle of the night as a wrecked
    recovery and advised skipping the gym over it — then stored that, where the
    weekly digest reads it back as what the morning actually was. So
    the job no longer assumes: with today's row present but the night un-scored it
    sends nothing and lets the next hourly fire look again, up to
    ``BRIEF_WAIT_HOURS``. In practice the brief now lands within the hour of
    waking rather than on the hour of the clock. The last fire gives up and sends
    what there is, minus the numbers the night never produced.
    """
    from vitals.integrations.llm_client import LLMClient
    from vitals.services import garmin_service
    from vitals.services.language_service import get_language
    from vitals.i18n import current_lang
    from vitals.services.proactive import channels, delivery, inbound, prefs

    today = today_local()
    # Before the Garmin pull, not after: on a normal day the brief left at 11:00
    # and every later fire in the window is a no-op that must not cost a login.
    async with session_factory() as session:
        if await delivery.already_sent(session, dedupe_key(today)):
            return
        brief_hour, _ = prefs.hhmm((await prefs.get_prefs(session))["brief_time"])
    out_of_patience = now_local().hour >= last_attempt_hour(brief_hour)

    try:
        await garmin_service.sync_job(session_factory, redis)
    except Exception:
        logger.warning("garmin sync before the brief failed; using stored data", exc_info=True)

    notifier = channels.build_notifier()
    async with session_factory() as session:
        current_lang.set(await get_language(session, redis))

        # Second pass at yesterday's unparsed messages, in its own transaction and
        # behind its own guard: a recovered row belongs in the lake before the
        # brief reads it, and a model that is still down must not cost the brief.
        try:
            recovered = await inbound.reparse_pending(session)
            await session.commit()
            if recovered:
                logger.info("re-parsed %d stored message(s) before the brief", len(recovered))
        except Exception:
            await session.rollback()
            logger.warning("re-parse sweep before the brief failed", exc_info=True)

        # Nothing is built, so nothing is stored and no model call is spent: an
        # un-scored night is not an empty day either, so it raises no alert — the
        # next fire is an hour away and this is the normal state of a lie-in.
        if not out_of_patience and not await night_scored(session, today):
            logger.info("brief for %s postponed: last night is not scored yet", today)
            return

        row = await generate_brief(session, LLMClient(), source=Source.SCHEDULER.value)
        if row is None:
            await alerts_service.raise_alert(
                session,
                domain=Domain.SYSTEM.value,
                severity=Severity.INFO.value,
                message=t("alert.brief_empty_day"),
                alert_key=EMPTY_DAY_ALERT_KEY,
            )
            await session.commit()
            return

        # Nothing answered for today → the header shows the template's guess and
        # the buttons are how it gets corrected in one tap.
        buttons = day_plan.buttons_from_context((row.context_json or {}).get("day"), today)
        # The hint rides on the *sent* message, not on the stored brief: /reports
        # shows the same content with no keyboard under it, and a line pointing at
        # buttons that aren't there is worse than no line at all.
        text = f"{row.content}\n\n{day_plan.HINT_FIX}" if buttons else row.content

        await delivery.send(
            session,
            notifier,
            text=text,
            category=delivery.CATEGORY_BRIEF,
            dedupe_key=dedupe_key(today),
            buttons=buttons,
        )
        await alerts_service.resolve_by_key(session, alert_key=EMPTY_DAY_ALERT_KEY)
        await session.commit()
