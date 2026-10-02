"""Patch OPENAI_API_KEY into /opt/mosaiq-shop/.env from a key file (no shell echo)."""

import pathlib

key_line = pathlib.Path("/tmp/openai_key.line").read_text().strip()
assert key_line.startswith("OPENAI_API_KEY=") and len(key_line) > 20

env = pathlib.Path("/opt/mosaiq-shop/.env")
text = env.read_text()
lines = text.splitlines()
out = []
replaced = False
for ln in lines:
    if ln.startswith("OPENAI_API_KEY="):
        out.append(key_line)
        replaced = True
    else:
        out.append(ln)
if not replaced:
    out.append(key_line)
env.write_text("\n".join(out) + "\n")
pathlib.Path("/tmp/openai_key.line").unlink(missing_ok=True)
print("env patched:", replaced)
