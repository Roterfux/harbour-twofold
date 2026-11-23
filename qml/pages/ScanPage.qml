// Twofold - SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick 2.6
import Sailfish.Silica 1.0
import QtMultimedia 5.6

// Reads an account's QR code (otpauth://) with the camera. Taken from Synctide's scanner.
//
// Several times a second the viewfinder is copied (ShaderEffectSource: on the Xperia a
// VideoOutput's own grabToImage gives black pictures), saved as a PPM file and read by
// python/qrscan.py. Should the copies come out black, the page takes photos instead.
Page {
    id: page
    property var app
    property var whenFound            // function (uri), called once

    property string folder: ""        // where the frames go (the app's cache folder)
    property bool busy: false         // a frame is being saved or read
    property bool done: false
    property bool fromStill: false    // the viewfinder copies are black: read photos instead
    property bool stillBusy: false
    property int frames: 0
    property int blanks: 0
    property int lastMs: 0
    property string message: qsTr("Starting the camera")

    readonly property int frameWidth: 640
    readonly property int frameHeight: viewfinder.contentRect.width > 0
        ? Math.round(frameWidth * viewfinder.contentRect.height / viewfinder.contentRect.width) : 480
    readonly property bool cameraActive: camera.cameraStatus === Camera.ActiveStatus

    allowedOrientations: Orientation.Portrait

    Component.onCompleted: app.call("scan_folder", [], function (path) { page.folder = path })

    function handle(result) {
        busy = false
        stillBusy = false
        if (done) return
        frames += 1
        lastMs = result.ms
        if (result.uri) {
            done = true
            var callback = whenFound
            pageStack.pop()
            if (callback) callback(result.uri)
        } else if (result.why) {
            message = result.why
        } else if (result.blank) {
            blanks += 1
            if (!fromStill && blanks >= 4 && blanks === frames) {
                fromStill = true
                message = qsTr("The viewfinder cannot be read on this phone; reading photos instead")
            }
        } else {
            message = qsTr("Point the camera at the QR code")
        }
    }

    function read(path) {
        app.call("scan_picture", [path, true], handle)
    }

    function grabFrame() {
        if (busy || done || folder === "" || !cameraActive) return
        busy = true
        var asked = frameBox.grabToImage(function (result) {
            var path = page.folder + "/frame.ppm"
            if (result.saveToFile(path)) {
                page.read(path)
            } else {
                page.busy = false
                page.message = qsTr("The frame could not be saved in %1").arg(page.folder)
            }
        }, Qt.size(frameWidth, frameHeight))
        if (!asked) busy = false
    }

    function takePicture() {
        if (stillBusy || done || folder === "" || !cameraActive || !camera.imageCapture.ready) return
        stillBusy = true
        camera.searchAndLock()
        camera.imageCapture.captureToLocation(folder + "/still-" + Date.now() + ".jpg")
    }

    Camera {
        id: camera
        captureMode: Camera.CaptureStillImage
        cameraState: page.done || !Qt.application.active ? Camera.UnloadedState : Camera.ActiveState
        flash.mode: Camera.FlashOff
        focus.focusMode: Camera.FocusContinuous
        focus.focusPointMode: Camera.FocusPointCenter
        imageCapture.onImageSaved: page.read(path)
        imageCapture.onCaptureFailed: {
            page.stillBusy = false
            page.message = qsTr("The photo failed: %1").arg(message)
        }
        onCameraStatusChanged: {
            if (cameraStatus === Camera.ActiveStatus && page.frames === 0)
                page.message = qsTr("Point the camera at the QR code")
        }
        onError: page.message = qsTr("Camera error: %1").arg(errorString)
    }

    // ---- what the camera sees
    Item {
        anchors.fill: parent
        clip: true

        VideoOutput {
            id: viewfinder
            anchors.fill: parent
            source: camera
            fillMode: VideoOutput.PreserveAspectFit
            orientation: 0              // the Sailfish camera backend turns the frames itself
        }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height) * 0.7
            height: width
            color: "transparent"
            border.width: Theme.paddingSmall / 2
            border.color: Theme.highlightColor
            radius: Theme.paddingMedium
            opacity: 0.8
        }

        MouseArea {
            anchors.fill: parent
            onClicked: camera.searchAndLock()
        }
    }

    // ---- the text on top
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: header.height + messageLabel.height + Theme.paddingLarge
        color: Theme.rgba("black", 0.55)
        PageHeader {
            id: header
            title: qsTr("Scan QR code")
        }
        Label {
            id: messageLabel
            anchors { top: header.bottom; left: parent.left; right: parent.right
                      leftMargin: Theme.horizontalPageMargin; rightMargin: Theme.horizontalPageMargin }
            wrapMode: Text.Wrap
            color: Theme.highlightColor
            text: page.message
        }
    }

    // ---- the bottom: what the scanner reads, and the photo button
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: Math.max(frameBox.height, takeButton.height) + 2 * Theme.paddingLarge
        color: Theme.rgba("black", 0.55)

        // The copy of the viewfinder that is read, shown small (black = the copy does not work)
        Item {
            id: frameBox
            x: Theme.horizontalPageMargin
            anchors.verticalCenter: parent.verticalCenter
            width: Theme.itemSizeHuge
            height: Math.round(width * page.frameHeight / page.frameWidth)
            opacity: page.fromStill ? 0.3 : 1.0
            ShaderEffectSource {
                id: snap
                anchors.fill: parent
                sourceItem: viewfinder
                sourceRect: viewfinder.contentRect
                textureSize: Qt.size(page.frameWidth, page.frameHeight)
                live: false
                hideSource: false
            }
        }

        Column {
            anchors { left: frameBox.right; leftMargin: Theme.paddingLarge
                      right: parent.right; rightMargin: Theme.horizontalPageMargin
                      verticalCenter: parent.verticalCenter }
            spacing: Theme.paddingSmall
            Button {
                id: takeButton
                width: parent.width
                text: page.stillBusy ? qsTr("Reading photo") : qsTr("Take a photo")
                enabled: page.cameraActive && !page.stillBusy
                onClicked: page.takePicture()
            }
            Label {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.secondaryColor
                text: page.frames > 0 ? qsTr("%1 pictures read, %2 ms each").arg(page.frames).arg(page.lastMs)
                                      : ""
            }
        }
    }

    // Copy the viewfinder, then save the copy once it has been drawn
    Timer {
        interval: 600
        repeat: true
        running: page.cameraActive && !page.fromStill && !page.done && page.folder !== ""
                 && page.status === PageStatus.Active
        onTriggered: {
            if (page.busy) return
            snap.scheduleUpdate()
            grabLater.restart()
        }
    }
    Timer {
        id: grabLater
        interval: 120
        onTriggered: page.grabFrame()
    }
    // Photo mode: a photo every few seconds
    Timer {
        interval: 2500
        repeat: true
        running: page.fromStill && page.cameraActive && !page.done
                 && page.status === PageStatus.Active
        onTriggered: page.takePicture()
    }
}
