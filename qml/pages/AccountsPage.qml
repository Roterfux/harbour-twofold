// The accounts with their current codes; the unlock (or first-start) form while locked.
import QtQuick 2.6
import Sailfish.Silica 1.0
import Sailfish.Pickers 1.0

Page {
    id: page
    property var app
    property string filter: ""
    property string pendingImport: ""     // picked file, imported once this page is back on top
    property var hotpCodes: ({})          // uuid -> code shown after "next code"
    readonly property bool unlocked: app.vaultState === "unlocked"

    Component.onCompleted: app.mainPage = page

    function reload() {
        app.call("entries", [], function (rows) {
            listModel.clear()
            for (var i = 0; i < rows.length; i++) listModel.append(rows[i])
        })
    }

    function matches(row) {
        if (!filter) return true
        var f = filter.toLowerCase()
        return (row.issuer + " " + row.name + " " + row.groups + " " + row.note)
               .toLowerCase().indexOf(f) >= 0
    }

    function spaced(code) {
        if (!code || code.length < 6) return code
        var half = Math.ceil(code.length / 2)
        return code.substring(0, half) + " " + code.substring(half)
    }

    function copy(uuid, type) {
        if (type === "hotp") {
            app.call("next_hotp", [uuid], function (r) {
                if (r.error) { app.show(r.error); return }
                var c = page.hotpCodes
                c[uuid] = r.code
                page.hotpCodes = c
                Clipboard.text = r.code
                app.show(qsTr("New code copied"))
            })
            return
        }
        var code = app.codes[uuid]
        if (code && code !== "?") {
            Clipboard.text = code
            app.show(qsTr("Code copied"))
        }
    }

    function runImport(path, password) {
        app.call("import_file", [path, password], function (r) {
            if (r.needPassword) {
                pageStack.push(Qt.resolvedUrl("PasswordDialog.qml"), {
                    title: qsTr("Password of the Aegis export"),
                    acceptText: qsTr("Import"),
                    callback: function (pw) { page.runImport(path, pw) }
                })
            } else if (r.error) {
                app.show(r.error)
            } else {
                var text = qsTr("Imported %1, skipped %2 already here").arg(r.added).arg(r.skipped)
                if (r.unsupported)
                    text += "\n" + qsTr("%1 of an unsupported type (Yandex/mOTP): kept, no codes")
                            .arg(r.unsupported)
                app.show(text)
                app.refreshState()
            }
        })
    }

    function addUri(uri) {
        app.call("add_uri", [uri], function (r) {
            app.show(r.error ? r.error : qsTr("Added %1").arg(r.label))
            app.refreshState()
        })
    }

    function scanPicture(path) {
        app.call("scan_picture", [path, false], function (r) {
            if (r.uri) addUri(r.uri)
            else app.show(r.why || qsTr("No QR code found in this picture"))
        })
    }

    onStatusChanged: {
        if (status !== PageStatus.Active) return
        if (pendingImport) {
            var path = pendingImport
            pendingImport = ""
            runImport(path, "")
        }
        if (pendingPicture) {
            var picture = pendingPicture
            pendingPicture = ""
            scanPicture(picture)
        }
    }

    property string pendingPicture: ""    // picked picture, scanned once this page is back on top

    Component {
        id: picturePicker
        ImagePickerPage {
            title: qsTr("Picture with a QR code")
            onSelectedContentPropertiesChanged: {
                if (selectedContentProperties && selectedContentProperties.filePath)
                    page.pendingPicture = String(selectedContentProperties.filePath)
            }
        }
    }

    Connections {
        target: app
        onRevisionChanged: page.reload()
        onVaultStateChanged: if (!page.unlocked) { listModel.clear(); page.hotpCodes = ({}) }
    }

    ListModel { id: listModel }

    Component {
        id: importPicker
        FilePickerPage {
            title: qsTr("Aegis export (.json)")
            nameFilters: ["*.json"]
            onSelectedContentPropertiesChanged: {
                if (selectedContentProperties && selectedContentProperties.filePath)
                    page.pendingImport = String(selectedContentProperties.filePath)
            }
        }
    }

    // ----- locked / first start -----
    SilicaFlickable {
        anchors.fill: parent
        visible: !page.unlocked
        contentHeight: lockColumn.height

        // Forgotten password: start over (the old vault is kept, renamed), then re-import
        PullDownMenu {
            visible: app.vaultState === "locked"
            MenuItem {
                text: qsTr("Reset app")
                onClicked: resetRemorse.execute(qsTr("Resetting: all accounts go"), function () {
                    app.call("reset", [], function (r) {
                        app.show(r.error ? r.error
                                         : qsTr("Reset. Choose a new password, then pull down to import from Aegis. The old vault was kept as %1").arg(r.kept))
                        app.refreshState()
                    })
                })
            }
        }
        RemorsePopup { id: resetRemorse }

        Column {
            id: lockColumn
            width: parent.width
            spacing: Theme.paddingLarge

            PageHeader { title: "Twofold" }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                color: Theme.highlightColor
                text: app.vaultState === "new"
                      ? qsTr("Choose a password for your vault. Your accounts are stored "
                             + "encrypted with it (same format as Aegis). There is no way to "
                             + "recover a forgotten password.")
                      : app.vaultState === "locked" ? qsTr("Enter your password to unlock. Forgot it? Pull down to reset.")
                      : qsTr("Loading")
            }

            PasswordField {
                id: pw
                width: parent.width
                visible: app.ready && app.vaultState !== "loading"
                label: qsTr("Password")
                EnterKey.iconSource: "image://theme/icon-m-enter-accept"
                EnterKey.onClicked: app.vaultState === "new" ? pw2.focus = true : unlockButton.clicked(null)
            }
            PasswordField {
                id: pw2
                width: parent.width
                visible: app.vaultState === "new"
                label: qsTr("Password again")
                EnterKey.iconSource: "image://theme/icon-m-enter-accept"
                EnterKey.onClicked: unlockButton.clicked(null)
            }
            Button {
                id: unlockButton
                anchors.horizontalCenter: parent.horizontalCenter
                visible: pw.visible
                enabled: !busy.running && pw.text.length > 0
                text: app.vaultState === "new" ? qsTr("Create vault") : qsTr("Unlock")
                onClicked: {
                    if (app.vaultState === "new" && pw.text !== pw2.text) {
                        app.show(qsTr("The two passwords differ"))
                        return
                    }
                    busy.running = true
                    app.call(app.vaultState === "new" ? "create" : "unlock", [pw.text], function (r) {
                        // create() leaves the new vault open
                        if (r.error) app.show(r.error)
                        else app.refreshState()
                        busy.running = false
                        pw.text = ""
                        pw2.text = ""
                    })
                }
            }
            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: app.vaultState === "locked" && app.fingerprint
                enabled: !app.asking && !busy.running
                text: qsTr("Unlock with fingerprint")
                onClicked: app.unlockFingerprint()
            }
            BusyIndicator {
                id: busy
                anchors.horizontalCenter: parent.horizontalCenter
                size: BusyIndicatorSize.Medium
                running: false
                visible: running
            }
        }
    }

    // ----- unlocked: the accounts -----
    SilicaListView {
        id: list
        anchors.fill: parent
        visible: page.unlocked
        model: listModel

        header: Column {
            width: list.width
            PageHeader { title: "Twofold" }
            SearchField {
                width: parent.width
                placeholderText: qsTr("Search")
                visible: listModel.count > 4
                onTextChanged: page.filter = text
                EnterKey.onClicked: focus = false
            }
        }

        PullDownMenu {
            MenuItem {
                text: qsTr("Settings")
                onClicked: pageStack.push(Qt.resolvedUrl("SettingsPage.qml"), { app: app })
            }
            MenuItem {
                text: qsTr("Import from Aegis")
                onClicked: pageStack.push(importPicker)
            }
            MenuItem {
                text: qsTr("Add account by hand")
                onClicked: pageStack.push(Qt.resolvedUrl("AddDialog.qml"), { app: app })
            }
            MenuItem {
                text: qsTr("QR code from picture")
                onClicked: pageStack.push(picturePicker)
            }
            MenuItem {
                text: qsTr("Scan QR code")
                onClicked: pageStack.push(Qt.resolvedUrl("ScanPage.qml"), {
                    app: app, whenFound: function (uri) { page.addUri(uri) } })
            }
            MenuItem {
                text: qsTr("Lock")
                onClicked: app.lock()
            }
        }

        ViewPlaceholder {
            enabled: page.unlocked && listModel.count === 0
            text: qsTr("No accounts yet")
            hintText: qsTr("Pull down to import from Aegis, scan a QR code or add an account")
        }

        delegate: ListItem {
            id: item
            width: list.width
            visible: page.matches(model)
            contentHeight: visible ? Math.max(Theme.itemSizeLarge, textColumn.height + 2 * Theme.paddingMedium) : 0
            menu: itemMenu
            onClicked: page.copy(model.uuid, model.type)

            function remove() {
                var id = model.uuid
                remorseAction(qsTr("Deleting"), function () {
                    app.call("remove", [id], function (r) {
                        if (r.error) app.show(r.error)
                        app.refreshState()
                    })
                })
            }

            readonly property real remaining: model.period - (app.now % model.period)
            readonly property string code: model.type === "hotp" ? (page.hotpCodes[model.uuid] || "")
                                                                 : (app.codes[model.uuid] || "")

            // Icon from the Aegis entry, else the first letter in a circle
            Rectangle {
                id: badge
                x: Theme.horizontalPageMargin
                anchors.verticalCenter: parent.verticalCenter
                width: Theme.iconSizeMedium
                height: width
                radius: width / 2
                color: icon.status === Image.Ready ? "transparent" : Theme.rgba(Theme.highlightBackgroundColor, 0.4)
                Label {
                    anchors.centerIn: parent
                    visible: icon.status !== Image.Ready
                    text: (model.issuer || model.name || "?").charAt(0).toUpperCase()
                    font.pixelSize: Theme.fontSizeLarge
                }
                Image {
                    id: icon
                    anchors.fill: parent
                    source: model.icon
                    sourceSize.width: width
                    sourceSize.height: height
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }
            }

            Column {
                id: textColumn
                anchors { left: badge.right; leftMargin: Theme.paddingLarge
                          right: parent.right; rightMargin: Theme.horizontalPageMargin
                          verticalCenter: parent.verticalCenter }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    color: item.highlighted ? Theme.highlightColor : Theme.primaryColor
                    text: (model.favorite ? "★ " : "") + (model.issuer || model.name)
                }
                Label {
                    width: parent.width
                    visible: model.issuer && model.name
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: model.name
                }
                Label {
                    font.pixelSize: Theme.fontSizeExtraLarge
                    font.family: Theme.fontFamilyHeading
                    color: Theme.highlightColor
                    text: !model.supported ? qsTr("unsupported type")
                          : model.type === "hotp" && !item.code ? qsTr("tap for a code")
                          : page.spaced(item.code)
                    opacity: !model.supported || (model.type === "hotp" && !item.code) ? 0.6 : 1.0
                }
                // The code of the next period, small
                Label {
                    visible: model.supported && model.type !== "hotp" && text !== ""
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryHighlightColor
                    text: app.nextCodes[model.uuid] ? qsTr("next %1").arg(page.spaced(app.nextCodes[model.uuid])) : ""
                }
                // Time left for this code
                Rectangle {
                    visible: model.supported && model.type !== "hotp"
                    height: Theme.paddingSmall / 2
                    width: parent.width * item.remaining / model.period
                    color: item.remaining < 6 ? "#e05050" : Theme.highlightColor
                    opacity: 0.6
                }
            }

            Component {
                id: itemMenu
                ContextMenu {
                    MenuItem {
                        text: qsTr("Copy code")
                        visible: model.type !== "hotp"
                        onClicked: page.copy(model.uuid, model.type)
                    }
                    MenuItem {
                        text: qsTr("Copy next code")
                        visible: model.type !== "hotp" && !!app.nextCodes[model.uuid]
                        onClicked: {
                            Clipboard.text = app.nextCodes[model.uuid]
                            app.show(qsTr("Next code copied"))
                        }
                    }
                    MenuItem {
                        text: qsTr("Edit")
                        onClicked: pageStack.push(Qt.resolvedUrl("EditDialog.qml"), {
                            app: app, uuid: model.uuid, issuer: model.issuer,
                            name: model.name, note: model.note })
                    }
                    MenuItem {
                        text: qsTr("Delete")
                        onClicked: item.remove()
                    }
                }
            }
        }
        VerticalScrollDecorator {}
    }

    // Short messages at the bottom
    Rectangle {
        id: banner
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: bannerText.height + 2 * Theme.paddingLarge
        color: Theme.rgba(Theme.highlightDimmerColor, 0.95)
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { FadeAnimation {} }
        Label {
            id: bannerText
            anchors.centerIn: parent
            width: parent.width - 2 * Theme.horizontalPageMargin
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.highlightColor
            text: app.notice
        }
        MouseArea { anchors.fill: parent; onClicked: banner.opacity = 0 }
        Timer { id: bannerTimer; interval: 3500; onTriggered: banner.opacity = 0 }
    }
    Connections {
        target: app
        onNoticeChanged: if (app.notice) { banner.opacity = 1; bannerTimer.restart() }
    }
}
