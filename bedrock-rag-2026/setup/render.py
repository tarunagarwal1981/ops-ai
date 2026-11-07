"""Fill ${VARS} in the setup/*.json templates from env vars and write them to build/.

    python setup/render.py      # needs AWS_REGION ACCOUNT_ID DOCS_BUCKET VECTOR_BUCKET INDEX_NAME
"""

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parent / "build"


def render(text, env=os.environ):
    missing = sorted({v for v in re.findall(r"\$\{(\w+)\}", text) if not env.get(v)})
    if missing:
        raise KeyError(f"set these env vars first: {', '.join(missing)}")
    return re.sub(r"\$\{(\w+)\}", lambda m: env[m.group(1)], text)


def main():
    OUT.mkdir(exist_ok=True)
    for template in sorted(HERE.glob("*.json")):
        try:
            (OUT / template.name).write_text(render(template.read_text()))
        except KeyError as e:
            sys.exit(str(e))
        print(f"build/{template.name}")


if __name__ == "__main__":
    main()
