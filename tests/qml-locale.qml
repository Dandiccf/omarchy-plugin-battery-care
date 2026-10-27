import QtQuick
import Quickshell
import "Care" as Care
import "Care/Model.js" as Model

ShellRoot {
  Care.CareTranslations { id: strings }
  Care.TimeoutEditor { id: editor }
  property string status: Model.status({key: "BAT0", state: 2}, true, strings)
  Timer {
    property int attempts: 0
    interval: 100; running: true; repeat: true
    onTriggered: {
      try {
        if (++attempts > 50) throw new Error("legacy translations timed out")
        if (strings.nativeAvailable) throw new Error("legacy fixture unexpectedly loaded native Translations")
        if (strings.language !== "de-AT") throw new Error("system locale precedence: " + strings.language)
        if (status !== "Akkubetrieb" || editor.label(0) !== "Sofort") return
        if (strings.formatNumber(13.1, 1) !== "13,1") throw new Error("locale number formatting")
        if (strings.t("Charge fully once") !== "Einmal vollständig laden") throw new Error("base language fallback")
        console.log("PASS: actual legacy Commons without I18n/Translations, POSIX locale, regional fallback and numbers")
        Qt.quit()
      } catch (error) { console.log("FAIL: " + error); Qt.quit() }
    }
  }
}
