# Frida — قوالب تعديل بصمة وقت التشغيل

هذه السكربتات **لا تُشغَّل تلقائياً** من الخادم. تستخدم عندما تحتاج أن يقرأ **تطبيق معيّن** قيماً مزيفة عبر Java API بينما النظام الحقيقي يبقى كما هو.

## المتطلبات

- `frida-tools` على الحاسوب: `pip install frida-tools`
- على المحاكي/الجهاز: `frida-server` بنفس الإصدار تقريباً، وصلاحيات مناسبة (غالباً root على AVD مع `adb root`).

## مثال

```bash
frida -D emulator-5554 -f com.example.app -l scripts/frida/emulator_fingerprint_hooks.js --no-pause
```

عدّل الكائن `FP` داخل `emulator_fingerprint_hooks.js` ليطابق بصمتك المخزّنة في لوحة التحكم.

## حدود

- لا يغني عن `setprop` الذي يطبّقه الـ backend؛ بعض التطبيقات تقرأ من NDK أو `/system/build.prop` مباشرة.
- الإخفاء الكامل لآثار المحاكي يتطلب تعديلات نظام أعمق من نطاق سكربت Frida فقط.

## ربط مع API

يمكنك تصدير JSON من `GET /api/fingerprint/{device_id}` وتوليد سكربت Frida ديناميكياً (سكربت مولّد اختياري في المستقبل).
