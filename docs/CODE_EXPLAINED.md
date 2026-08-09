# อธิบายการทำงานของโค้ด — LINE PC Scheduler (ละเอียด)

เอกสารนี้อธิบายการทำงานของโค้ดทุกไฟล์/ทุกฟังก์ชัน เพื่อให้เข้าใจและดูแลต่อได้

---

## 1. ภาพรวม (Architecture)

ระบบนี้ส่งข้อความ/รูปเข้า **กลุ่ม LINE อัตโนมัติตามเวลา** โดยไม่ใช้ LINE API
(เพราะเราเป็นสมาชิกกลุ่มธรรมดา ไม่มี Access Token และเอาบอทเข้ากลุ่มไม่ได้)
วิธีที่ใช้คือ **UI automation** — สั่งเมาส์/คีย์บอร์ดควบคุมแอป **LINE PC** เหมือนคนนั่งพิมพ์เอง

```
                 ┌─────────────────────────────────────────────┐
   ผู้ใช้ ──►     │  หน้าเว็บ UI (app.py + templates/index.html)   │
                 │  ตั้งค่า / เริ่ม-หยุด / ส่งทดสอบ / ดูสถานะ+log    │
                 └───────────────┬─────────────────────────────┘
                                 │ อ่าน/เขียน
                                 ▼
                          config.yaml  ◄──── config_util.py (โหลด+ตีความ targets)
                                 │
        ┌────────────────────────┴───────────────────────┐
        ▼                                                 ▼
  scheduler.py (โหมด headless)                    APScheduler ใน app.py
  ตั้งเวลาแบบ blocking                            ตั้งเวลาแบบ background
        │                                                 │
        └───────────────────────┬─────────────────────────┘
                                 ▼
                        line_controller.py  ◄── หัวใจของระบบ
                        (ควบคุมหน้าต่าง LINE + พิมพ์ + แนบรูป)
                                 │  Win32 / UIA / SendInput / pyautogui
                                 ▼
                            แอป LINE PC (Windows)
```

**หลักการสำคัญที่ค้นพบจากการทดสอบจริง (ต้องเข้าใจก่อน):**

| เรื่อง | สาเหตุ | วิธีที่โค้ดใช้ |
|-------|--------|--------------|
| เปิดห้องแชต | คลิกครั้งเดียวไม่ติด | **double-click** |
| ห้องแชตที่เปิด | LINE เด้งเป็น **หน้าต่างแยก** (`class=ChatWindow`) ที่ title = ชื่อกลุ่ม | หา ChatWindow ด้วย UIA + ตรวจชื่อ |
| ใส่ข้อความ | LINE **ไม่รับ Ctrl+V (paste)** | **พิมพ์ (type)** ผ่าน SendInput |
| อิโมจิ | `send_keys` ส่งอักขระ >U+FFFF ไม่ได้ (เพี้ยนเป็น 陋) | SendInput + **surrogate pair** |
| พาธรูป | File dialog หา `/` ไม่เจอ | แปลงเป็น `\` (`os.path.normpath`) |
| หน้าต่าง LINE ซ้ำชื่อ | มีหน้าต่างชื่อ "LINE" หลายอัน | กรองด้วย `class=AllInOneWindow` + เลือกอันใหญ่สุด |

---

## 2. โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|------|--------|
| `line_controller.py` | **หัวใจ** — ควบคุมหน้าต่าง LINE, พิมพ์ข้อความ, แนบรูป, ส่ง |
| `config_util.py` | โหลด `config.yaml`, ตีความกลุ่มเป้าหมาย (targets), ตั้ง logging |
| `scheduler.py` | ตัวตั้งเวลาแบบ headless (รันในเทอร์มินัล) + สูตรคำนวณช่วงเวลา |
| `app.py` | เว็บเซิร์ฟเวอร์ Flask + ตัวตั้งเวลา background + REST API |
| `templates/index.html` | หน้าเว็บ UI (ฟอร์ม + JavaScript) |
| `calibrate.py` | เครื่องมือหาพิกัดคลิก |
| `send_once.py` | ทดสอบส่ง 1 ครั้ง |
| `config.example.yaml` | ต้นแบบ config |
| `install_task.ps1` / `uninstall_task.ps1` | ติดตั้ง/ถอน Windows Task Scheduler |
| `run.bat` | ดับเบิลคลิกเพื่อเปิดระบบ |

---

## 3. config.yaml — ค่าตั้งทั้งหมด

```yaml
timezone: Asia/Bangkok        # โซนเวลาที่ใช้ตั้งเวลาส่ง
line:
  window_title: LINE          # ชื่อหน้าต่างหลัก LINE
  window_class: AllInOneWindow # class หน้าต่างหลัก (กันสับสนหน้าต่างซ่อนที่ชื่อ LINE)
  chat_window_class: ChatWindow # class หน้าต่างห้องแชตที่เด้งออกมา
  target_name: ''             # กลุ่มเดี่ยว (ใช้เมื่อไม่มี targets ด้านล่าง)
  targets:                    # กลุ่มหลายกลุ่ม (ชื่อ + พิกัดแถวในรายการแชต)
    - name: กลุ่ม A
      chat_row: [240, 140]
    - name: กลุ่ม B
      chat_row: [240, 213]
  exe_path: C:\...\LineLauncher.exe  # เผื่อสคริปต์ต้องเปิด LINE เอง
  window: {x, y, width, height}      # ตำแหน่ง/ขนาดหน้าต่างที่บังคับก่อนส่งทุกครั้ง
  coords:
    chat_row: [240, 140]      # แถวกลุ่มเริ่มต้น (ระบบ double-click แถวนี้)
    message_box: [240, 850]   # (เลิกใช้แล้ว เก็บไว้เพื่อความเข้ากันได้)
  chat_input: [90, 95]        # ช่องพิมพ์ในหน้าต่างห้องแชต [จากซ้าย, จากล่าง]
  attach_btn: [24, 25]        # ปุ่มแนบไฟล์ 📎 [จากซ้าย, จากล่าง]
  close_chat_after: false     # ปิดหน้าต่างห้องแชตหลังส่งเสร็จไหม
  delays:                     # หน่วงเวลาระหว่างสเต็ป (เครื่องช้าเพิ่มค่า)
    after_launch, after_focus, after_open_chat, after_click_box, after_paste
messages:                     # ตารางข้อความ (ดูรูปแบบใน README)
```

> พิกัดทั้งหมด **อ้างอิงจากมุมซ้ายบนของหน้าต่าง** ที่ถูกบังคับตำแหน่ง/ขนาดไว้ (`line.window`)
> ดังนั้นถ้า `window` = 480×900 ที่ (0,0) พิกัด `[240,140]` = จุดกลาง-บนของรายการแชต

---

## 4. config_util.py

โหลด config และตีความกลุ่มเป้าหมาย ใช้ร่วมกันทั้ง `scheduler.py` และ `app.py`

| ฟังก์ชัน | ทำอะไร |
|---------|--------|
| `load_config()` | อ่าน `config.yaml` (ถ้าไม่มี แจ้งให้ก็อปจาก example แล้วออก) คืน dict |
| `get_targets(cfg)` | คืนรายการกลุ่มทั้งหมด `[{name, chat_row}]` ; ถ้าไม่ได้ตั้ง `line.targets` จะ fallback เป็นกลุ่มเดียวจาก `target_name` + `coords.chat_row` |
| `resolve_targets(cfg, want)` | เลือกกลุ่มสำหรับข้อความหนึ่ง — `want` เป็น list/สตริงชื่อกลุ่ม ; **ว่าง = ทุกกลุ่ม** ; ถ้าระบุชื่อ จะกรองเฉพาะที่ตรง |
| `setup_logging()` | ตั้ง log ออกทั้งหน้าจอ + ไฟล์ `line_sender.log` |

**ตัวอย่างการ resolve:**
- `resolve_targets(cfg, None)` → ทุกกลุ่ม
- `resolve_targets(cfg, ["กลุ่ม B"])` → เฉพาะกลุ่ม B
- ถ้าชื่อไม่ตรงเลย → คืนทุกกลุ่ม (กันพลาด)

---

## 5. line_controller.py — หัวใจของระบบ

### 5.1 ตัวพิมพ์ยูนิโค้ดผ่าน SendInput (แก้อิโมจิเพี้ยน)

ปัญหา: `send_keys` ของ pywinauto พิมพ์อิโมจิ (อักขระ > U+FFFF) ไม่ได้ → กลายเป็นตัวอักษรจีน เช่น `陋`
เพราะอิโมจิใน Windows เก็บเป็น **UTF-16 surrogate pair** (2 ยูนิต 16 บิต) แต่ send_keys ส่งได้แค่ยูนิตเดียว

วิธีแก้: เรียก Windows API `SendInput` เองด้วย `ctypes` แล้วส่งแบบ `KEYEVENTF_UNICODE`

```python
def type_unicode(text):
    for ch in text:
        if ch == "\n":                     # ขึ้นบรรทัดใหม่ = Shift+Enter (ไม่ส่ง)
            _tap_vk(VK_RETURN, shift=True)
        else:
            utf16 = ch.encode("utf-16-le")  # 1 อักขระ = 1 หรือ 2 ยูนิต
            for cu in [รวมทีละ 16 บิต]:
                _send(keydown unicode cu); _send(keyup unicode cu)
```

- อักษรทั่วไป/ไทย = 1 ยูนิต → พิมพ์ปกติ
- อิโมจิ = 2 ยูนิต (surrogate pair) → ส่งครบทั้งคู่ → LINE ประกอบเป็นอิโมจิถูกต้อง

**กับดักสำคัญ:** โครงสร้าง `INPUT` (union) ต้องมี `MOUSEINPUT` ด้วย เพื่อให้ `sizeof(INPUT)` = 40 ไบต์ (บน 64-bit)
ถ้าใส่แค่ `KEYBDINPUT` ขนาดจะผิด → `SendInput` **ล้มเหลวเงียบ ๆ** (ไม่พิมพ์อะไรเลย แต่ไม่ error)
โค้ดจึงเช็คค่าที่ส่งคืน ถ้า `sent != n` จะ log เตือน

| ฟังก์ชันย่อย | หน้าที่ |
|-------------|--------|
| `_mk(...)` | สร้าง struct `INPUT` 1 ตัว (keyboard event) |
| `_send(*inputs)` | เรียก `SendInput` + เตือนถ้าส่งไม่ครบ |
| `_tap_vk(vk, shift)` | กดปุ่มพิเศษ (เช่น Enter) พร้อม Shift ถ้าต้องการ |
| `type_unicode(text)` | พิมพ์ข้อความยูนิโค้ดใด ๆ (ไทย+อิโมจิ) |

### 5.2 `LineController.__init__`

อ่านค่าจาก `cfg["line"]` เก็บเป็น attribute: `window_title`, `window_class`, `chat_window_class`,
`target_name`, `chat_input`, `attach_btn`, `close_after`, `exe_path`, `win_box`, `coords`, `delays`

### 5.3 หา + จัดหน้าต่าง LINE

| เมธอด | หน้าที่ |
|-------|--------|
| `_delay(key, default)` | หน่วงเวลาตามค่าใน `delays` |
| `_find_window()` | หาหน้าต่างหลัก LINE — กรองด้วย `class=AllInOneWindow` ก่อน (ถ้าไม่เจอใช้ title) แล้ว **เลือกอันที่มองเห็นและพื้นที่ใหญ่สุด** (LINE มีหน้าต่างซ่อนชื่อเดียวกัน) |
| `_connect_window()` | เรียก `_find_window()` ; ถ้าไม่เจอและมี `exe_path` จะ **เปิด LINE ให้** แล้วหาอีกครั้ง |
| `_prepare_window()` | คืนสภาพ (ถ้าย่ออยู่) → **ย้าย/ปรับขนาดหน้าต่างไปตำแหน่งคงที่** (`line.window`) → โฟกัส → คืน `rectangle` |

> `_prepare_window()` คือกุญแจความเสถียร — บังคับหน้าต่างให้อยู่ที่เดิมขนาดเดิมทุกครั้ง
> พิกัดคลิกจึงตรงเสมอ (ไม่ขึ้นกับว่าผู้ใช้ย้าย/ย่อหน้าต่างไว้)

### 5.4 คลิก + หาห้องแชต

| เมธอด | หน้าที่ |
|-------|--------|
| `_double_click_coord(rect, coord)` | double-click ที่ (มุมหน้าต่าง + coord) |
| `_double_click_rel(rect, key)` | double-click ตามพิกัดใน `coords[key]` |
| `_find_chat_window(expected_name)` | วน UIA หาหน้าต่าง `class=ChatWindow` ที่มองเห็น ; ถ้าระบุชื่อจะเลือกอันที่ title ตรง (เทียบแบบ substring 2 ทาง) ; ไม่ระบุคืนอันแรกที่เจอ |

### 5.5 แนบรูป (ส่งหลายรูปพร้อมกัน)

| เมธอด | หน้าที่ |
|-------|--------|
| `_find_visible_file_dialog()` | หา File Open dialog (`class=#32770`) ที่มองเห็น (มีซ่อนหลายอัน เลือกอันใหญ่สุด) |
| `_attach_images(rect, paths)` | คลิกปุ่ม 📎 → รอ dialog → ใส่ **ทุกไฟล์ในช่องเดียว** เป็น `"a.jpg" "b.jpg" ...` (คั่นเว้นวรรค + ครอบ `"`) → Enter เปิดไฟล์ทั้งหมด |
| `_normalize_images(image)` | รับ str (พาธเดียว/หลายบรรทัด) หรือ list → คืน list พาธ ; **แปลง `/` เป็น `\` ด้วย `os.path.normpath`** (สำคัญ! dialog หา `/` ไม่เจอ) |

> การใส่หลายพาธคั่นเว้นวรรคในช่อง filename = สั่ง dialog เลือกหลายไฟล์พร้อมกัน
> → LINE แนบทั้งหมด → กด Enter ครั้งเดียว → ส่งเป็น **อัลบั้ม**
> ข้อกำหนด: รูปควรอยู่โฟลเดอร์เดียวกัน

### 5.6 `_type_text(text)`

เรียก `type_unicode(text)` (ข้อ 5.1) — พิมพ์ข้อความรองรับไทย+อิโมจิ ; `\n` = Shift+Enter

### 5.7 `send(...)` — ฟังก์ชันหลัก

```python
def send(text="", image="", order="image_first",
         chat_row=None, target_name=None, should_stop=None)
```

**พารามิเตอร์:**
- `text` — ข้อความ
- `image` — พาธรูป (1 หรือหลายไฟล์: list หรือสตริงหลายบรรทัด)
- `order` — `"image_first"` (รูปก่อน) หรือ `"text_first"` (ข้อความก่อน)
- `chat_row`, `target_name` — ระบุกลุ่มเจาะจง (ถ้าไม่ใส่ ใช้ค่า default จาก config)
- `should_stop` — ฟังก์ชันเช็ค "ขอให้หยุด" (ใช้ตอนกดปุ่มหยุด)

**ลำดับการทำงาน:**
1. ตรวจ input (ต้องมี text หรือ image ; ไฟล์รูปต้องมีจริง)
2. `_prepare_window()` จัดหน้าต่างหลัก
3. **เปิดห้อง**: `_double_click_coord(chat_row)` แล้วหา ChatWindow — **ลองได้ถึง 3 ครั้ง**
   (คลิกแรกบางทีแค่ปลุกหน้าต่าง double-click เลยไม่ติด → โฟกัสใหม่แล้วลองซ้ำ)
4. **ตรวจชื่อห้อง**: ถ้า `target_name` ไม่ตรงกับ title ของห้องที่เปิด → **ยกเลิกทันที** (กันส่งผิดกลุ่ม)
5. นิยามฟังก์ชันย่อย `do_images()` / `do_text()` (แต่ละอันเช็ค `should_stop` ก่อนทำ)
   - `do_images()` — แนบรูปทั้งหมด → Enter ส่ง (อัลบั้มเดียว)
   - `do_text()` — คลิกช่องพิมพ์ 2 ครั้ง → `Ctrl+A`+`Backspace` เคลียร์ → พิมพ์ → Enter ส่ง
6. ส่งตาม `order` (image_first / text_first)
7. ถ้า `close_after` = true → ปิดหน้าต่างห้องแชต

**การกันส่งผิดกลุ่ม (ข้อ 4)** คือ safety สำคัญ — แม้ลำดับแถวจะเลื่อน ถ้าห้องที่เปิดชื่อไม่ตรงจะไม่ส่ง

---

## 6. scheduler.py — ตัวตั้งเวลา (headless)

รันในเทอร์มินัล (`python scheduler.py`) ใช้ **BlockingScheduler** ของ APScheduler

| ฟังก์ชัน | หน้าที่ |
|---------|--------|
| `_normalize_days(days)` | แปลงค่า days → รูปแบบ `day_of_week` ของ cron (`*`, `mon-fri`, `mon,wed,fri`) |
| `_parse_time("HH:MM")` | แยกเป็น (ชั่วโมง, นาที) |
| `make_job(ctrl, text, image, order, targets)` | สร้างฟังก์ชันงาน 1 ตัว ที่วนส่งเข้า **ทุกกลุ่มใน targets** (จับ error ต่อกลุ่ม) |
| `_window_triggers(...)` | **สูตรช่วงเวลา** — สร้าง CronTrigger สำหรับ "ช่วง sh:sm–eh:em ทุก every นาที" |
| `main()` | โหลด config → วนสร้าง job ตาม messages → `scheduler.start()` (บล็อกจนกด Ctrl+C) |

**สูตร `_window_triggers` (โหมดช่วงเวลา):**
กรณีนาทีเริ่ม/จบเป็น 0 และ `every` หาร 60 ลงตัว (เช่น 2,5,10,15,30):
- สร้าง cron: ชั่วโมง `sh..(eh-1)` นาที `*/every` → ครอบคลุม sh:00 ถึง (eh-1):(60-every)
- บวกอีก 1 trigger ที่ `eh:00` พอดี (จุดสิ้นสุด)

ตัวอย่าง 10:00–19:00 ทุก 2 นาที → ยิงที่ 10:00, 10:02, …, 18:58, และ 19:00 = **271 ครั้ง/วัน**
สูตรจำนวนครั้ง = `(นาทีในช่วง ÷ every) + 1`

**2 โหมดของ messages:**
- โหมดเวลาเดียว: มี `time: "HH:MM"`
- โหมดช่วงเวลา: มี `start` + `end` + `every_minutes`

ตัวเลือก APScheduler ที่ใช้: `max_instances=1` (กันซ้อน), `coalesce=True` (รวบรอบที่พลาด), `misfire_grace_time` (เผื่อยิงช้าได้กี่วินาที)

---

## 7. app.py — เว็บ UI + API

Flask + **BackgroundScheduler** (ตั้งเวลาในตัวแอปโดยไม่บล็อก)

### 7.1 สถานะรวม (module-level)

| ตัวแปร | หน้าที่ |
|-------|--------|
| `_send_lock` | ล็อกกันส่งซ้อน (เพราะ pyautogui ยึดเมาส์ทั้งเครื่อง) |
| `_cancel` | `threading.Event` — ตั้งเมื่อกดหยุด ให้การส่งที่ค้างเลิกกลางคัน |
| `EVENTS` | `deque` เก็บประวัติการส่งล่าสุด (สูงสุด 300) |
| `STATE` | สถานะ running |
| `_cfg`, `_ctrl`, `_scheduler` | config, ตัวควบคุม LINE, ตัวตั้งเวลา |

### 7.2 ฟังก์ชันภายใน

| ฟังก์ชัน | หน้าที่ |
|---------|--------|
| `_record(status, text, error)` | บันทึกเหตุการณ์ลง EVENTS (status: success/error/stopped) |
| `_do_send(text, image, order, targets)` | **ส่งจริง** — ถือ `_send_lock` แล้ววนทุกกลุ่ม ; เช็ค `_cancel` ก่อนแต่ละกลุ่ม ; ส่ง `should_stop=_cancel.is_set` เข้า `ctrl.send` เพื่อให้หยุดกลางคันได้ |
| `_make_job(...)` | ห่อ `_do_send` เป็นงานสำหรับ scheduler |
| `_rebuild_jobs()` | ล้าง job เก่า แล้วสร้างใหม่จาก `_cfg.messages` (รองรับทั้ง 2 โหมดเวลา + resolve targets ต่อข้อความ) |
| `_next_run()` | เวลารอบถัดไป (min ของ next_run_time ทุก job) |
| `_sent_today()` | นับจำนวนส่งสำเร็จวันนี้จาก EVENTS |
| `_save_config(new_cfg)` | เขียน `config.yaml` (จัดลำดับคีย์ + `allow_unicode`) |

### 7.3 REST API (routes)

| เส้นทาง | เมธอด | หน้าที่ |
|--------|-------|--------|
| `/` | GET | ส่งหน้าเว็บ (index.html) |
| `/api/status` | GET | สถานะ: running, รอบถัดไป, ส่งวันนี้, ผลล่าสุด, ประวัติ 50 รายการ |
| `/api/config` | GET | คืน config ปัจจุบัน |
| `/api/config` | POST | บันทึก config → โหลดใหม่ → สร้าง job ใหม่ |
| `/api/start` | POST | ล้าง `_cancel` → สร้าง job → `resume()` → running=true |
| `/api/stop` | POST | **ตั้ง `_cancel`** (หยุดงานค้าง) → `pause()` (กันรอบใหม่) → running=false |
| `/api/send_now` | POST | ส่งทดสอบทันที (แยก thread ไม่บล็อก) — รับ text/image/order/targets |
| `/api/pick_images` | POST | เปิด **File dialog ของ Windows** (tkinter) ให้เลือกรูป คืนพาธเต็ม |
| `/api/targets` | GET | รายชื่อกลุ่มที่นิยามไว้ (ให้ UI ทำ dropdown) |
| `/api/logs` | GET | 120 บรรทัดล่าสุดของ `line_sender.log` |

### 7.4 `main()`

สร้าง job → `scheduler.start(paused=True)` (เริ่มแบบหยุดไว้ก่อน) → **เปิดเบราว์เซอร์อัตโนมัติ** (Timer 1.2 วิ) → `app.run(port=5000)`

**การหยุดทันที (ข้อสำคัญที่แก้):**
`pause()` อย่างเดียวหยุดแค่ "รอบใหม่" ไม่หยุดงานที่กำลังส่ง (5 รูป × 2 กลุ่มใช้เวลานาน)
จึงเพิ่ม `_cancel` ที่ถูกเช็ค **ก่อนแต่ละกลุ่ม / ก่อนแต่ละรูป / ก่อนข้อความ** → กดหยุดแล้วเลิกภายในไม่กี่วินาที

---

## 8. templates/index.html — หน้าเว็บ UI

หน้าเดียว (HTML + CSS + vanilla JavaScript) แบ่งเป็น 2 คอลัมน์:
- **ซ้าย**: ฟอร์มตั้งค่า (timezone, กลุ่มเป้าหมาย, พิกัด, delay, ตารางข้อความ) + ปุ่มบันทึก/ส่งทดสอบ
- **ขวา**: Log สด + ประวัติการส่ง (ยืดลงถึงล่างสุดของจอ)

**ฟังก์ชัน JavaScript สำคัญ:**

| ฟังก์ชัน | หน้าที่ |
|---------|--------|
| `loadConfig()` | ดึง `/api/config` มาเติมลงฟอร์ม (เก็บ `LOADED_LINE` ไว้ merge ตอนเซฟ) |
| `gatherConfig()` | รวบค่าจากฟอร์มกลับเป็น config object ; **merge บน `LOADED_LINE`** เพื่อคงคีย์ที่ฟอร์มไม่มี (window_class, chat_input, attach_btn ฯลฯ) |
| `msgRow(m)` | สร้างแถวตารางข้อความ 1 แถว (time/start/end/every/days/text/image/order/targets) |
| `targetRow(t)` / `addTarget()` / `gatherTargets()` | จัดการตารางกลุ่มเป้าหมาย |
| `browseInto(textarea)` | เรียก `/api/pick_images` เปิด dialog แล้วเติมพาธลงช่อง |
| `saveConfig()` | POST `gatherConfig()` ไป `/api/config` |
| `sendNow()` | รวบ text/image(หลายบรรทัด)/order/targets → POST `/api/send_now` |
| `ctl('start'/'stop')` | เรียก start/stop |
| `refresh()` | ดึง `/api/status` ทุก 3 วิ อัปเดตการ์ดสถานะ+ประวัติ |
| `refreshLog()` | ดึง `/api/logs` ทุก 5 วิ |

**การกันคีย์หาย (สำคัญ):** ฟอร์มไม่ได้แสดงทุกคีย์ของ `line` ถ้า gatherConfig สร้าง object ใหม่หมดจะทำให้คีย์ที่ไม่มีในฟอร์มหาย → แก้โดย `Object.assign({}, LOADED_LINE, {...ค่าจากฟอร์ม})`

---

## 9. เครื่องมือ + สคริปต์อื่น

| ไฟล์ | หน้าที่ |
|------|--------|
| `calibrate.py` | จัดหน้าต่าง LINE แล้วโชว์พิกัดเมาส์แบบ real-time (relative ต่อมุมหน้าต่าง) เพื่อหา `chat_row` |
| `send_once.py` | `python send_once.py "ข้อความ"` — ทดสอบส่ง 1 ครั้งด้วย config ปัจจุบัน |
| `install_task.ps1` | ลงทะเบียน Windows Task Scheduler ให้รัน `scheduler.py` ตอนล็อกอิน (ใช้ pythonw, Interactive) |
| `uninstall_task.ps1` | ถอน task |
| `run.bat` | ดับเบิลคลิกเพื่อ `python app.py` (เปิดเบราว์เซอร์ให้เอง) |

---

## 10. ลำดับการทำงานจริง (End-to-End) เมื่อถึงเวลาส่ง

```
APScheduler ยิง job ตามเวลา
   └─► _do_send(text, image, order, targets)          [app.py]
         ถือ _send_lock (กันซ้อน)
         วนทีละกลุ่มใน targets:
            เช็ค _cancel (ถ้ากดหยุด → เลิก)
            └─► ctrl.send(text, image, order, chat_row, target_name, should_stop)   [line_controller.py]
                  1. _prepare_window()            → ย้าย/ปรับขนาด/โฟกัสหน้าต่าง LINE
                  2. double-click chat_row (×3)   → เปิดห้อง = หน้าต่าง ChatWindow
                  3. _find_chat_window(name)      → หา + ตรวจชื่อห้องให้ตรง (ไม่ตรง=ยกเลิก)
                  4. do_images()/do_text() ตาม order:
                        - รูป: 📎 → File dialog → ใส่ทุกพาธ → Enter → Enter (ส่งอัลบั้ม)
                        - ข้อความ: คลิกช่อง → เคลียร์ → type_unicode() → Enter
                  5. (option) ปิดหน้าต่างห้องแชต
         บันทึกผลลง EVENTS (success/error/stopped)
```

---

## 11. ข้อควรรู้/ข้อจำกัด

- **ผิด LINE ToS** — automation บัญชีเสี่ยงถูกระงับ อย่าส่งถี่เกินไป
- ต้อง **ปักหมุดกลุ่มไว้บนสุด** เพื่อให้พิกัดแถวคงที่ (ไม่งั้นรายการสลับตามข้อความล่าสุด)
- มี **name verification** กันส่งผิดกลุ่ม แม้ลำดับเลื่อน (ถ้าชื่อไม่ตรงจะไม่ส่ง)
- รูปหลายไฟล์ควรอยู่ **โฟลเดอร์เดียวกัน**
- เครื่องต้องเปิดค้าง + LINE ล็อกอิน + ไม่ล็อกหน้าจอ ระหว่างช่วงส่ง
- รัน `app.py` **หรือ** `scheduler.py` อย่างใดอย่างหนึ่ง (อย่าพร้อมกัน จะส่งซ้ำ)
- แก้ `config.yaml` หรือ `index.html` แล้วต้อง **รีสตาร์ท** app.py (config โหลดตอนเปิด + Flask cache template)
