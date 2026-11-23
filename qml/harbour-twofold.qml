// Twofold - SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick 2.6
import Sailfish.Silica 1.0
import Nemo.Configuration 1.0
import io.thp.pyotherside 1.3
import "pages"

ApplicationWindow {
    // Not "app": the pages have a property of that name (see Feedpond 0.1.0-2)
    id: appWindow

    property bool ready: false            // engine loaded
    property string vaultState: "loading"      // new | locked | unlocked
    property int revision: 0              // goes up when the list of accounts changed
    property var codes: ({})              // uuid -> current code
    property var nextCodes: ({})          // uuid -> code of the next period
    property real now: Date.now() / 1000  // seconds, ticks while unlocked and visible
    property string notice: ""
    property var mainPage: null
    property alias lockMinutes: cfg.lockMinutes
    property real hiddenSince: 0
    property bool fingerprint: false      // fingerprint unlock is on
    property bool asking: false           // the system's fingerprint dialog is open

    function unlockFingerprint() {
        if (asking) return
        asking = true
        call("unlock_fingerprint", [], function (r) {
            asking = false
            if (r.error) show(r.error)
            refreshState()
        })
    }

    function call(name, args, callback) {
        py.call("backend." + name, args || [], callback || function () {})
    }

    function show(text) {
        notice = ""
        notice = text
    }

    function refreshState() {
        call("status", [], function (s) {
            appWindow.vaultState = s.state
            appWindow.fingerprint = s.fingerprint
            appWindow.revision += 1
            refreshCodes()
        })
    }

    function refreshCodes() {
        if (vaultState !== "unlocked") { codes = ({}); nextCodes = ({}); return }
        call("codes", [], function (c) {
            appWindow.codes = c.now
            appWindow.nextCodes = c.next
        })
    }

    function lock() {
        call("lock", [], function () {
            appWindow.codes = ({})
            appWindow.nextCodes = ({})
            if (mainPage) pageStack.pop(mainPage, PageStackAction.Immediate)
            refreshState()
        })
    }

    // Lock after some time in the background (0 = as soon as the app is left)
    Connections {
        target: Qt.application
        onStateChanged: {
            if (Qt.application.state === Qt.ApplicationActive) {
                if (appWindow.vaultState === "unlocked" && appWindow.hiddenSince > 0
                        && appWindow.lockMinutes >= 0
                        && Date.now() / 1000 - appWindow.hiddenSince >= appWindow.lockMinutes * 60) {
                    appWindow.lock()
                }
                appWindow.hiddenSince = 0
                appWindow.now = Date.now() / 1000
                appWindow.refreshCodes()
            } else if (appWindow.hiddenSince === 0 && !appWindow.asking) {
                // (the fingerprint dialog also sends the app to the background: not a leave)
                appWindow.hiddenSince = Date.now() / 1000
            }
        }
    }
    // Also lock while still in the background, so the codes are not in memory longer
    Timer {
        interval: 15000
        repeat: true
        running: appWindow.vaultState === "unlocked" && appWindow.hiddenSince > 0
                 && appWindow.lockMinutes >= 0
        onTriggered: {
            if (Date.now() / 1000 - appWindow.hiddenSince >= appWindow.lockMinutes * 60)
                appWindow.lock()
        }
    }

    Timer {
        interval: 1000
        repeat: true
        running: appWindow.vaultState === "unlocked" && Qt.application.state === Qt.ApplicationActive
        triggeredOnStart: true
        onTriggered: {
            appWindow.now = Date.now() / 1000
            appWindow.refreshCodes()       // cheap: one HMAC per account
        }
    }

    ConfigurationGroup {
        id: cfg
        path: "/apps/harbour-twofold"
        property int lockMinutes: 1        // -1 = never
    }

    Python {
        id: py
        Component.onCompleted: {
            addImportPath(Qt.resolvedUrl("../python"))
            importModule("backend", function () {
                py.call("backend.init", [], function (s) {
                    appWindow.vaultState = s.state
                    appWindow.fingerprint = s.fingerprint
                    appWindow.ready = true
                    if (s.state === "locked" && s.fingerprint) appWindow.unlockFingerprint()
                })
            })
        }
        onError: appWindow.show(qsTr("Error: %1").arg(traceback))
    }

    allowedOrientations: defaultAllowedOrientations
    initialPage: Component { AccountsPage { app: appWindow } }

    cover: Component {
        CoverBackground {
            Column {
                anchors { left: parent.left; right: parent.right; margins: Theme.paddingLarge
                          verticalCenter: parent.verticalCenter }
                spacing: Theme.paddingMedium
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: "image://theme/icon-m-device-lock"
                    opacity: appWindow.vaultState === "unlocked" ? 0.4 : 1.0
                }
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Theme.highlightColor
                    text: appWindow.vaultState === "unlocked" ? qsTr("Unlocked") : qsTr("Locked")
                }
            }
            CoverActionList {
                enabled: appWindow.vaultState === "unlocked"
                CoverAction {
                    iconSource: "image://theme/icon-cover-cancel"
                    onTriggered: appWindow.lock()
                }
            }
        }
    }
}
