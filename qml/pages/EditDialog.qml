// Rename an account and edit its note.
import QtQuick 2.6
import Sailfish.Silica 1.0

Dialog {
    id: dialog
    property var app
    property string uuid
    property string issuer
    property string name
    property string note

    canAccept: issuerField.text.length > 0 || nameField.text.length > 0
    onAccepted: app.call("update", [uuid, nameField.text, issuerField.text, noteField.text],
                         function (r) {
                             if (r.error) app.show(r.error)
                             app.refreshState()
                         })

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height
        Column {
            id: column
            width: parent.width
            DialogHeader { title: qsTr("Edit account") }
            TextField {
                id: issuerField
                width: parent.width
                label: qsTr("Service")
                text: dialog.issuer
                EnterKey.onClicked: nameField.focus = true
            }
            TextField {
                id: nameField
                width: parent.width
                label: qsTr("Account")
                text: dialog.name
                inputMethodHints: Qt.ImhNoAutoUppercase
                EnterKey.onClicked: noteField.focus = true
            }
            TextArea {
                id: noteField
                width: parent.width
                label: qsTr("Note")
                text: dialog.note
            }
        }
    }
}
