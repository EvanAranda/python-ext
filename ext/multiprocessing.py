import asyncio
import logging
import multiprocessing as mp
import multiprocessing.pool as mpp
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from types import TracebackType
from typing import Awaitable, Callable, ContextManager, Generic, Self, TypeVar, cast

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class JobStats:
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0
        if self.finished_at is None:
            return 0
        return (self.finished_at - self.started_at).total_seconds()


class Job(Generic[T]):
    def __init__(self, jobid: int, func: Callable[..., T], *args):
        self.id = jobid
        self.func = func
        self.args = args
        self.stats: JobStats | None = None
        self.result: T | None = None
        self.error: Exception | None = None

    @property
    def name(self) -> str:
        return self.func.__name__

    def __str__(self) -> str:
        return f"Job {self.id} - {self.name}"


class JobHandle(Generic[T]):
    def __init__(self, job: Job[T]):
        self._job = job
        self._pool_task: mpp.AsyncResult = cast(mpp.AsyncResult, None)

    @property
    def job_id(self) -> int:
        return self._job.id

    @property
    def stats(self) -> JobStats:
        assert (
            self._job.stats is not None
        ), "job was not properly submitted to worker pool"
        return self._job.stats

    def join(self) -> T:
        assert (
            self._pool_task is not None
        ), "job was not properly submitted to worker pool"
        return self._pool_task.get()

    def _on_success(self, job: Job[T]) -> None:
        self._job = job
        log.debug(f"{self} finished in {self.stats.elapsed:.2f}s")

    def _on_error(self, error: BaseException) -> None:
        assert isinstance(error, JobFailedError), f"unexpected error type: {error}"
        self._job = error.job
        log.debug(f"{self} failed in {self.stats.elapsed:.2f}s")

    def __str__(self) -> str:
        return "(Handle) " + str(self._job)


class AsyncJobHandle(JobHandle[T], Awaitable[T], Generic[T]):
    def __init__(self, job: Job[T], future: asyncio.Future[T]):
        super().__init__(job)
        self._future = future

    def __await__(self):
        return self._future.__await__()

    def _on_success(self, job: Job[T]) -> None:
        def _set_result(j):
            JobHandle._on_success(self, j)
            self._future.set_result(j.result)  # type: ignore

        self._future.get_loop().call_soon_threadsafe(_set_result, job)

    def _on_error(self, error: BaseException) -> None:
        def _set_err(e: JobFailedError):
            JobHandle._on_error(self, e)
            self._future.set_exception(e.inner_error)

        self._future.get_loop().call_soon_threadsafe(_set_err, error)


class JobFailedError(Exception):
    def __init__(self, job: Job, inner_error: Exception, *args):
        self.job = job
        self.inner_error = inner_error
        super().__init__(*args)


def evaluate_job(job: Job):
    try:
        assert job.stats is not None, "job was not properly submitted to worker pool"
        job.stats.started_at = datetime.now()
        job.result = job.func(*job.args)
    except Exception as e:
        job.error = JobFailedError(job, e)
    finally:
        if job.stats:
            job.stats.finished_at = datetime.now()

    return job


class WorkerPool(ContextManager[Self]):
    _job_id = 0

    def __init__(self, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._pool = mp.Pool()
        self._loop = loop or asyncio.get_event_loop()
        log.debug("worker pool created")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        self._pool.terminate()
        log.debug("worker pool terminated")
        return super().__exit__(__exc_type, __exc_value, __traceback)

    def _next_job_id(self) -> int:
        self._job_id += 1
        return self._job_id

    def _submit(self, f, args, create_handle):
        job = Job(self._next_job_id(), f, *args)
        job.stats = JobStats(submitted_at=datetime.now())
        handle = create_handle(job)

        log.debug(f"submitting {handle}")

        handle._pool_task = self._pool.apply_async(
            evaluate_job,
            args=(job,),
            callback=handle._on_success,
            error_callback=handle._on_error,
        )

        return handle

    def submit(self, func: Callable, *args) -> AsyncJobHandle:
        return self._submit(
            func,
            args,
            partial(AsyncJobHandle, future=self._loop.create_future()),
        )
