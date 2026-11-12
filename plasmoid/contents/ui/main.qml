import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PC3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    // Runs through a shell, so $HOME is expanded.
    readonly property string ctl: '"$HOME/.local/bin/z407ctl"'
    readonly property int levelMax: 20
    // Bars from this index on (levels 17-20) are drawn in the warning color.
    readonly property int hotFrom: 16

    property var st: ({ daemon: false })
    property int seq: 0
    property int wheelDelta: 0

    readonly property bool daemonUp: st.daemon === true
    readonly property bool connected: st.connected === true
    readonly property bool connecting: st.connecting === true

    readonly property string stateText: {
        if (!daemonUp) return i18n("Service not running (z407d)");
        if (connecting) return i18n("Connecting…");
        if (connected) return i18n("Connected");
        if (st.error === "connect_failed") return i18n("Could not connect. Is the control pod still on?");
        return i18n("Not connected, connects on use");
    }

    function fmt(v) { return (v === null || v === undefined) ? "?" : v + "/" + levelMax; }

    function run(cmd) {
        // A unique suffix keeps the executable engine from dropping repeated identical commands.
        seq += 1;
        exec.connectSource(ctl + " " + cmd + " #" + seq);
    }

    Plasmoid.icon: "audio-speakers"
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    toolTipMainText: i18n("Logitech Z407")
    toolTipSubText: connected ? i18n("Volume %1 · Bass %2\nScroll: volume · Middle-click: play/pause", fmt(st.volume), fmt(st.bass))
                              : stateText

    onExpandedChanged: () => {
        if (!root.expanded) root.confirmForget = false;
    }

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source);
            try {
                root.st = JSON.parse(data["stdout"]);
            } catch (e) {
                root.st = { daemon: false };
            }
        }
    }

    Timer {
        interval: root.expanded || root.connecting ? 1500 : 10000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.run("status")
    }

    compactRepresentation: MouseArea {
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onClicked: mouse => {
            if (mouse.button === Qt.MiddleButton) root.run("play_pause");
            else root.expanded = !root.expanded;
        }
        onWheel: wheel => {
            root.wheelDelta += wheel.angleDelta.y;
            while (root.wheelDelta >= 120) { root.run("vol_up"); root.wheelDelta -= 120; }
            while (root.wheelDelta <= -120) { root.run("vol_down"); root.wheelDelta += 120; }
        }

        Kirigami.Icon {
            anchors.fill: parent
            source: Qt.resolvedUrl("../icons/z407.svg")
            isMask: true
            color: Kirigami.Theme.textColor
            opacity: root.connected ? 1 : 0.5
        }
    }


    readonly property bool canSend: daemonUp && !connecting

    // Set from the context menu; the popup then asks before the tracked levels are dropped.
    property bool confirmForget: false

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Reset volume and bass levels…")
            icon.name: "edit-reset-symbolic"
            enabled: root.daemonUp
            onTriggered: {
                root.confirmForget = true;
                root.expanded = true;
            }
        }
    ]

    // One level (volume or bass): header with the value, then a clickable/draggable bar meter between -/+.
    component LevelControl: ColumnLayout {
        id: level
        property string title
        property string iconSource
        property bool iconIsMask: false
        property var value
        property string setCmd
        property string upCmd
        property string downCmd

        // Value chosen in the UI that the speaker has not confirmed yet; -1 when none.
        property int pendingValue: -1
        readonly property bool known: value !== null && value !== undefined
        readonly property bool pending: pendingValue >= 0
        readonly property int shownValue: pending ? pendingValue : (known ? value : 0)

        function commit(v) {
            v = Math.max(0, Math.min(root.levelMax, v));
            if (known && v === value) {
                pendingValue = -1;
                return;
            }
            pendingValue = v;
            pendingTimeout.restart();
            root.run(setCmd + " " + v);
        }

        onValueChanged: if (value === pendingValue) pendingValue = -1

        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Timer {
            id: pendingTimeout
            interval: 15000
            onTriggered: level.pendingValue = -1
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: level.iconSource
                isMask: level.iconIsMask
                color: Kirigami.Theme.textColor
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            PC3.Label {
                text: level.title
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            PC3.Label {
                text: level.known || level.pending ? level.shownValue : "?"
                font.weight: Font.DemiBold
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.3
                opacity: level.pending ? 0.6 : 1
            }
            PC3.Label {
                text: "/ " + root.levelMax
                opacity: 0.5
                font: Kirigami.Theme.smallFont
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PC3.ToolButton {
                icon.name: "list-remove-symbolic"
                enabled: root.canSend
                autoRepeat: true
                autoRepeatInterval: 250
                onClicked: root.run(level.downCmd)
                Layout.alignment: Qt.AlignBottom
            }

            Item {
                id: meter
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2.2

                readonly property int gap: 3

                Row {
                    anchors.fill: parent
                    spacing: meter.gap
                    Repeater {
                        model: root.levelMax
                        Rectangle {
                            required property int index
                            readonly property bool lit: index < level.shownValue
                            // Top steps (17-20) glow red to signal "very loud".
                            readonly property bool hot: index >= root.hotFrom
                            width: (meter.width - meter.gap * (root.levelMax - 1)) / root.levelMax
                            height: meter.height * (0.3 + 0.7 * (index + 1) / root.levelMax)
                            anchors.bottom: parent.bottom
                            radius: Math.min(width / 2, 3)
                            color: !lit ? Kirigami.Theme.textColor
                                 : hot ? Kirigami.Theme.negativeTextColor
                                 : Kirigami.Theme.highlightColor
                            opacity: lit ? (level.pending ? 0.55 : 1) : (meterMouse.containsMouse ? 0.22 : 0.14)
                            Behavior on opacity { NumberAnimation { duration: Kirigami.Units.shortDuration } }
                        }
                    }
                }

                MouseArea {
                    id: meterMouse
                    anchors.fill: parent
                    enabled: root.canSend
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    property int wheelDelta: 0

                    function valueAt(x) {
                        return Math.max(0, Math.min(root.levelMax, Math.ceil(x / width * root.levelMax)));
                    }

                    onPressed: mouse => { level.pendingValue = valueAt(mouse.x); pendingTimeout.stop(); }
                    onPositionChanged: mouse => { if (pressed) level.pendingValue = valueAt(mouse.x); }
                    onReleased: mouse => level.commit(valueAt(mouse.x))
                    onWheel: wheel => {
                        wheelDelta += wheel.angleDelta.y;
                        while (wheelDelta >= 120) { root.run(level.upCmd); wheelDelta -= 120; }
                        while (wheelDelta <= -120) { root.run(level.downCmd); wheelDelta += 120; }
                    }
                }
            }

            PC3.ToolButton {
                icon.name: "list-add-symbolic"
                enabled: root.canSend
                autoRepeat: true
                autoRepeatInterval: 250
                onClicked: root.run(level.upCmd)
                Layout.alignment: Qt.AlignBottom
            }
        }

        PC3.Label {
            visible: !level.known
            text: level.pending ? i18n("Syncing: stepping down to the minimum first…")
                                : i18n("Level unknown. Click a bar to sync from the minimum.")
            font: Kirigami.Theme.smallFont
            opacity: 0.6
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 16
        Layout.preferredWidth: Kirigami.Units.gridUnit * 20
        Layout.minimumHeight: Kirigami.Units.gridUnit * 14
        Layout.preferredHeight: Kirigami.Units.gridUnit * 15

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing

            // Connection state
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Rectangle {
                    Layout.preferredWidth: 8
                    Layout.preferredHeight: 8
                    radius: 4
                    color: root.connected ? Kirigami.Theme.positiveTextColor
                         : root.connecting ? Kirigami.Theme.neutralTextColor
                         : root.daemonUp ? Kirigami.Theme.disabledTextColor
                         : Kirigami.Theme.negativeTextColor
                }
                PC3.Label {
                    text: root.stateText
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                PC3.BusyIndicator {
                    visible: root.connecting
                    running: visible
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }
                PC3.ToolButton {
                    icon.name: root.connected ? "network-disconnect-symbolic" : "network-connect-symbolic"
                    enabled: root.canSend
                    onClicked: root.run(root.connected ? "disconnect" : "connect")
                    PC3.ToolTip.text: root.connected ? i18n("Disconnect") : i18n("Connect")
                    PC3.ToolTip.visible: hovered
                    PC3.ToolTip.delay: Kirigami.Units.toolTipDelay
                }
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.confirmForget
                type: Kirigami.MessageType.Warning
                text: i18n("Forget the tracked levels? Only needed if you changed them with the control pod. The next adjustment steps volume and bass down to the minimum and back up.")
                actions: [
                    Kirigami.Action {
                        text: i18n("Reset")
                        icon.name: "edit-reset-symbolic"
                        onTriggered: {
                            root.confirmForget = false;
                            root.run("forget");
                        }
                    },
                    Kirigami.Action {
                        text: i18n("Cancel")
                        onTriggered: root.confirmForget = false
                    }
                ]
            }

            Item { Layout.fillHeight: true }

            LevelControl {
                title: i18n("Volume")
                iconSource: "audio-volume-high-symbolic"
                value: root.st.volume
                setCmd: "vol_set"
                upCmd: "vol_up"
                downCmd: "vol_down"
            }

            Item { Layout.fillHeight: true }

            LevelControl {
                title: i18n("Bass")
                iconSource: Qt.resolvedUrl("../icons/z407.svg")
                iconIsMask: true
                value: root.st.bass
                setCmd: "bass_set"
                upCmd: "bass_up"
                downCmd: "bass_down"
            }

            Item { Layout.fillHeight: true }

            Kirigami.Separator {
                Layout.fillWidth: true
                opacity: 0.5
            }

            // Playback + input source
            RowLayout {
                Layout.fillWidth: true
                spacing: 0

                PC3.ToolButton {
                    icon.name: "media-skip-backward-symbolic"
                    enabled: root.canSend
                    onClicked: root.run("prev")
                }
                PC3.ToolButton {
                    icon.name: "media-playback-start-symbolic"
                    enabled: root.canSend
                    onClicked: root.run("play_pause")
                }
                PC3.ToolButton {
                    icon.name: "media-skip-forward-symbolic"
                    enabled: root.canSend
                    onClicked: root.run("next")
                }

                Item { Layout.fillWidth: true }

                Repeater {
                    model: [
                        { cmd: "src_bt", key: "bluetooth", text: "BT", tip: "Bluetooth" },
                        { cmd: "src_aux", key: "aux", text: "AUX", tip: "AUX" },
                        { cmd: "src_usb", key: "usb", text: "USB", tip: "USB" }
                    ]
                    PC3.ToolButton {
                        required property var modelData
                        text: modelData.text
                        checkable: true
                        checked: root.st.source === modelData.key
                        enabled: root.canSend
                        font: Kirigami.Theme.smallFont
                        // Keep the checked state driven by the speaker, not by the click.
                        onClicked: {
                            checked = Qt.binding(() => root.st.source === modelData.key);
                            root.run(modelData.cmd);
                        }
                        PC3.ToolTip.text: i18n("Input: %1", modelData.tip)
                        PC3.ToolTip.visible: hovered
                        PC3.ToolTip.delay: Kirigami.Units.toolTipDelay
                    }
                }
            }
        }
    }
}
