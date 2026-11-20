"""Telegram widgets: small HTML cards that live inside a bot message.

Two cards, both behind ``VITALS_TELEGRAM_WIDGETS`` (default off):

  * the morning brief — the header's numbers as a card, the model's words below
    (:mod:`brief_card`; sends no requests at all);
  * the skincare checklist — tick products in the bubble, no message churn.

The HTML is a static template (``templates/``); only the chat state (a small JSON
string, see :mod:`state`) ever changes. The skincare card's single way out is a request
of at most 64 bytes, parsed by :mod:`payload` and executed by :mod:`handler`.
"""
