"""python -m jarvis.routines run | list | now <name>"""
import sys

from . import find, load, run_due, run_one


def main(argv):
    cmd = argv[0] if argv else "run"
    if cmd == "run":
        done = run_due()
        print("\n".join(f"{name}: {line}" for name, _, line in done) or "nothing due")
        return 1 if any(not ok for _, ok, _ in done) else 0
    if cmd == "list":
        for r in load():
            print(f"{r['time']}  {r['name']}  [{r['action'] or 'unknown'}]  {r['instruction']}")
        return 0
    if cmd == "now" and len(argv) > 1:
        r = find(" ".join(argv[1:]))
        if r is None:
            print("no such routine")
            return 1
        ok, line = run_one(r)
        print(line)
        return 0 if ok else 1
    print(__doc__)
    return 2


sys.exit(main(sys.argv[1:]))
