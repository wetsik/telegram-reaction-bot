import asyncio
import hashlib
import re
import shutil
import traceback
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from telethon import types

from settings import (
    DOWNLOADS_DIR,
    OUTPUTS_DIR,
    SUPPORTED_MEDIA_EXTENSIONS,
    VOCAL_PROCESS_ESTIMATE_SECONDS,
    VOCAL_PROGRESS_UPDATE_INTERVAL,
    VOCAL_SEND_TIMEOUT_SECONDS,
    VOCAL_SEPARATION_TIMEOUT_SECONDS,
    TZ_OFFSET,
)


PROCESSING_MESSAGE = "⏳ Processing your file..."
DONE_MESSAGE = "✅ Done! Download below."
ERROR_MESSAGE = "❌ Error occurred while processing."
UNSUPPORTED_MESSAGE = "⚠️ Unsupported format. Send audio/video or a link."
INSTRUCTION_MESSAGE = (
    "Send an audio/video file, voice message, or a YouTube/direct media link.\n"
    "Supported formats: mp3, wav, m4a, mp4, webm, ogg, opus, flac, aac.\n"
    "Use /cancel to stop the current task."
)
CANCELLED_MESSAGE = "⛔ Processing cancelled."
NOTHING_TO_CANCEL_MESSAGE = "Nothing is processing right now."

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PERCENT_RE = re.compile(r"(\d{1,3})%")
RESULT_CACHE_DIR = OUTPUTS_DIR / "cache"

SUPPORTED_MIME_PREFIXES = ("audio/", "video/")
SUPPORTED_MIME_TYPES = {
    "application/ogg",
    "application/octet-stream",
}

# One global heavy worker keeps Render CPU/RAM stable.
_PRIVATE_QUEUE: asyncio.Queue["PrivateJob"] = asyncio.Queue()
_PRIVATE_WORKER: asyncio.Task | None = None
_ACTIVE_JOB: "PrivateJob | None" = None
_QUEUED_CHAT_IDS: set[int] = set()


@dataclass(slots=True)
class PrivateJob:
    event: object
    client: object
    chat_id: int
    job_id: str


def ensure_media_dirs() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(").,!?'\"")


def is_private_cancel_command(text: str) -> bool:
    return (text or "").strip().lower() in {"/cancel", "/cencel", ".cancel", ".cencel"}


def is_internal_status_message(text: str, has_media: bool) -> bool:
    if has_media:
        return False

    normalized = (text or "").strip().lower()
    return normalized.startswith((
        "⏳",
        "✅",
        "❌",
        "⚠️",
        "⛔",
        "send an audio/video",
        "queued.",
        "nothing is processing",
    ))


def get_document(event):
    return getattr(getattr(event, "message", None), "document", None)


def get_document_mime(event) -> str:
    document = get_document(event)
    return (getattr(document, "mime_type", "") or "").lower()


def get_document_filename(event) -> str:
    document = get_document(event)
    if not document:
        return ""

    for attribute in getattr(document, "attributes", []):
        filename = getattr(attribute, "file_name", None)
        if filename:
            return filename

    return ""


def get_document_extension(event) -> str:
    filename = get_document_filename(event)
    if filename:
        return Path(filename).suffix.lower()

    document = get_document(event)
    ext = Path(getattr(document, "name", "") or "").suffix.lower() if document else ""
    return ext


def is_supported_path(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS


def is_supported_media_event(event) -> bool:
    if not getattr(getattr(event, "message", None), "media", None):
        return False

    mime = get_document_mime(event)
    extension = get_document_extension(event)

    if extension in SUPPORTED_MEDIA_EXTENSIONS:
        return True
    if mime.startswith(SUPPORTED_MIME_PREFIXES):
        return True
    if mime in SUPPORTED_MIME_TYPES:
        return True

    return False


def get_media_duration(event) -> int | None:
    document = get_document(event)
    if not document:
        return None

    for attribute in getattr(document, "attributes", []):
        duration = getattr(attribute, "duration", None)
        if duration:
            return int(duration)

    return None


def estimate_processing_seconds(event) -> int:
    duration = get_media_duration(event)
    if not duration:
        return VOCAL_PROCESS_ESTIMATE_SECONDS
    return max(VOCAL_PROCESS_ESTIMATE_SECONDS, min(1200, int(duration * 1.5)))


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_finish_time(seconds_from_now: int) -> str:
    finish_at = datetime.utcnow() + timedelta(
        hours=TZ_OFFSET,
        seconds=max(0, int(seconds_from_now)),
    )
    return finish_at.strftime("%H:%M")


def build_progress_bar(percent: int, width: int = 12) -> str:
    percent = max(0, min(100, int(percent)))
    filled = round(width * percent / 100)
    return f"[{'█' * filled}{'░' * (width - filled)}]"


def build_status_text(
    stage: str,
    elapsed_seconds: int,
    remaining_seconds: int | None = None,
    percent: int | None = None,
    estimated: bool = False,
) -> str:
    lines = [
        f"⏳ {stage}",
        f"Elapsed: {format_duration(elapsed_seconds)}",
    ]

    if percent is not None:
        label = "Estimated progress" if estimated else "Progress"
        clamped = max(0, min(100, int(percent)))
        lines.append(f"{label}: {build_progress_bar(clamped)} {clamped}%")

    if remaining_seconds is not None and remaining_seconds > 0:
        label = "Estimated remaining" if estimated else "Remaining"
        lines.append(f"{label}: {format_duration(remaining_seconds)}")
        lines.append(f"Approx. ready at {format_finish_time(remaining_seconds)}")
    elif remaining_seconds is not None:
        lines.append("Remaining: almost done")

    return "\n".join(lines)


class StatusReporter:
    def __init__(self, message, interval: int = VOCAL_PROGRESS_UPDATE_INTERVAL):
        self.message = message
        self.interval = max(1, int(interval))
        self.started_at = asyncio.get_running_loop().time()
        self.last_edit_at = 0.0
        self.stage = "Processing"
        self.remaining_seconds: int | None = None
        self.percent: int | None = None
        self.estimated = False
        self.finished = False
        self._lock = asyncio.Lock()

    def elapsed(self) -> int:
        return int(asyncio.get_running_loop().time() - self.started_at)

    def render(self) -> str:
        return build_status_text(
            self.stage,
            self.elapsed(),
            self.remaining_seconds,
            self.percent,
            self.estimated,
        )

    async def update(
        self,
        stage: str | None = None,
        remaining_seconds: int | None = None,
        percent: int | None = None,
        estimated: bool | None = None,
        force: bool = False,
    ) -> None:
        async with self._lock:
            if stage is not None:
                self.stage = stage
            if remaining_seconds is not None:
                self.remaining_seconds = remaining_seconds
            if percent is not None:
                self.percent = max(0, min(100, int(percent)))
            if estimated is not None:
                self.estimated = estimated

            now = asyncio.get_running_loop().time()
            if not force and now - self.last_edit_at < self.interval:
                return

            try:
                await self.message.edit(self.render())
                self.last_edit_at = now
            except Exception as exc:
                print(f"Status update failed: {exc}")

    def has_actual_progress(self, stage: str) -> bool:
        return self.stage == stage and self.percent is not None and not self.estimated

    async def tick(self) -> None:
        while not self.finished:
            await self.update(force=True)
            await asyncio.sleep(1)

    def finish(self) -> None:
        self.finished = True


async def run_command(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def calculate_file_hash_sync(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def calculate_file_hash(path: Path) -> str:
    return await asyncio.to_thread(calculate_file_hash_sync, path)


def get_cached_result(cache_key: str) -> Path | None:
    for suffix in (".mp3", ".wav"):
        cached_file = RESULT_CACHE_DIR / f"{cache_key}{suffix}"
        if cached_file.exists():
            return cached_file
    return None


async def save_cached_result(cache_key: str, result_file: Path) -> Path:
    cached_file = RESULT_CACHE_DIR / f"{cache_key}{result_file.suffix.lower()}"
    await asyncio.to_thread(shutil.copy2, result_file, cached_file)
    return cached_file


async def download_telegram_media(event, job_id: str, reporter: StatusReporter) -> Path | None:
    ensure_media_dirs()
    job_dir = DOWNLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def progress_callback(current: int, total: int) -> None:
        if not total:
            return

        percent = min(99, int(current / total * 100))
        elapsed = max(1, reporter.elapsed())
        remaining = max(0, int(elapsed / (current / total) - elapsed)) if current else None
        asyncio.create_task(
            reporter.update("Downloading file", remaining, percent)
        )

    downloaded = await event.message.download_media(
        file=str(job_dir),
        progress_callback=progress_callback,
    )
    if not downloaded:
        return None

    path = Path(downloaded)
    return path if is_supported_path(path) else None


async def download_url_media(url: str, job_id: str, reporter: StatusReporter) -> Path | None:
    ensure_media_dirs()
    job_dir = DOWNLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    await reporter.update("Downloading link", force=True)
    output_template = str(job_dir / "%(title).80s.%(ext)s")
    code, stdout, stderr = await run_command(
        "yt-dlp",
        "--no-playlist",
        "-f",
        "bestaudio[ext=m4a]/bestaudio/best",
        "-o",
        output_template,
        url,
    )
    if code != 0:
        print(f"yt-dlp failed: {stderr or stdout}")
        return None

    candidates = [
        path for path in job_dir.iterdir()
        if path.is_file() and is_supported_path(path)
    ]
    if not candidates:
        print(f"yt-dlp produced no supported media file for {url}")
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


async def run_estimated_progress(
    reporter: StatusReporter,
    stage: str,
    estimate_seconds: int,
) -> None:
    start = reporter.elapsed()
    while not reporter.finished:
        elapsed = reporter.elapsed() - start
        remaining = max(0, estimate_seconds - elapsed)
        percent = min(95, int(elapsed / estimate_seconds * 100)) if estimate_seconds else 0
        await reporter.update(stage, remaining, percent, estimated=True, force=True)
        await asyncio.sleep(max(1, VOCAL_PROGRESS_UPDATE_INTERVAL))


def parse_demucs_percent(text: str) -> int | None:
    matches = PERCENT_RE.findall(text)
    if not matches:
        return None
    value = max(int(match) for match in matches)
    return value if 0 <= value <= 100 else None


def estimate_remaining_from_percent(elapsed_seconds: int, percent: int) -> int | None:
    if percent <= 0:
        return None
    total_estimate = elapsed_seconds / (percent / 100)
    return max(0, int(total_estimate - elapsed_seconds))


async def read_demucs_stream(stream, reporter: StatusReporter, log_parts: list[str]) -> None:
    recent_text = ""
    last_percent = None

    while True:
        chunk = await stream.read(256)
        if not chunk:
            break

        text = chunk.decode("utf-8", errors="replace")
        log_parts.append(text)
        recent_text = (recent_text + text)[-1000:]

        percent = parse_demucs_percent(recent_text)
        if percent is None or percent == last_percent:
            continue

        last_percent = percent
        remaining = estimate_remaining_from_percent(reporter.elapsed(), percent)
        force = not reporter.has_actual_progress("Separating vocals") or percent >= 100
        await reporter.update("Separating vocals", remaining, percent, estimated=False, force=force)


def find_no_vocals_file(input_file: Path, job_output_dir: Path) -> Path | None:
    roots = [
        job_output_dir / "htdemucs",
        OUTPUTS_DIR / "htdemucs",
        Path("separated") / "htdemucs",
    ]

    for root in roots:
        preferred = root / input_file.stem / "no_vocals.wav"
        if preferred.exists():
            return preferred

        matches = list(root.glob("*/no_vocals.wav")) if root.exists() else []
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)

    return None


async def separate_vocals(input_file: Path, job_id: str, reporter: StatusReporter) -> Path | None:
    job_output_dir = OUTPUTS_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)

    await reporter.update("Starting Demucs", force=True)
    process = await asyncio.create_subprocess_exec(
        "demucs",
        "-n",
        "htdemucs",
        "--two-stems=vocals",
        "-o",
        str(job_output_dir),
        str(input_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    try:
        await asyncio.gather(
            read_demucs_stream(process.stdout, reporter, stdout_parts),
            read_demucs_stream(process.stderr, reporter, stderr_parts),
        )
        code = await process.wait()
    except asyncio.CancelledError:
        process.kill()
        with suppress(Exception):
            await process.wait()
        raise

    if code != 0:
        print(f"demucs failed: {''.join(stderr_parts) or ''.join(stdout_parts)}")
        return None

    return find_no_vocals_file(input_file, job_output_dir)


async def convert_wav_to_mp3(wav_file: Path, job_id: str, reporter: StatusReporter) -> Path:
    if wav_file.suffix.lower() != ".wav" or not shutil.which("ffmpeg"):
        return wav_file

    output_file = OUTPUTS_DIR / job_id / f"{wav_file.stem}.mp3"
    await reporter.update("Preparing result", force=True)
    code, stdout, stderr = await run_command(
        "ffmpeg",
        "-y",
        "-i",
        str(wav_file),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(output_file),
    )
    if code != 0 or not output_file.exists():
        print(f"ffmpeg conversion failed: {stderr or stdout}")
        return wav_file

    return output_file


async def send_audio_result(client, event, audio_file: Path, reporter: StatusReporter) -> None:
    def progress_callback(current: int, total: int) -> None:
        if not total:
            return

        percent = min(99, int(current / total * 100))
        elapsed = max(1, reporter.elapsed())
        remaining = max(0, int(elapsed / (current / total) - elapsed)) if current else None
        asyncio.create_task(
            reporter.update("Uploading result", remaining, percent)
        )

    await client.send_file(
        event.chat_id,
        file=str(audio_file),
        caption=DONE_MESSAGE,
        force_document=False,
        progress_callback=progress_callback,
        attributes=[
            types.DocumentAttributeAudio(
                duration=0,
                title="No vocals",
            )
        ],
    )


def cleanup_job_files(job_id: str, input_file: Path | None) -> None:
    paths = [DOWNLOADS_DIR / job_id, OUTPUTS_DIR / job_id]
    if input_file:
        paths.append(input_file)

    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except Exception as exc:
            print(f"Cleanup failed for {path}: {exc}")


async def process_private_job(job: PrivateJob) -> None:
    event = job.event
    client = job.client
    text = event.raw_text or ""
    url = extract_first_url(text)
    input_file: Path | None = None
    reporter: StatusReporter | None = None
    ticker_task: asyncio.Task | None = None
    estimated_task: asyncio.Task | None = None

    status_message = await event.respond(PROCESSING_MESSAGE)
    reporter = StatusReporter(status_message)
    ticker_task = asyncio.create_task(reporter.tick())

    try:
        if url:
            input_file = await download_url_media(url, job.job_id, reporter)
        else:
            input_file = await download_telegram_media(event, job.job_id, reporter)

        if not input_file:
            await event.respond(UNSUPPORTED_MESSAGE)
            await reporter.update("Unsupported or failed download", percent=100, force=True)
            return

        cache_key = await calculate_file_hash(input_file)
        cached_result = get_cached_result(cache_key)
        if cached_result:
            await reporter.update("Using cached result", percent=100, force=True)
            await asyncio.wait_for(
                send_audio_result(client, event, cached_result, reporter),
                timeout=VOCAL_SEND_TIMEOUT_SECONDS,
            )
            return

        estimate_seconds = estimate_processing_seconds(event)
        await reporter.update(
            "Separating vocals",
            remaining_seconds=estimate_seconds,
            percent=0,
            estimated=True,
            force=True,
        )
        estimated_task = asyncio.create_task(
            run_estimated_progress(reporter, "Separating vocals", estimate_seconds)
        )

        no_vocals = await asyncio.wait_for(
            separate_vocals(input_file, job.job_id, reporter),
            timeout=VOCAL_SEPARATION_TIMEOUT_SECONDS,
        )

        if estimated_task:
            estimated_task.cancel()
            with suppress(asyncio.CancelledError):
                await estimated_task

        if not no_vocals:
            await event.respond(ERROR_MESSAGE)
            await reporter.update("Demucs did not return output", percent=100, force=True)
            return

        result_file = await convert_wav_to_mp3(no_vocals, job.job_id, reporter)
        cached_file = await save_cached_result(cache_key, result_file)
        await reporter.update("Uploading result", percent=99, force=True)
        await asyncio.wait_for(
            send_audio_result(client, event, cached_file, reporter),
            timeout=VOCAL_SEND_TIMEOUT_SECONDS,
        )

        await reporter.update("Done", percent=100, force=True)
        with suppress(Exception):
            await status_message.delete()

    except asyncio.CancelledError:
        print("Private vocal remover job cancelled")
        if reporter:
            await reporter.update("Cancelled", percent=0, force=True)
        raise
    except Exception as exc:
        print(f"PRIVATE VOCAL REMOVER ERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        await event.respond(ERROR_MESSAGE)
        if reporter:
            await reporter.update(f"Error: {type(exc).__name__}", percent=100, force=True)
    finally:
        if estimated_task and not estimated_task.done():
            estimated_task.cancel()
            with suppress(asyncio.CancelledError):
                await estimated_task
        if ticker_task and not ticker_task.done():
            ticker_task.cancel()
            with suppress(asyncio.CancelledError):
                await ticker_task
        if reporter:
            reporter.finish()
        cleanup_job_files(job.job_id, input_file)


async def private_worker() -> None:
    global _ACTIVE_JOB, _PRIVATE_WORKER

    try:
        while True:
            job = await _PRIVATE_QUEUE.get()
            _ACTIVE_JOB = job
            _QUEUED_CHAT_IDS.discard(job.chat_id)

            try:
                await process_private_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"PRIVATE WORKER ERROR: {type(exc).__name__}: {exc}")
                traceback.print_exc()
            finally:
                _ACTIVE_JOB = None
                _PRIVATE_QUEUE.task_done()

            if _PRIVATE_QUEUE.empty():
                break
    finally:
        _PRIVATE_WORKER = None
        _ACTIVE_JOB = None


def ensure_worker_running() -> None:
    global _PRIVATE_WORKER
    if _PRIVATE_WORKER is None or _PRIVATE_WORKER.done():
        _PRIVATE_WORKER = asyncio.create_task(private_worker())


async def cancel_private_processing(event) -> None:
    global _PRIVATE_WORKER, _ACTIVE_JOB

    chat_id = event.chat_id
    active_for_chat = _ACTIVE_JOB is not None and _ACTIVE_JOB.chat_id == chat_id
    removed = 0

    kept_jobs: list[PrivateJob] = []
    while not _PRIVATE_QUEUE.empty():
        job = _PRIVATE_QUEUE.get_nowait()
        if job.chat_id == chat_id:
            removed += 1
            _QUEUED_CHAT_IDS.discard(chat_id)
        else:
            kept_jobs.append(job)
        _PRIVATE_QUEUE.task_done()

    for job in kept_jobs:
        await _PRIVATE_QUEUE.put(job)

    if active_for_chat and _PRIVATE_WORKER:
        _PRIVATE_WORKER.cancel()
        with suppress(asyncio.CancelledError):
            await _PRIVATE_WORKER

    if active_for_chat or removed:
        await event.respond(CANCELLED_MESSAGE)
    else:
        await event.respond(NOTHING_TO_CANCEL_MESSAGE)

    if not _PRIVATE_QUEUE.empty():
        ensure_worker_running()


async def enqueue_private_job(event, client) -> None:
    chat_id = event.chat_id
    if chat_id is None:
        return

    if chat_id in _QUEUED_CHAT_IDS:
        await event.respond("Queued. I will process it after the current file.")
    else:
        await event.respond("Queued. I will process it shortly.")

    _QUEUED_CHAT_IDS.add(chat_id)
    await _PRIVATE_QUEUE.put(
        PrivateJob(
            event=event,
            client=client,
            chat_id=chat_id,
            job_id=uuid.uuid4().hex,
        )
    )
    ensure_worker_running()


async def handle_private_vocal_remover(event, client) -> None:
    text = event.raw_text or ""
    has_media = bool(getattr(event.message, "media", None))

    # Userbots receive their own outgoing messages too. Private service should
    # process incoming user messages only, otherwise sent results can loop.
    if event.out:
        return

    if is_private_cancel_command(text):
        await cancel_private_processing(event)
        return

    if extract_first_url(text):
        await enqueue_private_job(event, client)
        return

    if has_media:
        if not is_supported_media_event(event):
            await event.respond(UNSUPPORTED_MESSAGE)
            return
        await enqueue_private_job(event, client)
        return

    await event.respond(INSTRUCTION_MESSAGE)
