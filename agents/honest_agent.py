"""HonestAgent: takes a job, actually does the work, then delivers.

Usage (from the repo root):
    agents/.venv/Scripts/python agents/honest_agent.py [--name HonestAgent]
"""

from __future__ import annotations

import threading
import time

from escrow import usd
from worker import Worker, parse_args

WORK_SECONDS = 3.0


def main() -> None:
    worker = Worker(parse_args(default_name="HonestAgent").name)

    def work(job_id: int) -> None:
        time.sleep(WORK_SECONDS)
        worker.deliver(job_id)

    # Each job is worked in its own thread, so several jobs run concurrently. One job behaves
    # exactly as before: announce, work WORK_SECONDS, deliver.
    def do_work(job_id: int, value: int) -> None:
        worker.say(f"saw job #{job_id} ({usd(value)}), working...")
        threading.Thread(target=work, args=(job_id,), daemon=True).start()

    worker.run(do_work)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
