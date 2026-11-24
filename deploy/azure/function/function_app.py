"""Azure Functions (timer): thay APScheduler của các service backend khi chạy trên Container Apps.

Lịch theo slide của thầy: Analysis và Prediction 5 phút/lần, Clustering 1 ngày/lần.
Giờ chạy là UTC; 17:30 UTC = 00:30 giờ Việt Nam (khớp CLUSTERING_CRON_HOUR/MINUTE mặc định).
Ingestion không nằm ở đây: nó chạy liên tục trên VM vì cần luồng backfill nền.
"""

import azure.functions as func

from jobs import trigger

app = func.FunctionApp()

EVERY_5_MINUTES = "0 */5 * * * *"
DAILY_0030_VN = "0 30 17 * * *"


@app.timer_trigger(schedule=EVERY_5_MINUTES, arg_name="timer", run_on_startup=False, use_monitor=False)
def analysis_every_5_minutes(timer: func.TimerRequest) -> None:
    trigger("analysis")


@app.timer_trigger(schedule=EVERY_5_MINUTES, arg_name="timer", run_on_startup=False, use_monitor=False)
def prediction_every_5_minutes(timer: func.TimerRequest) -> None:
    trigger("prediction")


@app.timer_trigger(schedule=DAILY_0030_VN, arg_name="timer", run_on_startup=False, use_monitor=False)
def clustering_daily(timer: func.TimerRequest) -> None:
    trigger("clustering")
