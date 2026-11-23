// Auto-lock, password, export, and what the app runs on.
import QtQuick 2.6
import Sailfish.Silica 1.0

Page {
    id: page
    property var app
    property string appVersion: "dev"     // stamped by the RPM build
    property var info: ({})
    readonly property var lockChoices: [0, 1, 5, 15, -1]

    Component.onCompleted: app.call("status", [], function (s) { page.info = s })

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width

            PageHeader { title: qsTr("Settings") }

            ComboBox {
                label: qsTr("Lock when left for")
                currentIndex: Math.max(0, page.lockChoices.indexOf(app.lockMinutes))
                menu: ContextMenu {
                    MenuItem { text: qsTr("at once") }
                    MenuItem { text: qsTr("1 minute") }
                    MenuItem { text: qsTr("5 minutes") }
                    MenuItem { text: qsTr("15 minutes") }
                    MenuItem { text: qsTr("never") }
                }
                onCurrentIndexChanged: app.lockMinutes = page.lockChoices[currentIndex]
            }

            TextSwitch {
                text: qsTr("Unlock with fingerprint")
                description: qsTr("Asks through the system dialog (fingerprint or security code). "
                                  + "While on, the vault key is kept on the phone, so anyone "
                                  + "with access to its files can open the vault.")
                checked: app.fingerprint
                automaticCheck: false
                enabled: !app.asking
                onClicked: {
                    app.asking = true
                    app.call(app.fingerprint ? "disable_fingerprint" : "enable_fingerprint", [],
                             function (r) {
                                 app.asking = false
                                 if (r.error) app.show(r.error)
                                 app.refreshState()
                             })
                }
            }

            SectionHeader { text: qsTr("Password") }
            PasswordField {
                id: oldPw
                width: parent.width
                label: qsTr("Current password")
            }
            PasswordField {
                id: newPw
                width: parent.width
                label: qsTr("New password")
            }
            PasswordField {
                id: newPw2
                width: parent.width
                label: qsTr("New password again")
            }
            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Change password")
                enabled: oldPw.text && newPw.text && !changing.running
                onClicked: {
                    if (newPw.text !== newPw2.text) { app.show(qsTr("The new passwords differ")); return }
                    changing.running = true
                    app.call("change_password", [oldPw.text, newPw.text], function (r) {
                        changing.running = false
                        app.show(r.error ? r.error : qsTr("Password changed"))
                        if (!r.error) { oldPw.text = ""; newPw.text = ""; newPw2.text = "" }
                    })
                }
            }
            BusyIndicator {
                id: changing
                anchors.horizontalCenter: parent.horizontalCenter
                size: BusyIndicatorSize.Small
                running: false
                visible: running
            }

            SectionHeader { text: qsTr("Backup") }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryHighlightColor
                text: qsTr("Saves the encrypted vault to Documents. It opens with your password "
                           + "and can be imported into Aegis or back into Twofold.")
            }
            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Export vault")
                onClicked: app.call("export_vault", [], function (r) {
                    app.show(r.error ? r.error : qsTr("Saved to %1").arg(r.path))
                })
            }

            SectionHeader { text: qsTr("About") }
            DetailItem { label: qsTr("Version"); value: page.appVersion }
            DetailItem { label: qsTr("Accounts"); value: page.info.count !== undefined ? page.info.count : "" }
            DetailItem {
                label: qsTr("Crypto")
                value: page.info.backends ? "scrypt: " + page.info.backends.scrypt
                                            + ", AES: " + page.info.backends.aes : ""
            }
            DetailItem { label: qsTr("Vault file"); value: page.info.path || "" }
            DetailItem {
                label: qsTr("Last problem")
                value: page.info.problem || qsTr("none")
            }
        }
    }
}
