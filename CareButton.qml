import QtQuick
import qs.Ui

// Keep mouse hover separate from the panel's keyboard navigation cursor.
Button {
  required property var navigationOwner
  required property int navigationIndex
  hasCursor: navigationOwner.cursorActive && navigationOwner.cursorIndex === navigationIndex
  onHovered: function(hovered) {
    if (hovered) {
      navigationOwner.cursorActive = false
      navigationOwner.cursorIndex = navigationIndex
    }
  }
}
