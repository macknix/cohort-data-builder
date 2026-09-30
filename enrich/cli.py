"""Tag a dataset's variables by topic with an LLM via Ollama.

    python -m enrich next_steps
    python -m enrich bcs70 --model gpt-oss:20b-cloud --batch-size 10 --workers 2
    python -m enrich next_steps --limit 200 --dry-run

Resumable: variables already tagged with the current schema are skipped, so
an interrupted run (Ctrl-C is fine) carries on where it stopped. Editing
schema/topics.yaml makes every existing tag stale, and the next run redoes
them.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn,
                           TextColumn, TimeElapsedColumn, TimeRemainingColumn)
from rich.table import Table

from . import corpus
from . import schema as schema_mod
from .corpus import Variable
from .store import TagStore
from .tagger import Tagger, ollama

ROOT = Path(__file__).resolve().parent.parent
console = Console()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m enrich",
        description="Tag survey variables with topics from schema/topics.yaml, using an LLM via Ollama.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("dataset", nargs="?", help=f"dataset to tag: {', '.join(corpus.datasets())}")
    ap.add_argument("--all", action="store_true", help="tag every dataset in turn")
    ap.add_argument("--model", default="gpt-oss:120b-cloud", help="Ollama model")
    ap.add_argument("--batch-size", type=int, default=20, help="variables per request")
    ap.add_argument("--workers", type=int, default=4, help="requests in flight at once")
    ap.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama server")
    ap.add_argument("--schema", type=Path, default=ROOT / "schema" / "topics.yaml",
                    help="topic schema (YAML)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--num-ctx", type=int, default=16384, help="context window, in tokens")
    ap.add_argument("--reasoning", default=None,
                    help="reasoning effort for thinking models: true, false, low, medium, high")
    ap.add_argument("--timeout", type=float, default=300, help="seconds to wait per request")
    ap.add_argument("--retries", type=int, default=2,
                    help="retries per batch; unanswered variables are then retried one by one")
    ap.add_argument("--limit", type=int, default=None, help="tag at most this many variables")
    ap.add_argument("--files", nargs="+", default=None,
                    help="only these data files (names as in files.csv)")
    ap.add_argument("--retag", action="store_true", help="redo variables that already have current tags")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the first batch's prompt and what would run, then stop")
    args = ap.parse_args(argv)
    if not args.dataset and not args.all:
        ap.error("name a dataset, or use --all")
    if args.batch_size < 1 or args.workers < 1:
        ap.error("--batch-size and --workers must be at least 1")
    return args


def shown(path: Path) -> str:
    """A path as the user should read it: relative to the repo when inside it."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def record(v: Variable, topics: dict[str, float], model: str, schema_hash: str) -> dict:
    return {"file": v.file, "variable": v.name, "topics": topics,
            "model": model, "schema": schema_hash, "tagged": date.today().isoformat()}


class Run:
    """One dataset's run: the work list, the counts, and the progress bar."""

    def __init__(self, args, sch: schema_mod.Schema, key: str):
        self.args, self.schema = args, sch
        self.ds = corpus.load(key)
        self.store = TagStore(corpus.DATASETS / key / "tags")

        variables = self.ds.variables
        if args.files:
            wanted = set(args.files)
            unknown = wanted - {v.file for v in variables}
            if unknown:
                raise SystemExit(f"Not in {key}: {', '.join(sorted(unknown))}")
            variables = [v for v in variables if v.file in wanted]
        self.order = [v.key for v in self.ds.variables]

        # The identifier needs no model: it is what it is.
        ident = self.ds.identifier.lower()
        self.identifiers = [v for v in variables if v.name.lower() == ident
                            and (args.retag or not self.store.is_current(v.key, sch.hash))]
        todo = [v for v in variables if v.name.lower() != ident]
        self.current = sum(self.store.is_current(v.key, sch.hash) for v in todo)
        if not args.retag:
            todo = [v for v in todo if not self.store.is_current(v.key, sch.hash)]
        if args.limit is not None:
            todo = todo[: args.limit]
        self.todo = todo
        self.total = len(variables)
        self.stats = Counter()
        self.topic_counts = Counter()
        self.failed: list[Variable] = []

    def batches(self) -> list[list[Variable]]:
        n = self.args.batch_size
        return [self.todo[i:i + n] for i in range(0, len(self.todo), n)]

    def summary_panel(self) -> Panel:
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold"); t.add_column()
        t.add_row("Dataset", f"{self.ds.name} ({self.ds.key})")
        t.add_row("Variables", f"{self.total:,} in scope · {self.current:,} already tagged "
                               f"with this schema · [bold]{len(self.todo):,} to tag[/]")
        t.add_row("Model", f"{self.args.model} at {self.args.ollama_url}")
        t.add_row("Batches", f"{len(self.batches()):,} of up to {self.args.batch_size} · "
                             f"{self.args.workers} at once")
        t.add_row("Schema", f"{self.schema.name} v{self.schema.version} · "
                            f"{len(self.schema.topics)} topics in {len(self.schema.domains)} "
                            f"domains · {self.schema.hash}")
        t.add_row("Output", shown(self.store.path))
        return Panel(t, title="Tagging", border_style="magenta", expand=False)


def tag_batch(tagger: Tagger, batch: list[Variable], retries: int) -> tuple[dict, list, int]:
    """Tag one batch: retry it whole, then retry whatever the model skipped
    one at a time. Returns ({index: topics}, [failed indices], retries used)."""
    done: dict[int, dict] = {}
    pending = list(range(len(batch)))
    used = 0
    last_error = None
    for attempt in range(retries + 1):
        if not pending:
            break
        if attempt:
            used += 1
        try:
            sub = [batch[i] for i in pending]
            result = tagger.tag(sub)
            for j, topics in result.tags.items():
                done[pending[j]] = topics
            pending = [pending[j] for j in result.missing]
        except Exception as err:  # parse failure, timeout, dropped connection
            last_error = err
    # Anything still unanswered: one at a time, which a model rarely fumbles.
    for i in list(pending):
        try:
            used += 1
            result = tagger.tag([batch[i]])
            if 0 in result.tags:
                done[i] = result.tags[0]
                pending.remove(i)
        except Exception as err:
            last_error = err
    if pending and last_error and len(pending) == len(batch):
        console.log(f"[yellow]batch failed:[/] {type(last_error).__name__}: {str(last_error)[:160]}")
    return done, pending, used


def run_dataset(args, sch: schema_mod.Schema, key: str) -> int:
    run = Run(args, sch, key)
    console.print(run.summary_panel())

    llm = ollama(args.model, args.ollama_url, sch, args.temperature, args.num_ctx,
                 args.reasoning, args.timeout)
    tagger = Tagger(sch, llm, run.ds.name)

    if args.dry_run:
        batches = run.batches()
        if batches:
            for m in tagger.messages(batches[0]):
                console.rule(type(m).__name__)
                console.print(m.content, markup=False, highlight=False)
        console.print("[dim]--dry-run: nothing sent to the model.[/]")
        return 0

    run.store.write_schema(sch.snapshot())
    if run.identifiers:
        run.store.add([record(v, {"identifiers": 1.0}, "rule", sch.hash) for v in run.identifiers])

    if not run.todo:
        run.store.compact(run.order)
        console.print("[green]Nothing to do: every variable has current tags.[/]")
        return 0

    progress = Progress(
        SpinnerColumn(), TextColumn("[bold]{task.description}"), BarColumn(),
        MofNCompleteColumn(), TaskProgressColumn(),
        TextColumn("[dim]elapsed[/]"), TimeElapsedColumn(),
        TextColumn("[dim]remaining[/]"), TimeRemainingColumn(),
        console=console,
    )
    started = time.monotonic()

    def status() -> str:
        s = run.stats
        rate = s["tagged"] / max(time.monotonic() - started, 1e-6)
        left = len(run.todo) - s["tagged"] - s["failed"]
        return (f"[green]{s['tagged']:,} tagged[/] · [bold]{left:,} left[/] · "
                f"{'[red]' if s['failed'] else '[dim]'}{s['failed']:,} failed[/] · "
                f"{s['retries']:,} retries · {rate:.1f} vars/s · "
                f"last batch {s['last_ms'] / 1000:.1f}s")

    class StatusLine:
        # Its own line under the bar: as a column of the bar it took the
        # width the bar and the times needed.
        def __rich__(self):
            return "  " + status()

    interrupted = False
    batches = run.batches()
    with Live(Group(progress, StatusLine()), console=console, refresh_per_second=4):
        task = progress.add_task(f"{run.ds.name}", total=len(run.todo))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            queue = iter(batches)
            running = {}

            def submit():
                batch = next(queue, None)
                if batch is not None:
                    running[pool.submit(timed, tagger, batch, args.retries)] = batch

            for _ in range(args.workers):
                submit()
            try:
                while running:
                    finished, _ = wait(running, return_when=FIRST_COMPLETED)
                    for fut in finished:
                        batch = running.pop(fut)
                        (done, failed, used), ms = fut.result()
                        run.store.add([record(batch[i], t, args.model, sch.hash)
                                       for i, t in done.items()])
                        for t in done.values():
                            run.topic_counts.update(t.keys())
                        run.failed += [batch[i] for i in failed]
                        run.stats.update(tagged=len(done), failed=len(failed), retries=used)
                        run.stats["last_ms"] = ms
                        progress.update(task, advance=len(batch))
                        submit()
            except KeyboardInterrupt:
                interrupted = True
                for fut in running:
                    fut.cancel()
                console.print("[yellow]Stopping: saving what has finished…[/]")

    run.store.compact(run.order)
    report(run, interrupted, time.monotonic() - started)
    return 1 if run.failed or interrupted else 0


def timed(tagger, batch, retries):
    t0 = time.monotonic()
    out = tag_batch(tagger, batch, retries)
    return out, (time.monotonic() - t0) * 1000


def report(run: Run, interrupted: bool, seconds: float) -> None:
    s = run.stats
    t = Table(title=f"{run.ds.name}: most used topics", show_edge=False, expand=False)
    t.add_column("topic"); t.add_column("domain", style="dim"); t.add_column("variables", justify="right")
    for topic, n in run.topic_counts.most_common(12):
        t.add_row(run.schema.topics[topic].label, run.schema.domain_of[topic].label, f"{n:,}")
    if run.topic_counts:
        console.print(t)
    head = "[yellow]Stopped[/]" if interrupted else ("[yellow]Finished with failures[/]"
                                                    if run.failed else "[green]Finished[/]")
    console.print(f"{head}: {s['tagged']:,} tagged, {s['failed']:,} failed, "
                  f"{s['retries']:,} retries in {seconds / 60:.1f} min. "
                  f"Saved to {shown(run.store.path)}.")
    if run.failed:
        names = ", ".join(v.key for v in run.failed[:5])
        console.print(f"[yellow]Not tagged:[/] {names}{' …' if len(run.failed) > 5 else ''}")
    if interrupted or run.failed:
        console.print("Run the same command again to carry on; finished variables are skipped.")
    else:
        console.print("Next: [bold]python3 build.py[/] to show the tags on the site.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sch = schema_mod.load(args.schema)
    except Exception as err:
        console.print(f"[red]Schema error in {args.schema}:[/] {err}")
        return 2
    keys = corpus.datasets() if args.all else [args.dataset]
    code = 0
    for key in keys:
        code = max(code, run_dataset(args, sch, key))
    return code


if __name__ == "__main__":
    sys.exit(main())
