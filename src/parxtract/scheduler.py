"""Resource-constrained deterministic job scheduler."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


_PROFILE_RANK = {"heavy-scalable": 0, "heavy-serial": 1, "small": 2}


@dataclass(frozen=True, slots=True)
class ScheduledJob(Generic[T]):
    """A payload annotated with the resources needed while it runs."""

    job_id: str
    payload: T
    profile: str
    priority: int
    estimated_weight: int
    plan_index: int
    cpu_tokens: int
    io_tokens: int = 1


@dataclass(slots=True)
class SchedulerEvent:
    """An observable scheduler transition, useful for progress and tests."""

    kind: str
    job_id: str
    running: int
    used_cpu: int
    used_io: int
    monotonic_time: float


@dataclass(slots=True)
class ScheduleReport(Generic[R]):
    """Completed worker values and scheduler interruption state."""

    results: list[tuple[ScheduledJob[object], R | BaseException]] = field(default_factory=list)
    interrupted: bool = False


class ResourceScheduler(Generic[T, R]):
    """Run independent jobs without exceeding CPU, process, or I/O budgets."""

    def __init__(
        self,
        *,
        cpu_budget: int,
        max_processes: int,
        io_slots: int,
        reservation_delay: float,
        clock: Callable[[], float] = time.monotonic,
        on_event: Callable[[SchedulerEvent], None] | None = None,
    ) -> None:
        if min(cpu_budget, max_processes, io_slots) < 1:
            raise ValueError("scheduler resource budgets must be positive")
        self.cpu_budget = cpu_budget
        self.max_processes = max_processes
        self.io_slots = io_slots
        self.reservation_delay = reservation_delay
        self.clock = clock
        self.on_event = on_event
        self.stop_event = threading.Event()
        self.interrupt_event = threading.Event()

    @staticmethod
    def sort_key(job: ScheduledJob[object]) -> tuple[int, int, int, int]:
        """Return the stable priority ordering required by the manifest contract."""

        return (
            -job.priority,
            _PROFILE_RANK.get(job.profile, 99),
            -job.estimated_weight,
            job.plan_index,
        )

    def stop(self) -> None:
        """Prevent new jobs from starting."""

        self.stop_event.set()

    def run(
        self,
        jobs: Iterable[ScheduledJob[T]],
        worker: Callable[[ScheduledJob[T], threading.Event], R],
        *,
        fail_fast_predicate: Callable[[R | BaseException], bool] | None = None,
        interrupt: Callable[[], None] | None = None,
    ) -> ScheduleReport[R]:
        """Execute jobs with backfill and an aging reservation for the queue head."""

        pending = sorted(list(jobs), key=self.sort_key)
        queued_at = {job.job_id: self.clock() for job in pending}
        running: dict[Future[R], ScheduledJob[T]] = {}
        used_cpu = 0
        used_io = 0
        report: ScheduleReport[R] = ScheduleReport()

        def fits(job: ScheduledJob[T]) -> bool:
            return (
                len(running) < self.max_processes
                and used_cpu + job.cpu_tokens <= self.cpu_budget
                and used_io + job.io_tokens <= self.io_slots
            )

        def event(kind: str, job: ScheduledJob[T]) -> None:
            if self.on_event:
                self.on_event(
                    SchedulerEvent(kind, job.job_id, len(running), used_cpu, used_io, self.clock())
                )

        with ThreadPoolExecutor(
            max_workers=self.max_processes, thread_name_prefix="parxtract"
        ) as pool:
            while pending or running:
                try:
                    started_any = False
                    while pending and not self.stop_event.is_set():
                        head = pending[0]
                        head_aged = self.clock() - queued_at[head.job_id] >= self.reservation_delay
                        selected_index: int | None = None
                        if fits(head):
                            selected_index = 0
                        elif not head_aged:
                            selected_index = next(
                                (
                                    index
                                    for index, candidate in enumerate(pending[1:], 1)
                                    if fits(candidate)
                                ),
                                None,
                            )
                        if selected_index is None:
                            break
                        selected = pending.pop(selected_index)
                        used_cpu += selected.cpu_tokens
                        used_io += selected.io_tokens
                        future = pool.submit(worker, selected, self.interrupt_event)
                        running[future] = selected
                        started_any = True
                        event("started", selected)

                    if not running:
                        # Jobs requiring more resources than the entire budget are invalid.
                        if pending and not self.stop_event.is_set():
                            impossible = pending[0]
                            raise ValueError(
                                f"job {impossible.job_id} can never fit scheduler resources"
                            )
                        break

                    completed, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                    for future in completed:
                        job = running.pop(future)
                        used_cpu -= job.cpu_tokens
                        used_io -= job.io_tokens
                        try:
                            value: R | BaseException = future.result()
                        except (
                            BaseException
                        ) as exc:  # Worker failures must still release resources.
                            value = exc
                        report.results.append((job, value))  # type: ignore[arg-type]
                        event("finished", job)
                        if fail_fast_predicate and fail_fast_predicate(value):
                            self.stop_event.set()
                    if not started_any and not completed:
                        time.sleep(0)
                except KeyboardInterrupt:
                    report.interrupted = True
                    self.stop_event.set()
                    self.interrupt_event.set()
                    if interrupt:
                        interrupt()

        return report
