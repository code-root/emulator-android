# مرجع مواصفات نظام Android Emulator Farm

هذا المستند يطابق المواصفات الوظيفية التي طلبتها (Emulator Core، أدوات OSS، البصمة، API، Dashboard، DB، ميزات متقدمة، أمان، نشر) مع **ما هو منفَّذ فعلياً** في المستودع، وما هو **مخطط للتوسعة**. استخدمه كخريطة طريق للتطوير.

> **التقنية الحالية:** Backend **FastAPI** (Python) + **PostgreSQL** + **React (Vite) + Tailwind** + **Docker Compose** + **JWT**.  
> لم يُبنَ النظام على Node/Express؛ يمكن إضافة خدمة جانبية لاحقاً دون كسر الواجهات.

---

## 1) Emulator Core

| المتطلب | الحالة | أين في الكود / ملاحظات |
|--------|--------|-------------------------|
| Android Emulator الرسمي (AVD) | **منفَّذ** | `backend/core/emulator/avd.py`, `EmulatorManager`, `EMULATOR_BACKEND=avd` |
| Genymotion (Desktop / Cloud) | **غير منفَّذ** | إضافة `GenymotionBackend` + محوّل منفذ/سيريال مشابه لـ AVD + إعدادات في `config.py` |
| تثبيت APK | **منفَّذ** | `POST /api/devices/{id}/install` — يقبل `.apk` فقط حالياً |
| XAPK (أرشيف + OBB) | **غير منفَّذ** | مسار مقترح: فك XAPK مؤقتاً → `adb install-multiple` + دفع OBB إلى `/sdcard/Android/obb/...` |
| Multi-instance | **منفَّذ** | عدة صفوف `devices`؛ منافذ ADB/كونسول مخصصة لكل جهاز |
| تحكم CLI | **جزئي** | المحاكي يُدار عبر `emulator` CLI؛ **أوامر كونسول المحاكي (telnet)** مستخدمة داخل البصمة لـ GPS (`FingerprintSpoofer` + `telnetlib`)؛ لا يوجد بعد REST موحّد لـ `network status` / `battery` |

---

## 2) Open Source Control Tools (دمج عبر طبقة خدمة)

| الأداة | الحالة | التكامل |
|--------|--------|---------|
| **ADB** | **منفَّذ** | `core/tools/adb.py` — تثبيت، shell، لقطات، logcat |
| **Scrcpy** | **جزئي** | `core/tools/scrcpy.py` موجود؛ **لا توجد نقاط REST** بعد لبدء/إيقاف الجلسة من الـ API (الواجهة تعتمد غالباً لقطات / WebSocket) |
| **Frida** | **جزئي** | `core/tools/frida_tool.py` — **غير موصول بـ `main.py` / routes**؛ يحتاج `api/routes/frida.py` + صلاحيات |
| **mitmproxy** | **منفَّذ** | `core/tools/mitm_tool.py` + `api/routes/proxy.py` (تشغيل/إيقاف، تمرير حركة، إعداد بروكسي الجهاز) |
| **Emulator Console** | **جزئي** | عبر telnet داخل `spoofer.py` للموقع؛ توسيع مقترح: خدمة `EmulatorConsoleService` أوامر `network speed` / `battery` / `geo` |

**مبدأ Wrapper Service:** كل أداة تبقى في `core/tools/*`؛ الـ API في `api/routes/*` يستدعيها فقط ويكتب `OperationLog`.

---

## 3) Device Fingerprint System

| الحقل / القدرة | الحالة | ملاحظات |
|----------------|--------|---------|
| IMEI, Android ID, Model, MAC, IP, GPS | **منفَّذ** | الحقول في `db/models.py` → `DeviceFingerprint`؛ التطبيق عبر `FingerprintSpoofer` |
| Xposed / LSPosed | **غير منفَّذ** | يتطلب صورة نظام تدعم الإطار؛ موثَّق كتوسعة اختيارية |
| Spoofing لكل جهاز | **منفَّذ** | بصمة لكل `device_id`؛ `PUT` + `POST .../apply` |
| Hub API (موحّد) | **منفَّذ** | `GET/PUT /api/fingerprint/{id}`, apply, randomize, validate, revisions, revert, compare |
| **Import من جهاز حقيقي** | **منفَّذ** | `POST /api/fingerprint/{id}/import` — يقبل نص getprop أو build.prop |
| **Jitter (تحريك دوري)** | **منفَّذ** | `POST /api/fingerprint/{id}/jitter` — ip/gps/battery بدلتا صغيرة |
| الإصدارات (Revisions) | **منفَّذ** | جدول `fingerprint_revisions`؛ list / revert / compare |
| Extended JSON | **منفَّذ** | `extended_json` — SIM2, network, sensors, battery, location |
| فحص التناسق | **منفَّذ** | Luhn, build_fingerprint, MCC/MNC range, carrier↔MCC country, sensor completeness |
| حزم SAMFW | **منفَّذ** | `firmware/` + `GET /api/meta/firmware-packages` + `core/firmware/samfw.py` |
| نموذج البيانات | **one-per-device + revisions** | بصمة واحدة نشطة + سجل تاريخي؛ تعدد الملفات غير منفَّذ (باكلوج) |
---

## 4) Backend (API)

| المتطلب | الحالة |
|---------|--------|
| إطار | **FastAPI** (وليس Express) |
| JWT | **منفَّذ** (`api/routes/auth.py`) |
| CRUD أجهزة + Start/Stop/Restart | **منفَّذ** (`api/routes/devices.py`) |
| تثبيت APK | **منفَّذ** (`api/routes/apps.py`) |
| أوامر ADB (shell) | **منفَّذ** (`POST .../shell`) |
| Scrcpy session عبر API | **مخطط** (الكود جاهز في `ScrcpyManager`) |
| إدارة البصمة | **منفَّذ** (`api/routes/fingerprint.py`) |
| Logging + أخطاء | **منفَّذ** (`OperationLog`, handlers في `main.py`) |

---

## 5) Dashboard (Frontend)

| المتطلب | الحالة |
|---------|--------|
| React + Tailwind | **منفَّذ** (`frontend/`) |
| قائمة الأجهزة والحالة | **منفَّذ** (Dashboard / Devices / DeviceDetail) |
| شاشة مباشرة | **جزئي** (لقطات + WebSocket؛ **ليست WebRTC كاملة** كبديل scrcpy) |
| أزرار تشغيل/إيقاف/تثبيت/بصمة | **منفَّذ** في الصفحات ذات الصلة |

---

## 6) Database

| المتطلب | الحالة |
|---------|--------|
| PostgreSQL | **منفَّذ** (`DATABASE_URL` + SQLAlchemy async) |
| أجهزة، بصمات، بروكسي، سجلات | **منفَّذ** (`db/models.py`) |

---

## 7) Advanced Features

| الميزة | الحالة |
|--------|--------|
| Proxy لكل جهاز (mitmproxy) | **منفَّذ** |
| GPS Spoofing | **منفَّذ** (emulator console `geo fix` + jitter endpoint) |
| Network throttling (3G/4G) | **مخطط** |
| Scheduler | **منفَّذ** (`services/scheduler.py`) |
| WebSocket JPEG | **منفَّذ** (`api/routes/ws.py`) |
| **WebSocket H.264** | **منفَّذ** (`api/routes/ws_h264.py`) |
| **Network Inspector** | **مخطط** — اتصالات التطبيق + cookies/sessions في الداشبورد |

---

## 7a) H.264 WebSocket Protocol

**المسار:** `ws://<host>/ws/{device_id}/h264?token=<JWT>`

### رسائل الخادم → المتصفح (Binary)

| Byte[0] | النوع | المحتوى |
|---------|-------|---------|
| `0x01` | **CONFIG** | `[1B type][4B width LE][4B height LE][2B codec_len][codec bytes][2B sps_len][SPS][2B pps_len][PPS]` |
| `0x02` | **FRAME** | `[1B type][1B keyframe][8B PTS µs LE][NAL data...]` |

### رسائل الخادم → المتصفح (JSON)

| `type` | المعنى |
|--------|--------|
| `status` | حالة الجهاز + stream mode |
| `ping` | keepalive (30s timeout) |
| `h264_error` | خطأ التيار — `code`: `no_video_data` |
| `error` | أمر غير معروف |
| `pong` | رد على ping |

### رسائل المتصفح → الخادم (JSON)

| `action` | الحقول |
|----------|--------|
| `tap` | `x`, `y` (إحداثيات جهاز حقيقية بعد المعايرة) |
| `swipe` | `x1`, `y1`, `x2`, `y2`, `duration_ms` |
| `keyevent` | `key` (KEYCODE_*) |
| `input_text` | `text` |
| `screenshot_once` | — |
| `ping` / `get_status` | — |

### إعادة الاتصال (Frontend)
- backoff أسي 1s → 30s max
- Timeout: إن لم يصل CONFIG خلال **22 ثانية** → تراجع تلقائي إلى JPEG
- تنظيف كامل عند unmount أو تغيير التبويب

### تعيين إحداثيات اللمس (Touch Mapping)
الـ canvas يُعرض بحجم CSS مختلف عن دقة الإطار (720×1280 افتراضي).  
`useDeviceH264` يكشف `frameWidth/frameHeight`؛ دالة `clientToDeviceSurface()` في `DeviceScreen.tsx`  
تحوّل إحداثيات المؤشر عبر نسبة `frameW/canvasClientW` × `frameH/canvasClientH`  
لضمان الضغط على البكسل الصحيح في جميع حالات التكبير/ملء الشاشة.
---

## 8) Security

| المتطلب | الحالة |
|---------|--------|
| حماية API (JWT) | **منفَّذ** |
| أدوار | **جزئي** (`admin` / `user` فقط) |
| Rate limiting | **غير في `backend/main.py`** (يوجد مثال منفصل تحت جذر `api/` مع slowapi — ليس مسار التشغيل الرئيسي) |
| عزل محاكي (Sandbox) | **تشغيلي** (مجلدات `INSTANCES_DIR` لكل جهاز)؛ **ليست حاويات Docker لكل جهاز** |

---

## 9) Deployment

| المتطلب | الحالة |
|---------|--------|
| Docker + Compose | **منفَّذ** (`docker/docker-compose.yml` + `docker-compose.emulator.yml`) |
| خدمات backend / frontend / nginx | **منفَّذ** |
| `emulator-controller` كخدمة مستقلة | **غير مطلوب حالياً** (المنطق داخل backend) |
| CI | **منفَّذ** (`.github/workflows/ci.yml`) |

---

## 10) هيكل المجلدات (الواقعي)

```
emulator-android/
├── backend/                 # تطبيق FastAPI الرئيسي
│   ├── api/routes/          # auth, devices, apps, fingerprint, proxy, ws, operation_logs, meta
│   ├── core/
│   │   ├── emulator/        # AVD backend
│   │   ├── fingerprint/     # مولّد + spoofer + Samsung extended
│   │   └── tools/           # adb, mitm, scrcpy, frida_tool
│   ├── db/                  # models, database
│   ├── services/            # scheduler, ws_manager
│   ├── tests/               # smoke tests
│   ├── main.py
│   └── requirements.txt
├── frontend/                # React + Vite + Tailwind
├── docker/                  # Dockerfiles + compose + nginx
├── scripts/                 # SDK install, SQL patches, AOSP mirrors
└── docs/
    └── REFERENCE_SPEC.md    # هذا الملف
```

> **تنبيه:** قد يوجد في جذر المستودع مجلد `api/` أو `main.py` إضافي (CLI/نسخة قديمة)؛ **مسار التشغيل الموصى به للمزرعة هو `backend/`** (`uvicorn main:app` من داخل `backend`).

---

## 11) أوامر التشغيل السريعة

```bash
# قاعدة البيانات (محلي أو Docker)
# ثم الباكند (Python 3.11 أو 3.12)
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql+asyncpg://emulator:emulator@localhost:5432/emulatordb
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# الفرونتند
cd frontend && npm install && npm run dev

# Docker كامل
docker compose -f docker/docker-compose.yml up --build
```

**Android SDK + محاكي:** `scripts/install_android_sdk.sh` (يتطلب **Java 17+**).  
**ضبط المسار:** `export ANDROID_HOME=...` و`AVD_SDK_PATH` / اكتشاف تلقائي في `config.py`.

---

## 12) أمثلة REST API

استبدل `TOKEN` و`BASE` (مثلاً `http://localhost:8000`).

```http
### تسجيل الدخول
POST {{BASE}}/api/auth/login
Content-Type: application/json

{"username": "admin", "password": "your-password"}

### قائمة الأجهزة
GET {{BASE}}/api/devices
Authorization: Bearer {{TOKEN}}

### إنشاء جهاز
POST {{BASE}}/api/devices
Authorization: Bearer {{TOKEN}}
Content-Type: application/json

{"name": "emu-01", "ram_mb": 2048, "cpu_cores": 2, "api_level": 35, "preset": "samsung_sm_g996b_android15"}

### تشغيل / إيقاف
POST {{BASE}}/api/devices/1/start
Authorization: Bearer {{TOKEN}}

POST {{BASE}}/api/devices/1/stop
Authorization: Bearer {{TOKEN}}

### Shell (ADB)
POST {{BASE}}/api/devices/1/shell
Authorization: Bearer {{TOKEN}}
Content-Type: application/json

{"cmd": "getprop ro.product.model"}

### تثبيت APK
POST {{BASE}}/api/devices/1/install
Authorization: Bearer {{TOKEN}}
Content-Type: multipart/form-data; boundary=----x
------x
Content-Disposition: form-data; name="file"; filename="app.apk"
Content-Type: application/vnd.android.package-archive

<binary>
------x--

### قراءة/تحديث البصمة وتطبيقها
GET {{BASE}}/api/devices/1/fingerprint
Authorization: Bearer {{TOKEN}}

PUT {{BASE}}/api/devices/1/fingerprint
Authorization: Bearer {{TOKEN}}
Content-Type: application/json

{"device_model": "SM-G996B", "latitude": 24.7136, "longitude": 46.6753}

POST {{BASE}}/api/devices/1/fingerprint/apply
Authorization: Bearer {{TOKEN}}

### بروكسي + mitmproxy
POST {{BASE}}/api/devices/1/proxy/start
Authorization: Bearer {{TOKEN}}

GET {{BASE}}/api/devices/1/proxy/traffic?limit=50
Authorization: Bearer {{TOKEN}}
```

**WebSocket (حالة الجهاز):**  
`ws://<host>/ws/{device_id}?token=<JWT>` — انظر `frontend/src/api/client.ts` → `getWebSocketUrl`.

---

## 13) خارطة طريق مقترحة (أولويات عملية)

1. **REST لـ Scrcpy** — ربط `ScrcpyManager` بنقاط `POST/DELETE /api/devices/{id}/scrcpy` + توثيق المنفذ.  
2. **REST لـ Frida** — تغليف `FridaTool` (قائمة عمليات، حقن سكربت، سياسات أمان).  
3. **XAPK** — مسار رفع وفك وتثبيت متعدد الحزم.  
4. **Rate limiting** — `slowapi` أو middleware في `backend/main.py` + إعدادات من `config`.  
5. **توسيع RBAC** — أدوار مثل `operator` / `viewer` وصلاحيات على مستوى الجهاز.  
6. **Network throttling** — طبقة `EmulatorConsole` موحّدة.  
7. **Genymotion** — backend اختياري عبر `EMULATOR_BACKEND=genymotion`.  
8. **WebRTC اختياري** — بجانب scrcpy للعرض من المتصفح دون عميل سطح مكتب.

---

## 14) الترخيص والأدوات

حزم **Android SDK / emulator / system images** موزَّعة من Google (شروط Android SDK). بقية الأدوات (ADB, scrcpy, mitmproxy, Frida) مفتوحة المصدر؛ راجع ترخيص كل أداة عند التوزيع التجاري.

---

*آخر تحديث: يُحدَّث هذا الملف مع كل دفعة توسعات رئيسية.*
