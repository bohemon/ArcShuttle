from __future__ import annotations

import threading
import time

from parxtract.scheduler import ResourceScheduler, ScheduledJob


def job(
    name: str,
    *,
    profile: str = "small",
    cpu: int = 1,
    io: int = 1,
    priority: int = 0,
    weight: int = 1,
    index: int = 0,
) -> ScheduledJob[str]:
    return ScheduledJob(name, name, profile, priority, weight, index, cpu, io)


def test_resource_limits_are_never_exceeded() -> None:
    lock = threading.Lock()
    current_cpu = current_io = current_count = 0
    maxima = [0, 0, 0]

    def worker(item: ScheduledJob[str], stop: threading.Event) -> str:
        nonlocal current_cpu, current_io, current_count
        with lock:
            current_cpu += item.cpu_tokens
            current_io += item.io_tokens
            current_count += 1
            maxima[0] = max(maxima[0], current_cpu)
            maxima[1] = max(maxima[1], current_io)
            maxima[2] = max(maxima[2], current_count)
        time.sleep(0.015)
        with lock:
            current_cpu -= item.cpu_tokens
            current_io -= item.io_tokens
            current_count -= 1
        return item.job_id

    scheduler = ResourceScheduler[str, str](
        cpu_budget=4, max_processes=3, io_slots=2, reservation_delay=1
    )
    jobs = [job(str(index), cpu=2 if index % 2 else 1, index=index) for index in range(8)]

    report = scheduler.run(jobs, worker)

    assert len(report.results) == 8
    assert maxima[0] <= 4
    assert maxima[1] <= 2
    assert maxima[2] <= 3


def test_heavy_priority_and_deterministic_ties() -> None:
    order: list[str] = []
    scheduler = ResourceScheduler[str, str](
        cpu_budget=1, max_processes=1, io_slots=1, reservation_delay=1
    )
    jobs = [
        job("small", profile="small", index=0),
        job("serial", profile="heavy-serial", index=2),
        job("scalable-later", profile="heavy-scalable", weight=5, index=3),
        job("scalable-first", profile="heavy-scalable", weight=5, index=1),
    ]

    scheduler.run(jobs, lambda item, stop: order.append(item.job_id) or item.job_id)

    assert order == ["scalable-first", "scalable-later", "serial", "small"]


def test_small_job_backfills_unused_cpu() -> None:
    small_started = threading.Event()
    first_heavy_can_finish = threading.Event()
    order: list[str] = []

    def worker(item: ScheduledJob[str], stop: threading.Event) -> str:
        order.append(item.job_id)
        if item.job_id == "heavy-one":
            assert small_started.wait(1), "small job was not backfilled"
            first_heavy_can_finish.set()
        elif item.job_id == "small":
            small_started.set()
            assert first_heavy_can_finish.wait(1)
        return item.job_id

    scheduler = ResourceScheduler[str, str](
        cpu_budget=4, max_processes=2, io_slots=2, reservation_delay=5
    )
    jobs = [
        job("heavy-one", profile="heavy-scalable", cpu=3, weight=10, index=0),
        job("heavy-two", profile="heavy-scalable", cpu=3, weight=9, index=1),
        job("small", profile="small", cpu=1, index=2),
    ]

    scheduler.run(jobs, worker)

    assert order[:2] == ["heavy-one", "small"]
    assert order[2] == "heavy-two"


def test_aged_head_reserves_resources() -> None:
    now = [0.0]
    release_first = threading.Event()
    sequence: list[str] = []

    def worker(item: ScheduledJob[str], stop: threading.Event) -> str:
        sequence.append(item.job_id)
        if item.job_id == "heavy-running":
            assert release_first.wait(1)
        elif item.job_id == "small-one":
            now[0] = 10.0
            release_first.set()
        return item.job_id

    scheduler = ResourceScheduler[str, str](
        cpu_budget=4,
        max_processes=2,
        io_slots=2,
        reservation_delay=5,
        clock=lambda: now[0],
    )
    jobs = [
        job("heavy-running", profile="heavy-scalable", cpu=3, weight=30, index=0),
        job("heavy-waiting", profile="heavy-scalable", cpu=4, weight=20, index=1),
        job("small-one", cpu=1, weight=2, index=2),
        job("small-two", cpu=1, weight=1, index=3),
    ]

    scheduler.run(jobs, worker)

    assert sequence.index("heavy-waiting") < sequence.index("small-two")


def test_worker_failure_releases_resources() -> None:
    ran: list[str] = []

    def worker(item: ScheduledJob[str], stop: threading.Event) -> str:
        ran.append(item.job_id)
        if item.job_id == "bad":
            raise RuntimeError("boom")
        return item.job_id

    scheduler = ResourceScheduler[str, str](
        cpu_budget=1, max_processes=1, io_slots=1, reservation_delay=1
    )

    report = scheduler.run([job("bad", index=0), job("good", index=1)], worker)

    assert ran == ["bad", "good"]
    assert isinstance(report.results[0][1], RuntimeError)


def test_stop_prevents_new_jobs() -> None:
    scheduler = ResourceScheduler[str, str](
        cpu_budget=1, max_processes=1, io_slots=1, reservation_delay=1
    )
    ran: list[str] = []

    def worker(item: ScheduledJob[str], stop: threading.Event) -> str:
        ran.append(item.job_id)
        scheduler.stop()
        return item.job_id

    scheduler.run([job("one", index=0), job("two", index=1)], worker)

    assert ran == ["one"]


def test_keyboard_interrupt_stops_launches_and_sets_cancel_event() -> None:
    raised = [False]
    saw_cancel = threading.Event()

    def on_event(event) -> None:
        if event.kind == "started" and not raised[0]:
            raised[0] = True
            raise KeyboardInterrupt

    scheduler = ResourceScheduler[str, str](
        cpu_budget=1,
        max_processes=1,
        io_slots=1,
        reservation_delay=1,
        on_event=on_event,
    )

    def worker(item: ScheduledJob[str], cancel: threading.Event) -> str:
        if cancel.wait(1):
            saw_cancel.set()
        return item.job_id

    report = scheduler.run([job("one", index=0), job("two", index=1)], worker)

    assert report.interrupted is True
    assert saw_cancel.is_set()
    assert len(report.results) == 1
