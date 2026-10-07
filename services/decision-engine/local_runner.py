"""Local/dev substitute for the Azure Functions timer triggers in function_app.py.

Runs the same logic.py functions on plain Python timers, in-process, so you
can `python local_runner.py` against docker-compose without needing the
Azure Functions Core Tools installed. The deployed app uses function_app.py
(Azure Functions timers), not this file.
"""
import logging
import threading
import time

import logic

logging.basicConfig(level="INFO")


def _every(seconds: float, fn, name: str):
    def loop():
        while True:
            try:
                fn()
            except Exception:
                logging.exception("%s failed", name)
            time.sleep(seconds)

    t = threading.Thread(target=loop, name=name, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    threads = [
        _every(60 * 15, logic.run_irrigation_cycle, "irrigation-cycle"),
        _every(60 * 15, logic.run_energy_arbitration, "energy-arbitration"),
        _every(60 * 5, logic.verify_irrigation_events, "verify-events"),
        _every(60 * 30, logic.run_shelf_life_update, "shelf-life"),
    ]
    logging.info("decision-engine local runner started (%d loops)", len(threads))
    while True:
        time.sleep(3600)
