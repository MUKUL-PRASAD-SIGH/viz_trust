"""SloppyAgent: takes a job and marks it delivered instantly, without doing the work.

The hirer notices and disputes. That dispute is the demo's pivot.

Usage (from the repo root):
    agents/.venv/Scripts/python agents/sloppy_agent.py [--name SloppyAgent]
"""

from __future__ import annotations

from escrow import usd
from worker import Worker, parse_args


def main() -> None:
    worker = Worker(parse_args(default_name="SloppyAgent").name)

    def do_work(job_id: int, value: int) -> None:
        worker.say(f"saw job #{job_id} ({usd(value)}), marking it delivered without doing the work")
        worker.deliver(job_id)

    worker.run(do_work)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
