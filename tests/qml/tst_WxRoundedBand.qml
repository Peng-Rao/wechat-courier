import QtQuick
import QtTest
import "../../qml/components"

TestCase {
    name: "WxRoundedBand"
    when: windowShown
    visible: true
    width: 200
    height: 120

    Item {
        id: scene
        width: 120
        height: 64
        Rectangle { anchors.fill: parent; color: "#d23465" }
        WxRoundedBand {
            id: band
            anchors.fill: parent
            fillColor: "#223344"
            radius: 8
        }
    }

    Item {
        id: reference
        x: 140
        width: 40
        height: 64
        Rectangle { anchors.fill: parent; color: "#d23465" }
        Rectangle { anchors.fill: parent; color: band.fillColor }
    }

    function init() {
        scene.height = 64
        band.fillColor = "#223344"
    }

    function checkPixel(image, x, y, color) {
        compare(image.pixel(x, y), color)
    }

    function test_end_corners_data() {
        return [
            {tag: "header", top: true, bottom: false},
            {tag: "footer", top: false, bottom: true},
            {tag: "both", top: true, bottom: true},
            {tag: "neither", top: false, bottom: false}
        ]
    }

    function test_end_corners(data) {
        band.roundTop = data.top
        band.roundBottom = data.bottom
        compare(band.radius, 8)
        waitForRendering(scene)
        var image = grabImage(scene)
        checkPixel(image, 0, 0, data.top ? "#d23465" : "#223344")
        checkPixel(image, image.width - 1, 0, data.top ? "#d23465" : "#223344")
        checkPixel(image, 0, image.height - 1, data.bottom ? "#d23465" : "#223344")
        checkPixel(image, image.width - 1, image.height - 1, data.bottom ? "#d23465" : "#223344")
        checkPixel(image, Math.floor(image.width / 2), Math.floor(image.height / 2), "#223344")
    }

    function test_translucent_fill_is_uniform_data() {
        return [{tag: "header", height: 48}, {tag: "footer", height: 52},
                {tag: "fractional_midpoint", height: 65}]
    }

    function test_translucent_fill_is_uniform(data) {
        scene.height = data.height
        band.fillColor = Qt.rgba(0.2, 0.3, 0.4, 0.5)
        waitForRendering(scene)
        var image = grabImage(scene)
        var referenceImage = grabImage(reference)
        var expected = referenceImage.pixel(10, 10)
        var x = Math.floor(image.width / 2)
        for (var y = 10; y < image.height - 10; ++y)
            compare(image.pixel(x, y), expected)
    }
}
