import QtQuick

Item {
    id: root
    property color fillColor: "transparent"
    property real radius: 8
    property bool roundTop: true
    property bool roundBottom: true

    // Disjoint clips keep translucent fills from blending over themselves.
    Item {
        id: topHalf
        width: root.width
        height: root.height / 2
        clip: true
        Rectangle {
            width: root.width
            height: root.height
            radius: root.roundTop ? root.radius : 0
            color: root.fillColor
            antialiasing: true
        }
    }
    Item {
        y: topHalf.height
        width: root.width
        height: root.height - topHalf.height
        clip: true
        Rectangle {
            y: -topHalf.height
            width: root.width
            height: root.height
            radius: root.roundBottom ? root.radius : 0
            color: root.fillColor
            antialiasing: true
        }
    }
}
