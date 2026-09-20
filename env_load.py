# -*- coding: utf-8 -*-
"""Standalone bridge for the production client's single env-loader contract.

The bot has a richer `env_load` module. The public extract must not teach `nansen_api.py` a second
way to read `.env`: two resolvers diverge on precedence and quoting. Instead it satisfies the same
one-function contract here. `python-dotenv` is already listed in requirements.txt.
"""


def load():
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return True
    except Exception:
        # Explicit `export NANSEN_API_KEY=...` still works; missing dotenv must not make module
        # import fail before the honest `nokey` refusal can be shown.
        return False
