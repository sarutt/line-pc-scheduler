"""
app.py — หน้าเว็บ UI (dashboard) สำหรับ LINE PC Scheduler
รัน:  python app.py   แล้วเปิดเบราว์เซอร์ที่ http://127.0.0.1:5000

ทำอะไรได้:
  - ตั้งค่า config (timezone / window / coords / delays / ตารางข้อความ) ผ่านฟอร์ม
  - Start / Stop ตัวตั้งเวลา (ในตัวแอปนี้เอง)
  - ส่งข้อความทดสอบทันที
  - ดูสถานะ: กำลังรัน, รอบถัดไป, ส่งไปแล้ววันนี้, ผลล่าสุด
  - ดู log สด

หมายเหตุ: ให้รัน "แอปนี้" หรือ "scheduler.py" อย่างใดอย่างหนึ่ง อย่ารันพร้อมกัน (จะส่งซ้ำ)
"""

import datetime as dt
import logging
import os
import threading
from collections import deque

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, render_template, request

from config_util import (CONFIG_PATH, LOG_PATH, load_config, resolve_targets,
                         setup_logging)
from line_controller import LineController
from scheduler import _normalize_days, _parse_time, _window_triggers

setup_logging()
log = logging.getLogger("app")

app = Flask(__name__)

# ---------- สถานะรวม ----------
_send_lock = threading.Lock()          # กันส่งซ้อนกัน (pyautogui ยึดเมาส์)
_cancel = threading.Event()            # ตั้งเมื่อกดหยุด -> ให้การส่งที่ค้างอยู่เลิกกลางคัน
EVENTS = deque(maxlen=300)             # ประวัติการส่งล่าสุด
STATE = {"running": False}

_cfg = load_config()
_ctrl = LineController(_cfg)
_scheduler = BackgroundScheduler(timezone=_cfg.get("timezone", "Asia/Bangkok"))


# ---------- helper ----------
def _record(status: str, text: str, error: str = "") -> None:
    EVENTS.appendleft({
        "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "text": text[:60],
        "error": error,
    })


def _do_send(text: str, image="", order: str = "image_first", targets=None) -> None:
    """ส่งจริงพร้อม lock + บันทึกผล ; targets = [{name, chat_row}] (ว่าง=ทุกกลุ่มที่นิยาม)"""
    if not targets:
        targets = resolve_targets(_cfg, None)
    _nimg = len(image) if isinstance(image, (list, tuple)) else (
        len(str(image).splitlines()) if image else 0)
    base = text if text else f"[{_nimg} รูป]"
    with _send_lock:
        for t in targets:
            if _cancel.is_set():
                log.info("ยกเลิกการส่งที่เหลือ (กดหยุด)")
                _record("stopped", f"{base} — ยกเลิกก่อนถึงกลุ่มถัดไป")
                break
            gname = t.get("name") or "(กลุ่มเริ่มต้น)"
            label = f"{base} → {gname}"
            try:
                _ctrl.send(text, image, order,
                           chat_row=t.get("chat_row"), target_name=t.get("name"),
                           should_stop=_cancel.is_set)
                _record("stopped" if _cancel.is_set() else "success", label)
            except Exception as exc:  # noqa: BLE001
                log.exception("ส่งล้มเหลว: กลุ่ม=%s", gname)
                _record("error", label, str(exc))


def _make_job(text: str, image="", order: str = "image_first", targets=None):
    def _job():
        _do_send(text, image, order, targets)
    return _job


def _rebuild_jobs() -> int:
    """โหลด config ปัจจุบันไปสร้าง job ใหม่ทั้งหมด ; คืนจำนวน message"""
    _scheduler.remove_all_jobs()
    tz = _cfg.get("timezone", "Asia/Bangkok")
    count = 0
    for i, m in enumerate(_cfg.get("messages", []) or [], start=1):
        text = m.get("text", "")
        image = m.get("image", "")
        if not text and not image:
            continue
        dow = _normalize_days(m.get("days"))
        targets = resolve_targets(_cfg, m.get("targets"))
        job = _make_job(text, image, m.get("order", "image_first"), targets)
        if m.get("start") and m.get("end") and m.get("every_minutes"):
            sh, sm = _parse_time(m["start"])
            eh, em = _parse_time(m["end"])
            every = int(m["every_minutes"])
            for j, trig in enumerate(_window_triggers(sh, sm, eh, em, every, dow, tz)):
                _scheduler.add_job(job, trigger=trig, id=f"msg_{i}_{j}",
                                   max_instances=1, coalesce=True, misfire_grace_time=60)
            count += 1
        elif m.get("time"):
            hh, mm = _parse_time(m["time"])
            _scheduler.add_job(job, CronTrigger(day_of_week=dow, hour=hh, minute=mm, timezone=tz),
                               id=f"msg_{i}", max_instances=1, coalesce=True, misfire_grace_time=300)
            count += 1
    return count


def _next_run():
    times = [j.next_run_time for j in _scheduler.get_jobs() if j.next_run_time]
    if not times:
        return None
    return min(times).strftime("%Y-%m-%d %H:%M:%S")


def _sent_today() -> int:
    today = dt.date.today().strftime("%Y-%m-%d")
    return sum(1 for e in EVENTS if e["status"] == "success" and e["ts"].startswith(today))


def _save_config(new_cfg: dict) -> None:
    """เขียน config.yaml (จัดลำดับคีย์ให้อ่านง่าย, รองรับ unicode)"""
    ordered = {
        "timezone": new_cfg.get("timezone", "Asia/Bangkok"),
        "line": new_cfg.get("line", {}),
        "messages": new_cfg.get("messages", []),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("# แก้ผ่านหน้า UI (app.py) — ดูคำอธิบายเต็มที่ config.example.yaml\n")
        yaml.safe_dump(ordered, f, allow_unicode=True, sort_keys=False)


# ---------- routes ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify({
        "running": STATE["running"],
        "next_run": _next_run(),
        "job_count": len(_scheduler.get_jobs()),
        "sent_today": _sent_today(),
        "last": EVENTS[0] if EVENTS else None,
        "events": list(EVENTS)[:50],
        "timezone": _cfg.get("timezone", "Asia/Bangkok"),
    })


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(_cfg)


@app.route("/api/config", methods=["POST"])
def api_set_config():
    global _cfg, _ctrl
    try:
        data = request.get_json(force=True)
        # sanity check ขั้นต่ำ
        if "line" not in data or "messages" not in data:
            return jsonify({"ok": False, "error": "โครงสร้าง config ไม่ครบ (line/messages)"}), 400
        _save_config(data)
        _cfg = load_config()
        _ctrl = LineController(_cfg)
        n = _rebuild_jobs()
        return jsonify({"ok": True, "message": f"บันทึกแล้ว ตั้งเวลา {n} รายการ"})
    except Exception as exc:  # noqa: BLE001
        log.exception("บันทึก config ล้มเหลว")
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/start", methods=["POST"])
def api_start():
    _cancel.clear()          # ล้างธงยกเลิกก่อนเริ่ม
    _rebuild_jobs()
    _scheduler.resume()
    STATE["running"] = True
    log.info("UI: เริ่มตัวตั้งเวลา")
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    _cancel.set()            # สั่งให้การส่งที่ค้างอยู่เลิกกลางคันทันที
    _scheduler.pause()       # กันรอบใหม่
    STATE["running"] = False
    log.info("UI: หยุดตัวตั้งเวลา (สั่งยกเลิกงานที่ค้าง)")
    return jsonify({"ok": True})


@app.route("/api/send_now", methods=["POST"])
def api_send_now():
    data = request.get_json(silent=True) or {}
    image = data.get("image") or ""
    text = data.get("text")
    order = data.get("order") or "image_first"
    targets = resolve_targets(_cfg, data.get("targets"))
    if not text and not image:
        text = "ทดสอบระบบ"
    _cancel.clear()   # ให้ส่งทดสอบได้เสมอ แม้เพิ่งกดหยุดมาก่อน
    threading.Thread(target=_do_send, args=(text or "", image, order, targets), daemon=True).start()
    n = len(targets)
    return jsonify({"ok": True, "message": f"กำลังส่ง {n} กลุ่ม (ดูผลในตารางประวัติ)"})


@app.route("/api/pick_images", methods=["POST"])
def api_pick_images():
    """เปิด File dialog ของ Windows ให้เลือกรูป (คืนพาธเต็ม) — ทำงานฝั่งเครื่องที่รันแอป"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        paths = filedialog.askopenfilenames(
            title="เลือกรูป (เลือกได้หลายไฟล์)",
            filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("ทุกไฟล์", "*.*")],
        )
        root.destroy()
        return jsonify({"ok": True, "paths": list(paths)})
    except Exception as exc:  # noqa: BLE001
        log.exception("เลือกไฟล์รูปล้มเหลว")
        return jsonify({"ok": False, "error": str(exc), "paths": []}), 500


@app.route("/api/targets")
def api_targets():
    """รายชื่อกลุ่มเป้าหมายที่นิยามไว้ (ให้ UI เอาไปทำ dropdown)"""
    return jsonify({"targets": resolve_targets(_cfg, None)})


@app.route("/api/pick_position", methods=["POST"])
def api_pick_position():
    """เครื่องมือชี้ตำแหน่ง: จัดหน้าต่าง LINE แล้วให้ผู้ใช้คลิกกลุ่ม -> คืนพิกัดแถว [x, y]"""
    if not _send_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "กำลังส่งอยู่ ลองใหม่ภายหลัง"}), 409
    try:
        pos = _ctrl.capture_click_position(timeout=20)
    except Exception as exc:  # noqa: BLE001
        log.exception("ชี้ตำแหน่งล้มเหลว")
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        _send_lock.release()
    if pos is None:
        return jsonify({"ok": False, "error": "หมดเวลา (ไม่ได้คลิกใน LINE ภายใน 20 วิ)"})
    return jsonify({"ok": True, "x": pos[0], "y": pos[1]})


@app.route("/api/logs")
def api_logs():
    if not os.path.exists(LOG_PATH):
        return jsonify({"lines": []})
    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[-120:]
    return jsonify({"lines": [ln.rstrip("\n") for ln in lines]})


def main():
    _rebuild_jobs()
    _scheduler.start(paused=True)   # เริ่มแบบหยุดไว้ก่อน รอผู้ใช้กด Start
    STATE["running"] = False
    url = "http://127.0.0.1:5000"
    log.info("เปิด UI ที่ %s", url)
    # เปิดเบราว์เซอร์ให้อัตโนมัติหลังเซิร์ฟเวอร์พร้อม (~1.2 วิ)
    import webbrowser
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # use_reloader=False กัน scheduler ถูกสร้างซ้ำสองรอบ
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
