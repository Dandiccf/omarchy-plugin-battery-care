import QtQuick
import QtQuick.Window
import Quickshell
import "Care" as Care

ShellRoot {
  Window {
    id: window
    width: 340
    height: 400
    visible: true
    title: "Battery Care menu check"
    color: "#20202b"
    Care.TimeoutDropdown {
      id: menu
      x: 20; y: 320; width: 280
      options: ["30s", "1m", "2m", "5m", "10m", "15m", "30m", "1h", "Custom…"]
      value: "5m"
    }
  }
  Timer {
    property int phase: 0
    interval: 150; running: true; repeat: true
    onTriggered: {
      try {
        if (phase === 0) { menu.open(); phase++ }
        else if (phase === 1) {
          if (!menu.popupOpen || !menu.opensUpwards) throw new Error("menu must open above a bottom selector")
          menu.close(); menu.y = 10; phase++
        } else if (phase === 2) { menu.open(); phase++ }
        else {
          if (!menu.popupOpen || menu.opensUpwards) throw new Error("menu must open below a top selector")
          console.log("PASS: timeout menu adapts to available space after layout")
          Qt.quit()
        }
      } catch (error) { console.log("FAIL: " + error); Qt.quit() }
    }
  }
}
