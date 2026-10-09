"""Read the name and GitHub URL recorded by the runner configuration tool."""

import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as runner_file:
    identity = json.load(runner_file)
print(identity.get("agentName", ""))
print(identity.get("gitHubUrl", ""))
