/**
 * قالب Frida — يتطلب frida-server على الجهاز/المحاكي (غالباً root).
 * الاستخدام (مثال):
 *   frida -U -f com.target.app -l emulator_fingerprint_hooks.js --no-pause
 *
 * عدّل FP أدناه أو مرّرها من سكربت Python عبر rpc.exports.
 *
 * تحذير: استخدم فقط على أجهزة/بيئات تملك صلاحية الاختبار.
 */
'use strict';

const FP = {
  MANUFACTURER: 'samsung',
  BRAND: 'samsung',
  MODEL: 'SM-G996B',
  FINGERPRINT: 'samsung/o1sxeea/o1s:15/AP3A.240905.015.A2/G996BXXSJHZC2:user/release-keys',
  SERIAL: 'TESTSERIAL1',
  ANDROID_ID: '0123456789abcdef',
};

function hookBuild() {
  const Build = Java.use('android.os.Build');
  try {
    Build.MANUFACTURER.value = FP.MANUFACTURER;
    Build.BRAND.value = FP.BRAND;
    Build.MODEL.value = FP.MODEL;
    Build.FINGERPRINT.value = FP.FINGERPRINT;
    Build.SERIAL.value = FP.SERIAL;
  } catch (e) {
    console.log('[fp] Build fields: ' + e);
  }
}

function hookTelephonyIMEI() {
  const TelephonyManager = Java.use('android.telephony.TelephonyManager');
  TelephonyManager.getImei.overload().implementation = function () {
    return '359162051234567';
  };
  TelephonyManager.getImei.overload('int').implementation = function (slot) {
    return '359162051234567';
  };
}

Java.perform(function () {
  hookBuild();
  try {
    hookTelephonyIMEI();
  } catch (e) {
    console.log('[fp] TelephonyManager: ' + e);
  }
  console.log('[fp] hooks installed (template)');
});
