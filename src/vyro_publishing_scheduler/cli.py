import json, os, typer
from rich import print
from .store import QueueStore
app=typer.Typer(no_args_is_help=True,help="VYRO Publishing Scheduler")

def get_store():
    return QueueStore(os.getenv("VYRO_SCHEDULER_DB", "vyro_scheduler.sqlite3"), os.getenv("TIMEZONE", "Asia/Jakarta"))

@app.command()
def init():
 store=get_store(); print(f"[green]Database ready[/green]: {store.db_path}")

@app.command()
def add(content_id: str=typer.Option(...), video_url: str=typer.Option(...), caption: str=typer.Option(""), at: str=typer.Option(...), idempotency_key: str=typer.Option(...)):
 job=get_store().add_job(content_id,video_url,caption,at,idempotency_key)
 print({"job_id":job,"status":"SCHEDULED"})

@app.command()
def due(limit: int=typer.Option(10,"--limit")):
 print(json.dumps(get_store().claim_due(limit),ensure_ascii=False,indent=2))

@app.command()
def complete(job_id: str, media_id: str=typer.Option(...)):
 get_store().complete(job_id,media_id); print({"job_id":job_id,"status":"PUBLISHED"})

@app.command()
def fail(job_id: str, reason: str=typer.Option(...), retry_in: int=typer.Option(300)):
 get_store().fail(job_id,reason,retry_in); print({"job_id":job_id,"status":"REQUEUED_OR_FAILED"})

@app.command("metrics")
def metrics(job_id: str, scheduled_at: str=typer.Option(...), views: float=0, reach: float=0, shares: float=0, saves: float=0, comments: float=0, profile_visits: float=0, follows: float=0, inquiries: float=0):
 get_store().add_metrics(job_id,scheduled_at,views=views,reach=reach,shares=shares,saves=saves,comments=comments,profile_visits=profile_visits,follows=follows,inquiries=inquiries)
 print("[green]Metrics recorded[/green]")

@app.command("recommend-slots")
def recommend_slots(): print(json.dumps(get_store().recommend_slots(),ensure_ascii=False,indent=2))
