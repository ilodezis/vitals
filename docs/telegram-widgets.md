# Telegram widgets (experimental)

Two bot messages can be sent as widgets: small HTML cards that live inside the
message bubble instead of plain text. Off by default. When Telegram refuses a
widget, the existing plain message goes out instead.

Enable with `VITALS_TELEGRAM_WIDGETS=true`. If you pass `allowed_updates` to
`setWebhook`, include `widget_query` so the skincare card's taps arrive. Widgets
work only in the private chat with the bot.

## The two cards

- **Morning brief.** The header numbers become a card: sleep, HRV, resting HR and
  Body Battery as tiles, each with a bar that shows today against his own norm
  (the tick). A tile turns amber when today is notably worse than the norm and
  accent-coloured when notably better. Within 5% of the norm it stays neutral. Below
  the tiles: last night's bedroom air, yesterday's activity, weight with its trend
  and a 14-day sparkline, and today's plan line. The model's paragraph is the
  caption under the card. The day-plan buttons stay ordinary inline buttons under
  the message.
- **Skincare checklist.** One bubble that ticks in place and follows ticks made in
  the app, instead of a message redrawn after every tick with one button per
  product.

## How it works

The HTML is a static template in `vitals/services/proactive/widgets/templates/`,
fixed when the message is sent. Only the *chat state* (a JSON string under 1 KB)
changes, through `editMessageWidgetData`. The widget has no network access.

- **The brief card sends no requests.** It is sent without `allow_queries`, so
  it has no path back to the bot at all. Everything it shows (values, norms,
  colours, bar positions) is computed in Python from the stored brief. The
  template only paints it. A tap on a day-plan button goes through the existing
  callback path. Because a card has no text to edit, the bot redraws the card's
  state and its keyboard instead (`editMessageReplyMarkup`).
- **The skincare card** asks the bot through `TelegramWidget.request(data)`: at
  most 64 bytes, delivered as a `widget_query` update. The bot answers with the
  card's new state and writes the same state to the message.

### Request payloads (the whole list)

| Payload | Meaning |
| --- | --- |
| `sk:1:<product id>` | tick one product |
| `sk:0:<product id>` | untick it |
| `sk:a` | tick everything still open in the slot |

Each payload must match one of these patterns in full. Anything else (wrong
length, non-ASCII, an unknown action) is refused with an empty answer. Dates and
slots are never in the payload: they come from the journal row of the message the
request was sent from.

### State sent to Telegram

- skincare: `{"v":1,"r":rev,"t":title,"i":[[product id,name,0|1],…],"e":error}`
- brief: `{"v":1,"r":rev,"h":date,"t":[[label,value,unit,meta,norm,tone,fill,tick],…],"p":pending,"o":[[label,text,tone,note],…],"w":[14 × tenths of kg],"d":day line,"f":hint}`

`r` is a revision, so a late answer can't overwrite a newer state. The brief's
state is journalled next to the message, and a day-plan tap starts from it.

## Security model

- **Owner only.** A `widget_query` is acted on only if both the tapping user and
  the private chat equal `VITALS_TELEGRAM_CHAT_ID`. The webhook router already
  drops other chats (it reads a widget query's chat from `widget_query.chat`), and
  the handler checks again. Forwarded copies (`shared_widget_query`) have no chat
  and are dropped. Rejected requests are logged and get no answer.
- **Untrusted payload.** A closed action list and a strict format. The payload is
  never evaluated or built into SQL, and ids are resolved on the server.
- **Replay safe.** A tick carries the wanted state, not a toggle, so a repeat is
  a no-op. Telegram's webhook retries are dropped by `update_id` like every other
  update.
- **Conflict engine.** The widget always calls the services with
  `override=False`. A blocking conflict comes back as an error line in the card;
  waiving one stays a web-app action.
- **Data minimisation.** Telegram stores the HTML and the state. They carry only
  what the cards draw: product names and ticks, plus the brief's header numbers,
  which the text brief already sends. No protocol, notes, tokens, URLs, lab or
  genetics data. Everything is painted with `textContent` and attributes; no
  user text is ever put into the HTML.
- **Static code.** Templates load no external resources and use no `innerHTML` and
  no `eval`. Messages are sent with `protect_content`.
- **Flag and fallback.** With the flag off, nothing changes. If `sendWidget` fails,
  the plain message goes out with its buttons and a warning is logged. The stored
  brief and the journal always keep the full text.

## Limits

Compressed HTML must stay under 4096 bytes (currently about 0.8 KB for skincare
and 2.1 KB for the brief), and state under 1024 bytes. If the brief state would
not fit, it drops the sparkline first, then the rows, then the day line. Tests
check the limits, and that the templates stay offline.

## Trying it

1. Set `VITALS_TELEGRAM_WIDGETS=true` and restart.
2. Wait for the morning brief or the skincare reminder.
3. Tap a day-plan button under the brief card: the card's day line changes in place.

Telegram may currently refuse widgets from general bots. In that case you get the
plain messages and a "widget send failed" warning in the log.
