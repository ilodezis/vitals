"""What comes back from the channel: button taps, replies, and free text.

Three inbound shapes, deliberately three code paths:

  * **a tap** (``callback_query``) — the "не то" undo, the day-context answers
    the evening block will ask for, and the skincare checklist's ticks. Stateless: the button carries
    everything needed in its payload, so a tap works days later.
  * **a question** — either a reply to one of our messages or a plain «почему hrv
    просел?». Answered from the message replied to — or, when nothing was
    replied to, the last few messages we sent — *plus* the context the last brief
    was built on, and nothing else. This is still not a second chat with the
    data: deep questions belong in Claude.ai over MCP, which has 69 tools and a
    better model. Here the model sees the tail of the conversation, the day's
    numbers, and is told to invent nothing.
  * **anything else typed** — free text into ``signals`` (raw first, always),
    followed by an echo of what was understood plus one "не то" button.

Idempotency: Telegram retries a webhook until it gets a 200, so the same
``update_id`` can arrive several times. Every update is keyed into
``raw_payloads`` as ``tg:<update_id>``, and an update whose key is already there
is dropped — which reuses the data-lake table that has to hold the message
anyway, instead of a second bookkeeping store that could disagree with it.

``handle_text`` takes text, not a Telegram update (C8): adding voice notes later
is one transcription step *in front of* this pipeline, not a rewrite of it.
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_type, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import DigestKind, Domain, SignalKind, Source
from vitals.integrations.llm_client import LLMClient
from vitals.models.raw_payload import RawPayload
from vitals.services import digest_service, signals_service
from vitals.services.proactive import day_plan, delivery, prefs, skincare
from vitals.services.proactive.channels import Notifier
from vitals.services.raw_payload_service import upsert_raw_payload
from vitals.utils.timeutils import now_local

logger = logging.getLogger(__name__)

DOMAIN = Domain.SIGNALS.value
SOURCE = Source.TELEGRAM.value

# Button payloads (Telegram caps callback_data at 64 bytes, both fit comfortably).
CB_MISPARSE = "mis:"   # mis:<batch_id>
CB_CONTEXT = "ctx:"    # ctx:<iso date>:<key>:<value>
CB_SKINCARE = skincare.CB_PREFIX  # sk:<iso date>:<slot>:<product id | all>

# The answer to any slash command, ``/start`` included. One reply for all of them
# on purpose: this bot has no command surface — everything it does is either
# initiated by it or written in plain words.
COMMAND_REPLY = (
    "Утром приношу разбор, вечером — итог дня.\n\n"
    "Пиши обычным текстом, как есть: «голова раскалывается», «кофе в 22», "
    "«спать хочу пиздец» — запишу и учту в разборах.\n\n"
    "Вес, уколы и еду вноси в приложении — здесь их нет."
)

# How many already-used keys the parser is shown. Reusing an existing key is the
# only thing keeping the open registry from drifting into 60 near-synonyms before
# the registry can be consolidated; the cap keeps the prompt small.
_KNOWN_KEYS_LIMIT = 40

_PARSER_SYSTEM = """\
Ты разбираешь короткие сообщения владельца дашборда здоровья на отдельные факты.

Верни JSON вида {"signals": [...]}. Каждый элемент:
- kind: "state" | "symptom" | "exposure"
    state — как человеку и как ему шёл день; имеет интенсивность. Это и самочувствие
      («энергии ноль», «спать хочу»), и то, каким день был по факту:
      «нихуя не делал, весь день за компом» → sedentary,
      «мотался по городу весь день» → on_feet,
      «работал допоздна» → long_work_day, «завал на работе» → workload_high,
      «нервный день» → stress. Про день отвечают именно так — не теряй это.
    symptom — то, что случилось и имеет тяжесть («голова раскалывается», «тошнит»)
    exposure — то, что человек принял или сделал разово («кофе в 22», «выпил два бокала»)
- key: короткий английский слаг (sleepiness, headache, caffeine_late, alcohol,
  sedentary, on_feet, long_work_day, workload_high, stress)
- value_num: для exposure — количество; для state/symptom — сила по шкале ниже.
  Шкалу выводи ИЗ САМИХ СЛОВ, а не из темы. 3 — это «мешает», а не «я не знаю»:
    1 — вскользь, почти незаметно («чуть-чуть клонит в сон»)
    2 — заметно, но не мешает; смягчение («устал немного», «че-то хочу спать»,
        «какая-то апатия» — «какой-то», «немного», «слегка», «чуть» = 2)
    3 — голая констатация без усилителя и без смягчения («болит голова»,
        «поругались», «устал»)
    4 — усилитель («очень», «сильно», «весь день», «еле», «жутко»)
    5 — предел: мат, гипербола, «не могу», «чуть не» («пиздец устал»,
        «раскалывается», «чуть не расплакался», «вырубает»)
  Несколько усилителей подряд не поднимают выше 5 и не опускают ниже 1.
- unit: единица для exposure ("mg", "ml", "min"), иначе null
- at_time: "HH:MM", если время названо или однозначно следует из фразы, иначе null
- note: кусок исходной фразы, из которого взят этот факт

Одно сообщение может дать несколько фактов — верни их все.
События дня (болезнь, поездка, смена протокола) сюда НЕ идут — для них есть
отдельный раздел, пропускай их.
Если фактов нет (болтовня, вопрос, благодарность) — верни {"signals": []}.
Ничего не выдумывай: чего нет в сообщении, того нет в ответе.\
"""

_REPLY_SYSTEM = """\
Ты отвечаешь на вопрос владельца дашборда здоровья.
Перед тобой могут быть последние сообщения самого бота (по порядку, последнее —
внизу) и JSON с данными последнего разбора дня. Короткий вопрос без пояснений
почти всегда про то, что бот только что написал — сначала ищи ответ там, и
только потом в JSON. Отвечай по-русски, коротко (2-4 предложения); числа бери
только из этих двух источников.
Если ответа в них нет — так и скажи. Никаких выдуманных чисел.\
"""

_REPLY_MAX_TOKENS = 800
# How far back the "what did you just say" context reaches. Three covers an echo
# followed by a nudge that landed in between; more starts pulling in yesterday.
_CONTEXT_MESSAGES = 3
_NO_LLM_REPLY = "Сейчас не отвечу — модель недоступна. Загляни в приложение."
# The day's numbers as JSON, capped: the brief's context grows a field per module
# and the prompt is paid for by the token.
_DAY_FACTS_LIMIT = 4000

# A question typed on its own has to be told apart from a fact, and asking the
# model which it is costs a call on every message. So: a question mark, or an
# opening question word. Matched as a *word*, never as a prefix — «что-то тошнит»
# is a symptom, not a question about «что».
_QUESTION_WORDS = frozenset({"почему", "что", "чем", "как", "сколько", "когда", "зачем"})

# Before this hour a message still belongs to the day that is ending: «кофе в 2»
# written at 00:30 is about the evening just spent, and filing it under the fresh
# calendar date buries it in tomorrow's brief while tonight's never sees it.
_DAY_ROLLS_OVER_AT = 4


def looks_like_question(text: str) -> bool:
    """Is this asked *of* the bot rather than told to it?"""
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    words = stripped.lower().replace(",", " ").split()
    if not words:
        return False
    return words[0] in _QUESTION_WORDS or words[:2] == ["стоит", "ли"]


def conversation_day(now: Optional[datetime] = None) -> date_type:
    """Which day a message written *now* is talking about."""
    moment = now or now_local()
    return (
        moment.date() - timedelta(days=1)
        if moment.hour < _DAY_ROLLS_OVER_AT
        else moment.date()
    )


# ── Telegram update shape (the only place that knows it) ──────────────────────
def chat_id_of(update: dict) -> Optional[str]:
    """The chat an update came from, whichever shape it arrived in."""
    for holder in (
        update.get("message"),
        update.get("edited_message"),
        (update.get("callback_query") or {}).get("message"),
    ):
        chat = (holder or {}).get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return None


async def _already_handled(session: AsyncSession, external_id: str) -> bool:
    result = await session.execute(
        select(RawPayload.id).where(
            RawPayload.domain == DOMAIN,
            RawPayload.source == SOURCE,
            RawPayload.external_id == external_id,
        )
    )
    return result.scalars().first() is not None


async def handle_update(
    session: AsyncSession,
    update: dict,
    *,
    notifier: Optional[Notifier],
    parse: Optional[signals_service.Parser] = None,
) -> None:
    """Entry point for one Telegram update. Safe to call twice with the same one."""
    update_id = update.get("update_id")
    external_id = f"tg:{update_id}" if update_id is not None else None
    if external_id and await _already_handled(session, external_id):
        logger.info("ignoring repeated update %s", external_id)
        return

    # The emergency switch stops the expensive and the outgoing half — the
    # model call and every reply — but not the ears. A message written while the
    # module is off still lands in the lake: "выключено" must not read as
    # "потерял", and the re-parse sweep picks the text up whenever it comes back
    # on. What it cannot do is answer, which is enforced in ``delivery.send`` too.
    enabled = await prefs.bot_enabled(session)

    callback = update.get("callback_query")
    if callback:
        # A tap is an answer to a question this bot asked; with the module off
        # there is nothing asking, so it is dropped rather than stored.
        if not enabled:
            logger.info("ignoring tap: the signals module is switched off")
            return
        await _handle_callback(session, callback, notifier=notifier, external_id=external_id)
        return

    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    if not text:
        # Photos, stickers, voice notes: nothing to capture yet (voice arrives as
        # a transcription step in front of handle_text, not as a branch here).
        return

    if not enabled:
        # A slash command is addressed to the bot, not a fact about the day —
        # same call the enabled path makes. Left unstamped it would sit in
        # the queue until the module came back on and then cost a model call to
        # learn that «/start» holds no signals.
        await signals_service.store_raw_text(
            session,
            text=text,
            external_id=external_id,
            source=SOURCE,
            processed=text.startswith("/"),
        )
        logger.info("stored inbound text unparsed: the signals module is switched off")
        return

    await handle_text(
        session,
        text,
        notifier=notifier,
        external_id=external_id,
        message_id=message.get("message_id"),
        reply_to_message_id=(message.get("reply_to_message") or {}).get("message_id"),
        parse=parse,
    )


# ── Taps ──────────────────────────────────────────────────────────────────────
async def _handle_callback(
    session: AsyncSession,
    callback: dict,
    *,
    notifier: Optional[Notifier],
    external_id: Optional[str],
) -> None:
    data = str(callback.get("data") or "")
    callback_id = str(callback.get("id") or "")

    # The tap itself is data too — which button, when — so it lands in the lake
    # like everything else, and doubles as this update's idempotency record.
    if external_id:
        await upsert_raw_payload(
            session, domain=DOMAIN, source=SOURCE, external_id=external_id, payload=callback
        )

    toast = ""
    answered: Optional[tuple[date_type, str]] = None
    ticked: Optional[tuple[date_type, str]] = None
    if data.startswith(CB_MISPARSE):
        batch_id = data[len(CB_MISPARSE):]
        changed = await signals_service.mark_misparse(session, batch_id)
        # The rows stay, flagged: they are the material the key registry gets
        # built from — real mistakes, not remembered ones.
        toast = "Убрал из графиков" if changed else "Уже убрано"
    elif data.startswith(CB_CONTEXT):
        answered = await _apply_context(session, data)
        toast = "Записал" if answered is not None else ""
    elif data.startswith(CB_SKINCARE):
        applied = await skincare.apply_tap(session, data)
        if applied is not None:
            ticked = applied[:2]
            toast = applied[2]

    if notifier is not None and callback_id:
        # Acknowledged first: Telegram spins on the button until this lands, and
        # the redraw below is a second round-trip the spinner shouldn't wait for.
        try:
            await notifier.answer_callback(callback_id, toast)
        except Exception:
            logger.warning("could not acknowledge tap %s", callback_id, exc_info=True)

    if notifier is not None and answered is not None:
        await _redraw(session, callback, *answered, notifier=notifier)
    message_id = (callback.get("message") or {}).get("message_id")
    if notifier is not None and ticked is not None and message_id:
        await skincare.redraw(session, notifier, str(message_id), *ticked)


async def _redraw(
    session: AsyncSession,
    callback: dict,
    on_date: date_type,
    key: str,
    *,
    notifier: Notifier,
) -> None:
    """The message that asked now says what was answered.

    Without it a tap leaves nothing but a grey toast: the line still reads out the
    template's guess and the same keyboard still sits under it, which looks like
    "не нажалось" and gets tapped again. Rebuilt from the day, not from the tap —
    two taps in a row must not each drop the other's answer.
    """
    message = callback.get("message") or {}
    message_id = message.get("message_id")
    text = message.get("text") or ""
    if not message_id or not text:
        return

    answers, answered = await day_plan.resolve(session, on_date)
    buttons = day_plan.exception_buttons(
        answers, on_date, answered, day_plan.questions_for(key)
    )
    try:
        await notifier.edit(
            str(message_id),
            day_plan.redraw(text, answers, has_buttons=bool(buttons)),
            buttons=buttons or None,
        )
    except Exception:
        # The answer is already stored; a channel that refused the edit (the
        # message is old, or nothing actually changed) is worth a log, not a
        # failed update Telegram would then retry for hours.
        logger.warning("could not redraw message %s", message_id, exc_info=True)


async def _apply_context(
    session: AsyncSession, data: str
) -> Optional[tuple[date_type, str]]:
    """``ctx:<iso date>:<key>:<value>`` → merge one answer into that day's context.

    Returns the day answered and the question answered (``None`` if the payload
    was rejected). The redraw needs both: the day to rebuild the answers from,
    and the question to know which of the two keyboards this tap came off —
    the evening sends a recap one and a plan one, and rebuilding the wrong set
    would hang tomorrow's buttons under today's question.

    The date rides in the payload rather than being "today": the evening block
    asks about *tomorrow*, and a tap that lands after midnight must still answer
    the day it was asked about. Merging (and keeping the template's guess beside
    the answer) is ``day_plan``'s job — here we only decode the payload.

    The decoded pair is checked against the question registry: Telegram keeps old
    keyboards tappable forever, so a button sent before a question was renamed or
    dropped would otherwise write a key nothing reads back.
    """
    try:
        _, iso_date, key, value = data.split(":", 3)
        on_date = date_type.fromisoformat(iso_date)
    except ValueError:
        logger.warning("unparseable context payload: %s", data)
        return None

    question = day_plan.QUESTIONS_BY_KEY.get(key)
    answer = day_plan.decode(value)
    if question is None or answer not in question.labels:
        logger.warning("context payload outside the question registry: %s", data)
        return None

    await day_plan.record_answer(session, on_date, key, answer)
    return on_date, key


# ── Text ──────────────────────────────────────────────────────────────────────
async def handle_text(
    session: AsyncSession,
    text: str,
    *,
    notifier: Optional[Notifier],
    external_id: Optional[str] = None,
    message_id: Optional[Any] = None,
    reply_to_message_id: Optional[Any] = None,
    parse: Optional[signals_service.Parser] = None,
    on_date: Optional[date_type] = None,
) -> None:
    """The channel-agnostic entry point (C8): already text, whatever produced it."""
    # A slash command is addressed to the bot, not a fact about the day. Caught
    # before anything else because ``/start`` is the very first thing anyone sends
    # a new bot: capturing it costs a model call and answers "разобрать не смог",
    # which reads as broken on the first ever message.
    if text.startswith("/"):
        # Stored anyway, and marked done on the spot: the raw row is what a
        # webhook retry trips over, and without it Telegram's second delivery of
        # the same ``/start`` gets a second identical answer. ``processed`` keeps
        # the re-parse sweep from feeding «/start» to the parser later.
        await signals_service.store_raw_text(
            session, text=text, external_id=external_id, source=SOURCE, processed=True
        )
        await delivery.send(
            session,
            notifier,
            text=COMMAND_REPLY,
            category=delivery.CATEGORY_REPLY,
            reply_to=str(message_id) if message_id else None,
        )
        return

    answered = (
        await delivery.find_sent(session, str(reply_to_message_id))
        if reply_to_message_id is not None
        else None
    )
    # The evening block *asks* «как день?», so a reply to it is an answer, not a
    # question — «норм, а ты как?» falls through to capture, question mark and
    # all. Everything else that replies to us, and anything typed as a question
    # on its own, is asked *of* us: «почему hrv просел?» answered with «фактов
    # для графиков тут не нашёл» is the single most broken-looking thing the bot
    # could say.
    to_evening = answered is not None and answered.category == delivery.CATEGORY_EVENING
    if not to_evening and (answered is not None or looks_like_question(text)):
        # A question is data too, and this is also what stops a webhook retry
        # from paying for a second model call on the same question. Marked done
        # in the same breath: a question is not a message waiting to be parsed
        # into signals, so the re-parse sweep must not pick it up and turn «почему
        # пульс низкий?» into a symptom row.
        await signals_service.store_raw_text(
            session, text=text, external_id=external_id, source=SOURCE, processed=True
        )
        await _answer_reply(session, text, answered, notifier=notifier, message_id=message_id)
        return

    rows = await signals_service.ingest_text(
        session,
        text=text,
        parse=parse or make_signal_parser(await known_keys(session)),
        external_id=external_id,
        on_date=on_date or conversation_day(),
        source=SOURCE,
    )

    if not rows:
        # Not an error, and it must not read like one. The evening block asks «как
        # день?» and «весь день за компом» is a perfectly good answer that simply
        # holds no state, symptom or exposure — the schema has nowhere to put it.
        # The text is saved either way and the re-parse sweep sees it again, so
        # the honest thing to say is that it is written down.
        await delivery.send(
            session,
            notifier,
            text="Записал. Фактов для графиков тут не нашёл — если что-то важное, скажи прямо.",
            category=delivery.CATEGORY_ECHO,
            reply_to=str(message_id) if message_id else None,
        )
        return

    await delivery.send(
        session,
        notifier,
        text=render_echo(rows),
        category=delivery.CATEGORY_ECHO,
        buttons=[("не то", f"{CB_MISPARSE}{rows[0].batch_id}")],
        reply_to=str(message_id) if message_id else None,
    )


async def _answer_reply(
    session: AsyncSession,
    question: str,
    answered,
    *,
    notifier: Optional[Notifier],
    message_id: Optional[Any],
) -> None:
    """``answered`` is the message being replied to; for a question typed on its
    own the last few things we said stand in for it."""
    if answered is not None:
        context = (answered.payload or {}).get("text") or ""
    else:
        context = "\n\n".join(
            text
            for row in await delivery.recent_sent(session, limit=_CONTEXT_MESSAGES)
            if (text := (row.payload or {}).get("text"))
        )
    try:
        text = await answer_reply(question, context, await _day_facts(session))
    except Exception:
        logger.warning("could not answer a reply", exc_info=True)
        text = _NO_LLM_REPLY
    await delivery.send(
        session,
        notifier,
        text=text or _NO_LLM_REPLY,
        category=delivery.CATEGORY_REPLY,
        reply_to=str(message_id) if message_id else None,
    )


async def _day_facts(session: AsyncSession) -> str:
    """The numbers behind the latest brief, as JSON — or ``""`` if there is none.

    Without it the model answers «почему hrv просел?» from the prose of one
    message and nothing else: it cannot see the HRV it is being asked about, so
    the honest answer is always "в тексте этого нет". The brief already assembled
    the day and stored the context it was built from, so this reads *that* rather
    than assembling a second, subtly different picture of the same day.
    """
    digest = await digest_service.latest_digest(session, kind=DigestKind.DAILY_BRIEF.value)
    if digest is None or not digest.context_json:
        return ""
    try:
        return json.dumps(digest.context_json, ensure_ascii=False, default=str)[:_DAY_FACTS_LIMIT]
    except (TypeError, ValueError):
        logger.warning("brief context is not serialisable; answering without it", exc_info=True)
        return ""


def _fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def render_echo(rows) -> str:
    """What was understood: his own words, the key it was filed under, the value.

    The key used to be left out on purpose — `голова раскалывается → headache 4/5`
    reads like the bot answering in a language he did not use. In practice the
    reverse was worse. The number alone is not checkable: «спать хочу → 3/5» and
    «спать хочу → 3/5» look identical whether the second one went under
    ``sleepiness`` or quietly opened a 61st synonym for it, and the key registry
    the open-vocabulary parser is supposed to converge on drifts unwatched until
    ``/signals`` is opened on purpose. The key is the half that says *where* the
    row landed, which is exactly what an echo is for.
    """
    lines = []
    for row in rows:
        bits = [signals_service.normalize_key(row.key)]
        if row.value_num is not None:
            number = _fmt_num(row.value_num)
            if row.unit:
                bits.append(f"{number} {row.unit}")
            elif row.kind in (SignalKind.STATE.value, SignalKind.SYMPTOM.value):
                bits.append(f"{number}/5")
            else:
                bits.append(number)
        if row.at_time is not None:
            bits.append(f"в {row.at_time.strftime('%H:%M')}")
        parsed = " ".join(bits)
        # No note (the parser found a fact but quoted nothing) leaves the key to
        # name the row on its own — no «→» with nothing on its left.
        lines.append(f"• {row.note} → {parsed}" if row.note else f"• {parsed}")
    return "Записал:\n" + "\n".join(lines)


# ── LLM ───────────────────────────────────────────────────────────────────────
async def known_keys(session: AsyncSession) -> list[str]:
    """The vocabulary the parser is reminded of, most-used first."""
    stats = await signals_service.key_frequency(session)
    return [stat.key for stat in stats][:_KNOWN_KEYS_LIMIT]


async def reparse_pending(session: AsyncSession) -> list:
    """Give the messages the parser choked on one more go (R3).

    Lives next to the parser because that is what it needs; called from the
    morning-brief job rather than from a schedule of its own, so a recovered row
    is in the lake *before* the brief reads it.
    """
    return await signals_service.reparse_unparsed(
        session, parse=make_signal_parser(await known_keys(session))
    )


def make_signal_parser(known: Optional[list[str]] = None) -> signals_service.Parser:
    """Build the parser handed to ``ingest_text``.

    A factory, not a bare function, because the prompt carries the keys already in
    use — the parser is only as consistent as the vocabulary it is reminded of.
    Injected as a parameter everywhere downstream, so tests never touch a network.
    """
    vocabulary = ", ".join(known or []) or "пока пусто"
    system = (
        f"{_PARSER_SYSTEM}\n\n"
        f"Уже использованные ключи — переиспользуй подходящий, новый заводи только "
        f"если ни один не подходит: {vocabulary}"
    )

    async def _parse(text: str) -> list[dict]:
        result = await LLMClient().extract_json(text, system=system)
        items = result.get("signals")
        return items if isinstance(items, list) else []

    return _parse


async def answer_reply(question: str, context: str, facts: str = "") -> str:
    """Answer using the message replied to and the day the brief was built on.

    Either half can be empty — a question typed on its own has no message behind
    it, and a day with no brief yet has no numbers — so the prompt only carries
    what exists rather than a labelled hole the model might fill in.
    """
    parts = []
    if context:
        parts.append(f"Последние сообщения бота:\n{context}")
    if facts:
        parts.append(f"Данные последнего разбора дня (JSON):\n{facts}")
    parts.append(f"Вопрос:\n{question}")
    return await LLMClient().complete_text(
        "\n\n".join(parts), system=_REPLY_SYSTEM, max_tokens=_REPLY_MAX_TOKENS
    )
