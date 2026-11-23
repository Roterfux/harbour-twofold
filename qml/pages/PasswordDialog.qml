// Asks for one password; callback(password) runs once the dialog is accepted.
import QtQuick 2.6
import Sailfish.Silica 1.0

Dialog {
    id: dialog
    property string title
    property string acceptText
    property var callback

    canAccept: field.text.length > 0
    onAccepted: callback(field.text)

    Column {
        width: parent.width
        DialogHeader { title: dialog.title; acceptText: dialog.acceptText }
        PasswordField {
            id: field
            width: parent.width
            focus: true
            label: qsTr("Password")
            EnterKey.enabled: dialog.canAccept
            EnterKey.iconSource: "image://theme/icon-m-enter-accept"
            EnterKey.onClicked: dialog.accept()
        }
    }
}
