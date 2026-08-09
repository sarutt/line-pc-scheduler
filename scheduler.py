"""
scheduler.py — ตัวหลัก: อ่านตารางข้อความจาก config.yaml แล้วส่งอัตโนมัติตามเวลา
รันค้างไว้:  python scheduler.py   (ปิดด้วย Ctrl+C)
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config_util import load_config, resolve_targets, setup_logging
from line_controller import LineController

log = logging.getLogger("scheduler")

# แปลงค่า days ใน config -> รูปแบบ day_of_week ของ APScheduler
_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _normalize_days(days) -> str:
    if days is None:
        return "*"
    d = str(days).strip().lower()
    if d in ("", "*", "all", "everyday", "ทุกวัน"):
        return "*"
    # รองรับทั้ง "mon-fri", "mon,wed,fri", "mon"
    return d


def _parse_time(t: str):
    hh, mm = str(t).strip().split(":")
    return int(hh), int(mm)


def make_job(ctrl: LineController, text: str, image="", order: str = "image_first", targets=None):
    targets = targets or [{"name": ctrl.target_name, "chat_row": ctrl.coords.get("chat_row")}]

    def _job():
        for t in targets:
            try:
                ctrl.send(text, image, order,
                          chat_row=t.get("chat_row"), target_name=t.get("name"))
            except Exception:  # noqa: BLE001
                log.exception("ส่งล้มเหลว: กลุ่ม=%r text=%r image=%r",
                              t.get("name"), text[:40], image)
    return _job


def _window_triggers(sh, sm, eh, em, every, dow, tz):
    """สร้าง CronTrigger สำหรับ 'ช่วงเวลา [sh:sm .. eh:em] ส่งทุก every นาที'
    รองรับกรณีนาทีเริ่ม/จบเป็น 0 และ every หาร 60 ลงตัว (เช่น 2,3,5,10,15,20,30)
    """
    triggers = []
    if sm == 0 and em == 0 and every > 0 and 60 % every == 0:
        # ชั่วโมงเต็ม sh..(eh-1) ยิงทุก every นาที (sh:00 .. (eh-1):(60-every))
        if eh - 1 >= sh:
            triggers.append(CronTrigger(
                day_of_week=dow, hour=f"{sh}-{eh - 1}",
                minute=f"*/{every}", timezone=tz))
        # บวกจุดสิ้นสุดพอดี eh:00
        triggers.append(CronTrigger(
            day_of_week=dow, hour=eh, minute=0, timezone=tz))
    else:
        # fallback ทั่วไป: ยิงทุก every นาทีในช่วงชั่วโมง sh..eh (อาจคลาดจากขอบเล็กน้อย)
        log.warning(
            "ช่วงเวลา %02d:%02d-%02d:%02d every=%d ไม่เข้าเงื่อนไขแบบตรงเป๊ะ "
            "ใช้โหมดประมาณ (ยิงทุก %d นาที ในชั่วโมง %d-%d)",
            sh, sm, eh, em, every, every, sh, eh)
        triggers.append(CronTrigger(
            day_of_week=dow, hour=f"{sh}-{eh}",
            minute=f"*/{every}", timezone=tz))
    return triggers


def main() -> None:
    setup_logging()
    cfg = load_config()
    tz = cfg.get("timezone", "Asia/Bangkok")
    ctrl = LineController(cfg)

    scheduler = BlockingScheduler(timezone=tz)
    messages = cfg.get("messages", []) or []

    if not messages:
        log.warning("ไม่มีข้อความใน config.yaml -> messages")

    count = 0
    for i, m in enumerate(messages, start=1):
        text = m.get("text", "")
        image = m.get("image", "")
        if not text and not image:
            log.warning("ข้าม message #%d (ไม่มี text หรือ image)", i)
            continue
        dow = _normalize_days(m.get("days"))
        order = m.get("order", "image_first")
        targets = resolve_targets(cfg, m.get("targets"))
        job = make_job(ctrl, text, image, order, targets)
        _nimg = len(image) if isinstance(image, (list, tuple)) else (
            len(str(image).splitlines()) if image else 0)
        label = text[:20] if text else f"[{_nimg} รูป]"

        # โหมดช่วงเวลา + ทุก N นาที: ต้องมี start, end, every_minutes
        if m.get("start") and m.get("end") and m.get("every_minutes"):
            sh, sm = _parse_time(m["start"])
            eh, em = _parse_time(m["end"])
            every = int(m["every_minutes"])
            triggers = _window_triggers(sh, sm, eh, em, every, dow, tz)
            for j, trig in enumerate(triggers):
                scheduler.add_job(
                    job, trigger=trig, id=f"msg_{i}_{j}",
                    name=f"{m['start']}-{m['end']}/{every}m [{dow}] {label}",
                    misfire_grace_time=60, coalesce=True, max_instances=1,
                )
            count += 1
            log.info("ตั้งเวลา #%d: ช่วง %s-%s ทุก %d นาที วัน=%s -> %r",
                     i, m["start"], m["end"], every, dow, text[:30])

        # โหมดเวลาเดียว: ต้องมี time
        elif m.get("time"):
            hour, minute = _parse_time(m["time"])
            trigger = CronTrigger(day_of_week=dow, hour=hour, minute=minute, timezone=tz)
            scheduler.add_job(
                job, trigger=trigger, id=f"msg_{i}",
                name=f"{m['time']} [{dow}] {label}",
                misfire_grace_time=300, coalesce=True, max_instances=1,
            )
            count += 1
            log.info("ตั้งเวลา #%d: %s วัน=%s -> %r", i, m["time"], dow, text[:30])

        else:
            log.warning("ข้าม message #%d (ต้องมี 'time' หรือ 'start+end+every_minutes')", i)

    log.info("เริ่มทำงาน: ตั้งเวลาไว้ %d รายการ (timezone=%s). กด Ctrl+C เพื่อหยุด", count, tz)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("หยุดการทำงาน")


if __name__ == "__main__":
    main()
