"""Prints configuration status WITHOUT showing any secret value. Used by start.bat."""
from .config import DATA, load_sources

default, sources, notes = load_sources()
print("  .env file found:       ", "yes" if (DATA / ".env").exists() else "NO (copy .env.example to .env)")
for n in notes:
    st = sources.get(n["name"])
    if st:
        print(f"  {n['label']}: ON, symbols {', '.join(st.underlyings)}" + ("  [default]" if n["name"] == default else ""))
    else:
        print(f"  {n['label']}: off ({n['reason']})")
print("  Database folder:       ", next(iter(sources.values())).db_path.parent)
