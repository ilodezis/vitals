"""Telegram widgets: small HTML cards that live inside a bot message.

Two cards, both behind ``VITALS_TELEGRAM_WIDGETS`` (default off):

  * the skincare checklist — tick products in the bubble, no message churn;
  * the weight card — a 7-day sparkline and a stepper to log today's weight.

The HTML is a static template (``templates/``); only the chat state (a small JSON
string, see :mod:`state`) ever changes. The widget's single way out is a request of
at most 64 bytes, parsed by :mod:`payload` and executed by :mod:`handler`.
"""
