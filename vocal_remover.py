import asyncio
import codecs
import hashlib
import re
import shutil
import uuid
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
import traceback

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


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PERCENT_RE = re.compile(r"(\d{1,3})%")
RESULT_CACHE_DIR = OUTPUTS_DIR / "cache"


def ensure_media_dirs():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None

    return match.group(0).rstrip(").,!?\"'")


def is_supported_media_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS


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
        seconds=max(0, int(seconds_from_now))
    )
    return finish_at.strftime("%H:%M")


def build_progress_bar(percent: int, width: int = 12) -> str:
    percent = max(0, min(100, int(percent)))
    filled = round(width * percent / 100)
    empty = width - filled
    return f"[{'в–€' * filled}{'в–‘' * empty}]"


def get_message_media_duration(event) -> int | None:
    document = getattr(event.message, "document", None)
    if not document:
        return None

    for attribute in getattr(document, "attributes", []):
        duration = getattr(attribute, "duration", None)
        if duration:
            return int(duration)

    return None


def estimate_processing_seconds(event) -> int:
    media_duration = get_message_media_duration(event)
    if not media_duration:
        return VOCAL_PROCESS_ESTIMATE_SECONDS

    return max(
        VOCAL_PROCESS_ESTIMATE_SECONDS,
        min(1200, int(media_duration * 1.5))
    )


def build_stage_text(
    stage: str,
    elapsed_seconds: int = 0,
    remaining_seconds: int | None = None,
    percent: int | None = None,
    estimated: bool = False,
) -> str:
    lines = [
        f"⏳ {stage}",
        f"Прошло: {format_duration(elapsed_seconds)}",
    ]

    if percent is not None:
        label = "Примерный прогресс" if estimated else "Прогресс"
        clamped = max(0, min(100, percent))
        lines.append(f"{label}: {build_progress_bar(clamped)} {clamped}%")

    if remaining_seconds is not None and remaining_seconds > 0:
        label = "Примерно осталось" if estimated else "Осталось"
        lines.append(f"{label}: {format_duration(remaining_seconds)}")
        lines.append(f"Готово примерно в {format_finish_time(remaining_seconds)}")
    elif remaining_seconds is not None:
        lines.append("Осталось: ещё немного")

    return "\n".join(lines)




class StatusReporter:
    def __init__(self, status_message, update_interval: int = VOCAL_PROGRESS_UPDATE_INTERVAL):
        self.status_message = status_message
        self.update_interval = update_interval
        self.started_at = asyncio.get_running_loop().time()
        self.last_edit_at = 0.0
        self.stage = "РћР±СЂР°Р±Р°С‚С‹РІР°СЋ"
        self.remaining_seconds = None
        self.percent = None
        self.estimated = False
        self.finished = False
        self._lock = asyncio.Lock()

    def elapsed(self) -> int:
        return int(asyncio.get_running_loop().time() - self.started_at)

    def _render(self) -> str:
        return build_stage_text(
            self.stage,
            self.elapsed(),
            self.remaining_seconds,
            self.percent,
            self.estimated,
        )

    async def set_state(
        self,
        stage: str | None = None,
        remaining_seconds: int | None = None,
        percent: int | None = None,
        estimated: bool | None = None,
        force: bool = False,
    ):
        async with self._lock:
            if stage is not None:
                self.stage = stage
            if remaining_seconds is not None:
                self.remaining_seconds = remaining_seconds
            if percent is not None:
                self.percent = max(0, min(100, percent))
            if estimated is not None:
                self.estimated = estimated

            now = asyncio.get_running_loop().time()
            if not force and now - self.last_edit_at < self.update_interval:
                return

            try:
                await self.status_message.edit(self._render())
                self.last_edit_at = now
            except Exception as e:
                print(f"Status update failed: {e}")

    async def update(
        self,
        stage: str | None = None,
        remaining_seconds: int | None = None,
        percent: int | None = None,
        estimated: bool | None = None,
        force: bool = False,
    ):
        await self.set_state(
            stage=stage,
            remaining_seconds=remaining_seconds,
            percent=percent,
            estimated=estimated,
            force=force,
        )

    def has_actual_progress(self, stage: str) -> bool:
        return self.stage == stage and self.percent is not None and not self.estimated

    async def tick(self):
        while not self.finished:
            await self.set_state(force=True)
            await asyncio.sleep(1)

    def finish(self):
        self.finished = True


async def run_estimated_progress(reporter: StatusReporter, stage: str, estimate_seconds: int):
    start = reporter.elapsed()

    while not reporter.finished:
        elapsed_seconds = reporter.elapsed() - start
        remaining_seconds = max(0, estimate_seconds - elapsed_seconds)
        percent = min(95, int(elapsed_seconds / estimate_seconds * 100)) if estimate_seconds else None
        await reporter.set_state(stage=stage, remaining_seconds=remaining_seconds, percent=percent, estimated=True, force=True)
        await asyncio.sleep(VOCAL_PROGRESS_UPDATE_INTERVAL)


def estimate_remaining_from_percent(elapsed_seconds: int, percent: int) -> int | None:
    if percent <= 0:
        return None

    total_estimate = elapsed_seconds / (percent / 100)
    return max(0, int(total_estimate - elapsed_seconds))


def parse_demucs_percent(text: str) -> int | None:
    matches = PERCENT_RE.findall(text)
    if not matches:
        return None

    value = max(int(match) for match in matches)
    if 0 <= value <= 100:
        return value

    return None

async def convert_wav_to_mp3(wav_file: Path, job_id: str, reporter: StatusReporter | None = None) -> Path:
    if wav_file.suffix.lower() != ".wav" or not shutil.which("ffmpeg"):
        return wav_file

    output_file = OUTPUTS_DIR / job_id / f"{wav_file.stem}.mp3"

    if reporter:
        await reporter.update("РЎР¶РёРјР°СЋ СЂРµР·СѓР»СЊС‚Р°С‚", force=True)

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
        print(f"ffmpeg mp3 conversion failed: {stderr or stdout}")
        return wav_file

    return output_file

async def run_command(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace")
    )


async def download_telegram_media(event, job_id: str, reporter: StatusReporter | None = None) -> Path | None:
    ensure_media_dirs()
    job_download_dir = DOWNLOADS_DIR / job_id
    job_download_dir.mkdir(parents=True, exist_ok=True)

    def progress_callback(current: int, total: int):
        if not reporter or not total:
            return

        percent = min(99, int(current / total * 100))
        remaining = None
        if current > 0:
            elapsed = max(1, reporter.elapsed())
            total_estimate = elapsed / (current / total)
            remaining = max(0, int(total_estimate - elapsed))

        asyncio.create_task(
            reporter.update("РЎРєР°С‡РёРІР°СЋ С„Р°Р№Р»", remaining, percent)
        )

    downloaded = await event.message.download_media(
        file=str(job_download_dir),
        progress_callback=progress_callback
    )
    if not downloaded:
        return None

    path = Path(downloaded)
    if not is_supported_media_file(path):
        return None

    return path


async def download_url_media(url: str, job_id: str, reporter: StatusReporter | None = None) -> Path | None:
    ensure_media_dirs()
    job_download_dir = DOWNLOADS_DIR / job_id
    job_download_dir.mkdir(parents=True, exist_ok=True)

    if reporter:
        await reporter.update("РЎРєР°С‡РёРІР°СЋ РїРѕ СЃСЃС‹Р»РєРµ", force=True)

    output_template = str(job_download_dir / "%(title).80s.%(ext)s")
    code, stdout, stderr = await run_command(
        "yt-dlp",
        "--no-playlist",
        "-f",
        "bestaudio[ext=m4a]/bestaudio/best",
        "-o",
        output_template,
        url
    )
    if code != 0:
        print(f"yt-dlp failed: {stderr or stdout}")
        return None

    candidates = [
        path for path in job_download_dir.iterdir()
        if path.is_file() and is_supported_media_file(path)
    ]
    if not candidates:
        print(f"yt-dlp produced no supported file for {url}")
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_no_vocals_file(input_file: Path, job_output_dir: Path) -> Path | None:
    search_roots = [
        job_output_dir / "htdemucs",
        OUTPUTS_DIR / "htdemucs",
        Path("separated") / "htdemucs",
    ]

    preferred_track_dir = input_file.stem
    for root in search_roots:
        preferred = root / preferred_track_dir / "no_vocals.wav"
        if preferred.exists():
            return preferred

        matches = list(root.glob("*/no_vocals.wav")) if root.exists() else []
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)

    return None


async def read_demucs_stream(stream, reporter: StatusReporter | None, log_parts: list[str]):
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    recent_text = ""
    last_percent = None

    while True:
        chunk = await stream.read(128)
        if not chunk:
            break

        text = decoder.decode(chunk)
        log_parts.append(text)

        if not reporter:
            continue

        recent_text = (recent_text + text)[-1000:]
        percent = parse_demucs_percent(recent_text)
        if percent is None or percent == last_percent:
            continue

        last_percent = percent
        remaining = estimate_remaining_from_percent(reporter.elapsed(), percent)
        is_first_actual_progress = not reporter.has_actual_progress("Р Р°Р·РґРµР»СЏСЋ РІРѕРєР°Р»")
        await reporter.update(
            "Р Р°Р·РґРµР»СЏСЋ РІРѕРєР°Р»",
            remaining,
            percent,
            force=is_first_actual_progress or percent >= 100,
        )

    tail = decoder.decode(b"", final=True)
    if tail:
        log_parts.append(tail)


async def separate_vocals(input_file: Path, job_id: str, reporter: StatusReporter | None = None) -> Path | None:
    job_output_dir = OUTPUTS_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)

    if reporter:
        await reporter.update("Р Р°Р·РґРµР»СЏСЋ РІРѕРєР°Р»", force=True)

    process = await asyncio.create_subprocess_exec(
        "demucs",
        "-n",
        "htdemucs",
        "--two-stems=vocals",
        "-o",
        str(job_output_dir),
        str(input_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
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
        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        print(f"demucs failed: {stderr or stdout}")
        return None

    return find_no_vocals_file(input_file, job_output_dir)


async def send_audio_result(client, event, audio_file: Path, reporter: StatusReporter | None = None):
    def progress_callback(current: int, total: int):
        if not reporter or not total:
            return

        percent = min(99, int(current / total * 100))
        remaining = None
        if current > 0:
            elapsed = max(1, reporter.elapsed())
            total_estimate = elapsed / (current / total)
            remaining = max(0, int(total_estimate - elapsed))

        asyncio.create_task(
            reporter.update("РћС‚РїСЂР°РІР»СЏСЋ СЂРµР·СѓР»СЊС‚Р°С‚", remaining, percent)
        )

    await client.send_file(
        event.chat_id,
        file=str(audio_file),
        caption="Р“РѕС‚РѕРІРѕ рџЋ§",
        force_document=False,
        progress_callback=progress_callback,
        attributes=[
            types.DocumentAttributeAudio(
                duration=0,
                title="No vocals"
            )
        ]
    )


def cleanup_job_files(job_id: str, input_file: Path | None):
    paths_to_remove = [
        DOWNLOADS_DIR / job_id,
        OUTPUTS_DIR / job_id,
    ]

    if input_file:
        paths_to_remove.append(input_file)

    for path in paths_to_remove:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except Exception as e:
            print(f"Cleanup failed for {path}: {e}")


async def report_vocal_error(event, reporter: StatusReporter | None, user_message: str, log_message: str):
    print(log_message)
    if reporter:
        await reporter.set_state(stage=f"РћС€РёР±РєР°: {user_message}", percent=100, force=True)
        reporter.finish()
    await event.respond(user_message)


def is_internal_status_message(text: str, has_media: bool) -> bool:
    if has_media:
        return False

    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    return normalized.startswith((
        "вЏі ",
        "РѕС€РёР±РєР°",
        "РіРѕС‚РѕРІРѕ",
        "СЃС‚Р°СЂС‚:",
        "СЃРєР°С‡РёРІР°СЋ",
        "СЂР°Р·РґРµР»СЏСЋ",
        "РѕС‚РїСЂР°РІР»СЏСЋ",
        "РЅР°С€С‘Р»",
    ))


_PRIVATE_JOB_QUEUES: dict[int, asyncio.Queue] = {}
_PRIVATE_JOB_WORKERS: dict[int, asyncio.Task] = {}


def is_private_cancel_command(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"/cencel", "/cancel", ".cencel", ".cancel"}


def _clear_private_queue(chat_id: int) -> int:
    queue = _PRIVATE_JOB_QUEUES.get(chat_id)
    if not queue:
        return 0

    cleared = 0
    while True:
        try:
            queue.get_nowait()
            queue.task_done()
            cleared += 1
        except asyncio.QueueEmpty:
            break

    return cleared


async def cancel_private_processing(event) -> bool:
    chat_id = event.chat_id
    if chat_id is None:
        return False

    worker = _PRIVATE_JOB_WORKERS.get(chat_id)
    queue = _PRIVATE_JOB_QUEUES.get(chat_id)
    has_active_job = worker is not None and not worker.done()
    has_pending_jobs = bool(queue and not queue.empty())

    if not has_active_job and not has_pending_jobs:
        await event.respond("Сейчас ничего не обрабатываю.")
        return True

    cleared = _clear_private_queue(chat_id)

    if has_active_job:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker

    _PRIVATE_JOB_QUEUES.pop(chat_id, None)
    _PRIVATE_JOB_WORKERS.pop(chat_id, None)

    await event.respond(f"⛔ Обработка отменена. Очередь очищена ({cleared} задач).")
    return True


async def _process_private_vocal_remover(event, client):
    status_message = None
    input_file = None
    reporter = None
    ticker_task = None
    estimated_task = None
    job_id = uuid.uuid4().hex

    try:
        text = event.raw_text or ""
        url = extract_first_url(text)

        if event.message.media:
            status_message = await event.respond("вЏі РЎС‚Р°СЂС‚: С„Р°Р№Р» РїРѕР»СѓС‡РµРЅ")
            reporter = StatusReporter(status_message)
            ticker_task = asyncio.create_task(reporter.tick())
            await reporter.set_state(stage="РЎРєР°С‡РёРІР°СЋ С„Р°Р№Р»", force=True)
            input_file = await download_telegram_media(event, job_id, reporter)
        elif url:
            status_message = await event.respond("вЏі РЎС‚Р°СЂС‚: СЃСЃС‹Р»РєР° РїРѕР»СѓС‡РµРЅР°")
            reporter = StatusReporter(status_message)
            ticker_task = asyncio.create_task(reporter.tick())
            await reporter.set_state(stage="РЎРєР°С‡РёРІР°СЋ РїРѕ СЃСЃС‹Р»РєРµ", force=True)
            input_file = await download_url_media(url, job_id, reporter)
        else:
            return

        if not input_file:
            await report_vocal_error(
                event,
                reporter,
                "Р¤Р°Р№Р» РЅРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ",
                "PRIVATE VOCAL REMOVER ERROR: download step returned empty input_file",
            )
            return

        cache_key = await calculate_file_hash(input_file)
        cached_result = get_cached_result(cache_key)
        if cached_result:
            if reporter:
                await reporter.set_state(stage="РќР°С€С‘Р» РіРѕС‚РѕРІС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚ РІ РєСЌС€Рµ", percent=100, force=True)
            try:
                await asyncio.wait_for(
                    send_audio_result(client, event, cached_result, reporter),
                    timeout=VOCAL_SEND_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                await report_vocal_error(
                    event,
                    reporter,
                    "Telegram СЃР»РёС€РєРѕРј РґРѕР»РіРѕ РїСЂРёРЅРёРјР°Р» РєСЌС€РёСЂРѕРІР°РЅРЅС‹Р№ С„Р°Р№Р»",
                    "PRIVATE VOCAL REMOVER ERROR: cached upload timeout",
                )
                return
            return

        if reporter:
            estimate_seconds = estimate_processing_seconds(event)
            await reporter.set_state(stage="Р Р°Р·РґРµР»СЏСЋ РІРѕРєР°Р»", remaining_seconds=estimate_seconds, percent=0, estimated=True, force=True)
            estimated_task = asyncio.create_task(
                run_estimated_progress(reporter, "Р Р°Р·РґРµР»СЏСЋ РІРѕРєР°Р»", estimate_seconds)
            )

        try:
            no_vocals = await asyncio.wait_for(
                separate_vocals(input_file, job_id, reporter),
                timeout=VOCAL_SEPARATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await report_vocal_error(
                event,
                reporter,
                "РћР±СЂР°Р±РѕС‚РєР° СЃР»РёС€РєРѕРј РґРѕР»РіРѕ РЅРµ Р·Р°РІРµСЂС€Р°Р»Р°СЃСЊ",
                "PRIVATE VOCAL REMOVER ERROR: demucs timeout",
            )
            return

        if estimated_task:
            estimated_task.cancel()
            with suppress(asyncio.CancelledError):
                await estimated_task

        if not no_vocals:
            await report_vocal_error(
                event,
                reporter,
                "Demucs РЅРµ РІРµСЂРЅСѓР» СЂР°Р·РґРµР»С‘РЅРЅС‹Р№ С„Р°Р№Р»",
                "PRIVATE VOCAL REMOVER ERROR: no no_vocals.wav found after demucs",
            )
            return

        result_file = await convert_wav_to_mp3(no_vocals, job_id, reporter)
        result_file = await save_cached_result(cache_key, result_file)

        if reporter:
            await reporter.set_state(stage="РћС‚РїСЂР°РІР»СЏСЋ РіРѕС‚РѕРІС‹Р№ С„Р°Р№Р»", percent=99, force=True)

        try:
            await asyncio.wait_for(
                send_audio_result(client, event, result_file, reporter),
                timeout=VOCAL_SEND_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await report_vocal_error(
                event,
                reporter,
                "Telegram СЃР»РёС€РєРѕРј РґРѕР»РіРѕ РїСЂРёРЅРёРјР°Р» РіРѕС‚РѕРІС‹Р№ С„Р°Р№Р»",
                "PRIVATE VOCAL REMOVER ERROR: final upload timeout",
            )
            return

        if reporter:
            await reporter.set_state(stage="Р“РѕС‚РѕРІРѕ, С„Р°Р№Р» РѕС‚РїСЂР°РІР»РµРЅ", percent=100, force=True)
            reporter.finish()

        if status_message:
            try:
                await status_message.delete()
            except Exception:
                pass

    except Exception as e:
        print(f"PRIVATE VOCAL REMOVER ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        if reporter:
            await reporter.set_state(stage=f"РћС€РёР±РєР°: {type(e).__name__}", percent=100, force=True)
            reporter.finish()
        await event.respond(f"РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё: {type(e).__name__}")

    except asyncio.CancelledError:
        print("PRIVATE VOCAL REMOVER: cancelled by user")
        if reporter:
            with suppress(Exception):
                await reporter.set_state(stage="⛔ Отменено", percent=0, force=True)
            reporter.finish()
        raise

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

        cleanup_job_files(job_id, input_file)


async def _private_worker(chat_id: int, client):
    queue = _PRIVATE_JOB_QUEUES.get(chat_id)
    if queue is None:
        return

    try:
        while True:
            event = await queue.get()
            try:
                await _process_private_vocal_remover(event, client)
            except Exception as e:
                print(f"PRIVATE WORKER ERROR: {type(e).__name__}: {e}")
                traceback.print_exc()
            finally:
                queue.task_done()

            if queue.empty():
                break
    finally:
        _PRIVATE_JOB_QUEUES.pop(chat_id, None)
        _PRIVATE_JOB_WORKERS.pop(chat_id, None)


async def _enqueue_private_job(event, client):
    chat_id = event.chat_id
    if chat_id is None:
        return

    if event.out:
        return

    queue = _PRIVATE_JOB_QUEUES.get(chat_id)
    worker = _PRIVATE_JOB_WORKERS.get(chat_id)
    is_busy = worker is not None and not worker.done()

    if queue is None:
        queue = asyncio.Queue()
        _PRIVATE_JOB_QUEUES[chat_id] = queue

    await queue.put(event)

    if is_busy:
        try:
            await event.respond("⏳ Уже обрабатываю предыдущий файл. Это сообщение добавил в очередь.")
        except Exception as e:
            print(f"PRIVATE QUEUE NOTICE FAILED: {e}")
        return

    worker = asyncio.create_task(_private_worker(chat_id, client))
    _PRIVATE_JOB_WORKERS[chat_id] = worker
    try:
        await event.respond("⏳ Принял файл. Начинаю обработку.")
    except Exception as e:
        print(f"PRIVATE START NOTICE FAILED: {e}")


async def handle_private_vocal_remover(event, client):
    text = event.raw_text or ""
    if is_private_cancel_command(text):
        await cancel_private_processing(event)
        return

    await _enqueue_private_job(event, client)
