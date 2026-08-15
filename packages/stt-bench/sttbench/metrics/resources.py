"""CPU / RAM / GPU sampling around a benchmark run.

Sampled on a background thread at a fixed interval rather than measured once at
the end, because the interesting number is the *peak* during decoding — a mean
taken over a run that is mostly silence would hide a model that pegs a core
whenever someone speaks.

CPU is reported as percent of a single core (so 400% means four cores busy) and
also normalized to total machine capacity, since "is the app still responsive"
depends on how much of the whole CPU is gone.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field


@dataclass
class ResourceSample:
    cpu_percent: float
    rss_mb: float
    gpu_percent: float | None = None
    gpu_mem_mb: float | None = None


@dataclass
class ResourceStats:
    cpu_percent_mean: float = 0.0
    cpu_percent_peak: float = 0.0
    cpu_cores: int = 1
    rss_mb_mean: float = 0.0
    rss_mb_peak: float = 0.0
    rss_mb_baseline: float = 0.0
    gpu_percent_peak: float | None = None
    gpu_mem_mb_peak: float | None = None
    samples: int = 0

    @property
    def cpu_percent_of_machine(self) -> float:
        if self.cpu_cores <= 0:
            return self.cpu_percent_mean
        return self.cpu_percent_mean / self.cpu_cores

    @property
    def cpu_peak_of_machine(self) -> float:
        if self.cpu_cores <= 0:
            return self.cpu_percent_peak
        return self.cpu_percent_peak / self.cpu_cores

    @property
    def rss_mb_delta(self) -> float:
        """Memory attributable to the engine: peak minus the interpreter
        baseline captured before the model was loaded."""
        return max(0.0, self.rss_mb_peak - self.rss_mb_baseline)


def gpu_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def _gpu_sample() -> tuple[float, float] | None:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=True,
        ).stdout.strip()
        util, mem = out.splitlines()[0].split(",")
        return float(util.strip()), float(mem.strip())
    except Exception:  # noqa: BLE001
        return None


class ResourceMonitor:
    """Context manager that samples this process while the body runs."""

    def __init__(self, interval_s: float = 0.15, watch_gpu: bool = False) -> None:
        self.interval_s = interval_s
        self.watch_gpu = watch_gpu and gpu_available()
        self._samples: list[ResourceSample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = None
        self._baseline_rss_mb = 0.0
        self._cores = 1
        self._paused = threading.Event()

    def __enter__(self) -> "ResourceMonitor":
        try:
            import psutil
        except ImportError:
            return self  # degrade to "no measurements" rather than failing the run

        self._proc = psutil.Process()
        self._cores = psutil.cpu_count(logical=True) or 1
        self._baseline_rss_mb = self._proc.memory_info().rss / 1e6
        # Prime the CPU counter; the first call always returns 0.0.
        self._proc.cpu_percent(None)

        self._thread = threading.Thread(target=self._run, name="resmon", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def pause(self) -> None:
        """Stops recording samples. Used to exclude model loading from the
        steady-state numbers — a 500 MB model load pegs several cores for a
        second or two, which would otherwise swamp the decoding average and
        make a cheap engine look expensive."""
        self._paused.set()

    def resume(self) -> None:
        if self._proc is not None:
            # Discard the CPU time accumulated while paused, so the first
            # sample after resuming does not report the load spike.
            try:
                self._proc.cpu_percent(None)
            except Exception:  # noqa: BLE001
                pass
        self._paused.clear()

    def _run(self) -> None:
        proc = self._proc
        assert proc is not None
        while not self._stop.wait(self.interval_s):
            if self._paused.is_set():
                continue
            try:
                cpu = proc.cpu_percent(None)
                rss = proc.memory_info().rss / 1e6
            except Exception:  # noqa: BLE001
                break
            gpu_util = gpu_mem = None
            if self.watch_gpu:
                got = _gpu_sample()
                if got:
                    gpu_util, gpu_mem = got
            self._samples.append(ResourceSample(cpu, rss, gpu_util, gpu_mem))

    def stats(self) -> ResourceStats:
        if not self._samples:
            return ResourceStats(cpu_cores=self._cores, rss_mb_baseline=self._baseline_rss_mb)

        cpus = [s.cpu_percent for s in self._samples]
        rss = [s.rss_mb for s in self._samples]
        gpu_utils = [s.gpu_percent for s in self._samples if s.gpu_percent is not None]
        gpu_mems = [s.gpu_mem_mb for s in self._samples if s.gpu_mem_mb is not None]

        return ResourceStats(
            cpu_percent_mean=sum(cpus) / len(cpus),
            cpu_percent_peak=max(cpus),
            cpu_cores=self._cores,
            rss_mb_mean=sum(rss) / len(rss),
            rss_mb_peak=max(rss),
            rss_mb_baseline=self._baseline_rss_mb,
            gpu_percent_peak=max(gpu_utils) if gpu_utils else None,
            gpu_mem_mb_peak=max(gpu_mems) if gpu_mems else None,
            samples=len(self._samples),
        )
