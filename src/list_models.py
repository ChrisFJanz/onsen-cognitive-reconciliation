"""List the OpenAI model ids available to your account.

Use it to find the exact id for a model (for example GPT-6 Astra) to pass to
--model. Reads your key from .env.

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/list_models.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

if not os.environ.get("OPENAI_API_KEY"):
    sys.exit("OPENAI_API_KEY not set; write it into .env first.")

from openai import OpenAI

ids = sorted(m.id for m in OpenAI().models.list().data)
for mid in ids:
    print(mid)
print(f"\n{len(ids)} models. Pass the exact id you want with --model.")
