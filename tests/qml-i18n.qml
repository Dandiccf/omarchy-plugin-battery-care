import QtQuick
import Quickshell
import qs.Commons
import "Care" as Care
import "Care/Model.js" as Model

ShellRoot {
  Care.CareTranslations { id: strings }
  Care.TimeoutEditor { id: editor }
  property string status: Model.status({key: "BAT0", state: 2}, true, strings)
  property string label: editor.label(0)
  Timer {
    property int phase: 0
    property int attempts: 0
    property int languageIndex: 0
    property var cases: [
      ["es", "Con batería"], ["es-MX", "Con batería"],
      ["fr", "Sur batterie"], ["it", "A batteria"],
      ["pt", "A bateria"], ["pt-BR", "A bateria"],
      ["pl", "Na baterii"], ["ru", "От батареи"],
      ["zh-CN", "使用电池"], ["ja", "バッテリー使用中"],
      ["ko", "배터리 사용 중"], ["hi", "बैटरी पर"],
      ["ar", "على البطارية"], ["en", "On battery"]
    ]
    function nextLanguage() {
      attempts = 0
      I18n.setLanguage(cases[languageIndex][0])
    }
    interval: 100; running: true; repeat: true
    onTriggered: {
      function check(value, message) { if (!value) throw new Error(message) }
      try {
        if (++attempts > 60) throw new Error("translation switch timed out")
        if (phase === 0) {
          check(strings.nativeAvailable, "modern Omarchy translation backend")
          I18n.setLanguage("de"); phase++; return
        }
        if (phase === 1) {
          if (status !== "Akkubetrieb" || label !== "Sofort") return
          check(strings.t("Charge fully once") === "Einmal vollständig laden", "German charge action")
          check(Model.limitLabel({end: 80}, strings) === "80 % Ladegrenze", "German limit placeholder")
          check(Model.explanation({key:"BAT0", supported:true, enabled:true, end:80, start:75}, true, strings).indexOf("75 %") >= 0, "German resume placeholder")
          I18n.language = "de-AT"; phase++; return
        }
        if (phase === 2) {
          if (status !== "Akkubetrieb") return
          check(strings.t("Cancel") === "Abbrechen", "regional German fallback")
          I18n.setLanguage("is"); phase++; return
        }
        if (phase === 3) {
          if (status !== "On battery" || label !== "Immediately") return
          check(strings.t("Charge fully once") === "Charge fully once", "English fallback")
          check(strings.t("Unknown diagnostic", "Unknown diagnostic") === "Unknown diagnostic", "unknown diagnostic preserved")
          phase = 4
          nextLanguage()
          return
        }
        if (phase === 4) {
          var code = cases[languageIndex][0]
          if (status !== cases[languageIndex][1]) return
          check(strings.t("Charge fully once") !== "Charge fully once" || code === "en", "translated charge action: " + code)
          if (code === "ar") {
            if (!I18n.rightToLeft) return
          } else check(!I18n.rightToLeft, "left-to-right restored: " + code)
          if (++languageIndex < cases.length) { nextLanguage(); return }
          console.log("PASS: all catalog live switches, regional and English fallbacks, Arabic RTL and placeholders")
          Qt.quit()
        }
      } catch (error) { console.log("FAIL: " + error); Qt.quit() }
    }
  }
}
