"""Run the workspace rationale coverage check when its inputs are present.

``scripts/check_rationale.py`` belongs to the ACD repository checkout and is not part
of the copied plugin tree, so the installed-plugin path has no such script in the
conversation workspace. Invoking it unconditionally makes the hook exit with a missing
file and block every stop event. This wrapper keeps the check fail-closed where it can
apply: the rationale inputs decide whether the check is applicable, and a missing
validator with present inputs is a denial rather than a silent pass.
"""

from __future__ import annotations

import subprocess
import sys

from common import event, project_dir, result

GRAPH_PATH = "fixtures/golden-design-1/graph.json"
RATIONALE_PATH = "fixtures/golden-design-1/rationale.json"
VALIDATOR_PATH = "scripts/check_rationale.py"


def main(argv: list[str]) -> int:
    warn_only = "--warn-only" in argv
    root = project_dir(event())
    inputs = [root / GRAPH_PATH, root / RATIONALE_PATH]
    if not all(path.is_file() for path in inputs):
        print("Rationale validation not applicable; graph or rationale is not present.")
        return 0
    validator = root / VALIDATOR_PATH
    if not validator.is_file():
        reason = (
            f"Rationale inputs are present but {VALIDATOR_PATH} cannot be resolved "
            f"under {root}."
        )
        if warn_only:
            print(reason)
            return 0
        result(decision="deny", reason=reason)
        return 2
    command = [
        "uv",
        "run",
        "--project",
        str(root),
        "python",
        str(validator),
        "--if-present",
    ]
    if warn_only:
        command.append("--warn-only")
    try:
        completed = subprocess.run(command, cwd=root, check=False)
    except OSError as exc:
        reason = f"Rationale validation could not be executed: {exc}."
        if warn_only:
            print(reason)
            return 0
        result(decision="deny", reason=reason)
        return 2
    return 0 if warn_only else completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
