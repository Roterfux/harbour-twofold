// Add one account: paste an otpauth:// link, or type the secret and settings.
import QtQuick 2.6
import Sailfish.Silica 1.0

Dialog {
    id: dialog
    property var app
    readonly property bool byLink: linkField.text.trim().length > 0
    readonly property var types: ["totp", "hotp", "steam"]
    readonly property var algos: ["SHA1", "SHA256", "SHA512"]
    readonly property string kind: types[typeBox.currentIndex]

    canAccept: byLink || (secretField.text.trim().length > 0
                          && (issuerField.text.length > 0 || nameField.text.length > 0))

    onAccepted: {
        var done = function (r) {
            app.show(r.error ? r.error : qsTr("Account added"))
            app.refreshState()
        }
        if (byLink) {
            app.call("add_uri", [linkField.text.trim()], done)
        } else {
            app.call("add_manual", [{
                type: kind, issuer: issuerField.text, name: nameField.text,
                secret: secretField.text, algo: algos[algoBox.currentIndex],
                digits: parseInt(digitsField.text) || 6,
                period: parseInt(periodField.text) || 30,
                counter: parseInt(counterField.text) || 0
            }], done)
        }
    }

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width

            DialogHeader { title: qsTr("Add account"); acceptText: qsTr("Add") }

            TextField {
                id: linkField
                width: parent.width
                label: qsTr("otpauth:// link")
                placeholderText: qsTr("Paste an otpauth:// link")
                inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText | Qt.ImhUrlCharactersOnly
                EnterKey.iconSource: "image://theme/icon-m-enter-accept"
                EnterKey.onClicked: if (dialog.canAccept) dialog.accept()
            }
            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Paste")
                visible: Clipboard.hasText && !dialog.byLink
                         && Clipboard.text.indexOf("otpauth://") === 0
                onClicked: linkField.text = Clipboard.text
            }

            SectionHeader { text: qsTr("Or enter it by hand"); visible: !dialog.byLink }

            Column {
                width: parent.width
                visible: !dialog.byLink
                TextField {
                    id: issuerField
                    width: parent.width
                    label: qsTr("Service")
                    placeholderText: qsTr("Service, e.g. GitHub")
                    EnterKey.onClicked: nameField.focus = true
                }
                TextField {
                    id: nameField
                    width: parent.width
                    label: qsTr("Account")
                    placeholderText: qsTr("Account, e.g. you@example.com")
                    inputMethodHints: Qt.ImhNoAutoUppercase
                    EnterKey.onClicked: secretField.focus = true
                }
                TextField {
                    id: secretField
                    width: parent.width
                    label: qsTr("Secret key")
                    placeholderText: qsTr("Secret key (letters and digits 2-7)")
                    inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhPreferUppercase
                    font.family: "monospace"
                }
                ComboBox {
                    id: typeBox
                    label: qsTr("Type")
                    menu: ContextMenu {
                        MenuItem { text: qsTr("Time-based (TOTP)") }
                        MenuItem { text: qsTr("Counter-based (HOTP)") }
                        MenuItem { text: "Steam" }
                    }
                }
                ComboBox {
                    id: algoBox
                    visible: dialog.kind !== "steam"
                    label: qsTr("Algorithm")
                    menu: ContextMenu {
                        MenuItem { text: "SHA1" }
                        MenuItem { text: "SHA256" }
                        MenuItem { text: "SHA512" }
                    }
                }
                TextField {
                    id: digitsField
                    visible: dialog.kind !== "steam"
                    width: parent.width
                    label: qsTr("Digits")
                    text: "6"
                    inputMethodHints: Qt.ImhDigitsOnly
                    validator: IntValidator { bottom: 4; top: 10 }
                }
                TextField {
                    id: periodField
                    visible: dialog.kind === "totp"
                    width: parent.width
                    label: qsTr("Period (seconds)")
                    text: "30"
                    inputMethodHints: Qt.ImhDigitsOnly
                    validator: IntValidator { bottom: 1; top: 3600 }
                }
                TextField {
                    id: counterField
                    visible: dialog.kind === "hotp"
                    width: parent.width
                    label: qsTr("Counter")
                    text: "0"
                    inputMethodHints: Qt.ImhDigitsOnly
                    validator: IntValidator { bottom: 0 }
                }
            }
        }
    }
}
