#!/bin/sh
# Compile every QML file of the app with the phone's own Qt and Silica, without a screen,
# and report the ones that fail (qmllint on the PC does not know Qt 5.6 or Silica).
# Run on the phone:  sh phone-qml-check.sh <folder with the app's qml/>
# Prints "OK file" / "FAIL file: error" and a last line "DONE <failures>".
set -e
ROOT=$(cd "${1:-.}" && pwd)
HARNESS=/tmp/qmlcheck-$$.qml             # BusyBox mktemp takes no suffix
trap 'rm -f "$HARNESS"' EXIT
FILES=$(cd "$ROOT" && find qml -name '*.qml' | sort | sed 's/.*/"&",/' | tr -d '\n')
cat > "$HARNESS" <<EOF
import QtQuick 2.6
Item {
    // from a timer: Qt.quit() before the event loop runs is ignored and qmlscene stays
    Timer {
        interval: 10
        running: true
        onTriggered: parent.check()
    }
    function check() {
        var files = [$FILES]
        var bad = 0
        for (var i = 0; i < files.length; ++i) {
            var c = Qt.createComponent("file://$ROOT/" + files[i], Component.PreferSynchronous)
            if (c.status === Component.Ready) {
                console.log("OK   " + files[i])
            } else {
                bad += 1
                console.log("FAIL " + files[i] + ": " + c.errorString().replace(/\n/g, " "))
            }
        }
        console.log("DONE " + bad)
        Qt.quit()
    }
}
EOF
QT_LOGGING_TO_CONSOLE=1 QT_QPA_PLATFORM=minimal qmlscene "$HARNESS" > "$HARNESS.log" 2>&1 &
RUNNER=$!
for _ in $(seq 60); do                    # at most a minute
    grep -q 'DONE ' "$HARNESS.log" 2>/dev/null && break
    sleep 1
done
kill "$RUNNER" 2>/dev/null || true
grep -E '(OK|FAIL|DONE) ' "$HARNESS.log" | sed 's/^.*\(OK \|FAIL\|DONE\)/\1/'
grep -q 'DONE ' "$HARNESS.log" || { echo "NO RESULT:"; tail -20 "$HARNESS.log"; }
rm -f "$HARNESS.log"
