import logging

import azure.functions as func
import logic

app = func.FunctionApp()


@app.function_name(name="IrrigationControlLoop")
@app.timer_trigger(schedule="0 */15 * * * *", arg_name="timer", run_on_startup=False)
def irrigation_control_loop(timer: func.TimerRequest) -> None:
    """Sense -> estimate -> decide -> actuate, every 15 minutes, per plot."""
    logging.info("running irrigation control loop")
    logic.run_irrigation_cycle()


@app.function_name(name="VerifyIrrigationEvents")
@app.timer_trigger(schedule="0 5-59/15 * * * *", arg_name="timer", run_on_startup=False)
def verify_irrigation_events(timer: func.TimerRequest) -> None:
    """Verify step: reconcile measured flow-meter volume against the intended decision."""
    logging.info("verifying irrigation events")
    logic.verify_irrigation_events()


@app.function_name(name="EnergyArbitration")
@app.timer_trigger(schedule="0 */15 * * * *", arg_name="timer", run_on_startup=False)
def energy_arbitration(timer: func.TimerRequest) -> None:
    """Cluster-level six-step solar priority order."""
    logging.info("running energy arbitration")
    logic.run_energy_arbitration()


@app.function_name(name="ShelfLifeUpdate")
@app.timer_trigger(schedule="0 */30 * * * *", arg_name="timer", run_on_startup=False)
def shelf_life_update(timer: func.TimerRequest) -> None:
    logging.info("recomputing storage-lot shelf life")
    logic.run_shelf_life_update()


@app.function_name(name="DailyVoiceAdvisory")
@app.timer_trigger(schedule="0 40 6 * * *", arg_name="timer", run_on_startup=False)
def daily_voice_advisory(timer: func.TimerRequest) -> None:
    """6:40 AM outbound calls carrying the day's recommendation (rung 2)."""
    logging.info("sending daily voice advisories")
    logic.send_daily_voice_advisories()


@app.function_name(name="CloseLedgerPeriod")
@app.timer_trigger(schedule="0 0 3 * * 1", arg_name="timer", run_on_startup=False)
def close_ledger_period(timer: func.TimerRequest) -> None:
    """Weekly (Monday 03:00): write the auditable savings-ledger entries."""
    logging.info("closing weekly ledger period")
    logic.close_ledger_period(period_days=7)
