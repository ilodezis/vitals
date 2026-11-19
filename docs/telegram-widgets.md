# Telegram widgets (experimental)

Two cards in the bot that live inside the message bubble instead of text plus
inline buttons. Off by default. When Telegram refuses a widget, the existing plain
message goes out instead.

Enable with `VITALS_TELEGRAM_WIDGETS=true` and make sure the webhook's
`allowed_updates` includes `widget_query` (if you pass `allowed_updates` to
`setWebhook` at all). Widgets work only in the private chat with the bot.

## Why these two

Both replace something done every day that costs taps or typing today.

- **Skincare checklist.** The text-and-buttons version redraws the whole message
  after every tick and shows one button per product. The widget keeps one bubble,
  ticks in place, and updates when you tick in the app.
- **Weight card.** Logging a weight meant opening the app. The card sits under the
  morning brief while today's weight is missing: a 7-day sparkline and a stepper
  (±0.1 / ±0.5 kg, starting from the last reading), one tap to save. There is no
  text twin: a number can't be typed into a button, so when the flag is off or
  the widget is refused, nothing is sent and the app is the way to log, as before.

## How it works

The HTML is a static template in `vitals/services/proactive/widgets/templates/`,
fixed when the message is sent. Only the *chat state* (a JSON string under 1 KB)
changes, through `editMessageWidgetData`. The widget has no network. Its one way
out is `TelegramWidget.request(data)`: at most 64 bytes, delivered as a
`widget_query` update. The bot answers with the card's new state and writes the
same state to the message.

### Request payloads (the whole list)

| Payload | Meaning |
| --- | --- |
| `sk:1:<product id>` | tick one product |
| `sk:0:<product id>` | untick it |
| `sk:a` | tick everything still open in the slot |
| `wt:<tenths of kg>` | log today's weight, e.g. `wt:823` is 82.3 kg (20.0–400.0) |

Each payload is matched in full against a regular expression. Anything else
(wrong length, non-ASCII, unknown action, number out of range) is refused with an
empty answer. Dates and slots are never in the payload: they come from the
journal row of the message the request was sent from.

### State sent to Telegram

- skincare: `{"v":1,"r":rev,"t":title,"i":[[product id,name,0|1],…],"e":error}`
- weight: `{"v":1,"r":rev,"d":"dd.mm","w":[7 × tenths of kg],"c":start,"l":logged,"e":error}`

`r` is a revision so a late answer can't overwrite a newer state.

## Security model

- **Owner only.** A `widget_query` is acted on only if both the tapping user and
  the private chat equal `VITALS_TELEGRAM_CHAT_ID`. The webhook router already
  drops other chats (a widget query's chat is read from `widget_query.chat`);
  the handler checks again. Forwarded copies (`shared_widget_query`) have no chat
  and are dropped. Rejected requests are logged and get no answer.
- **Untrusted payload.** Closed action list, strict format, no `eval`, no SQL
  built from it, ids resolved on the server.
- **Replay safe.** Ticks carry the wanted state rather than a toggle, so a repeat
  is a no-op. The same weight is the same row. Telegram's webhook retries are
  dropped by `update_id` like every other update. A weight card from another day
  refuses to log.
- **Conflict engine.** The widget always calls the services with
  `override=False`. A blocking conflict comes back as an error line in the card;
  waiving one stays a web-app action.
- **Data minimisation.** The HTML and state are stored by Telegram. They carry
  product names, ticks and a week of weights and nothing else: no tokens, URLs,
  lab or genetics data. The sparkline and the checklist are drawn from state with
  `textContent` and attributes; no user text is ever put into the HTML.
- **Static code.** Templates contain no external resources, no `innerHTML`, no
  `eval`. Messages are sent with `protect_content`.
- **Flag and fallback.** With the flag off, nothing changes. If `sendWidget`
  fails, the skincare checklist goes out as the plain message with buttons and a
  warning is logged; the weight card is skipped.

## Limits

Compressed HTML must stay under 4096 bytes (currently about 0.8 KB and 1.2 KB),
state under 1024 bytes. Tests check both, and that the templates stay offline.

## Trying it

1. Set `VITALS_TELEGRAM_WIDGETS=true`, restart.
2. Wait for the skincare reminder time; the weight card follows the morning
   brief while today's weight is empty.
3. Tick a product, then tick one in the app: the bubble follows.

Telegram may currently refuse widgets from general bots; in that case you'll see
the plain checklist and a "widget send failed" warning in the log.
