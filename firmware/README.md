# حزم السوفتوير (مرجع البصمة)

ضع هنا ملفات ZIP بأسماء متوافقة مع نمط SAMFW الشائع، مثلاً:

`SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip`

- يكتشفها الـ API عبر `GET /api/meta/firmware-packages`.
- عند إنشاء جهاز مرّر `firmware_package` باسم الملف فقط (انظر `POST /api/devices`).

**مهم:** هذه الحزم مخصّصة عادةً للأجهزة الحقيقية (Odin) وليست صورة `system.img` لمحاكي Google AVD. المزرعة تستخدمها لمواءمة **AP / CSC / build fingerprint** مع السوفتوير الذي لديك، بينما يعمل المحاكي على **system-images** من Android SDK.

يمكن تغيير المسار بالمتغير `FIRMWARE_PACKAGES_DIR`.
