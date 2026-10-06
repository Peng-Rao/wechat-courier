// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "FugeWeChatMac",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "FugeWeChat", targets: ["FugeWeChat"]),
        .executable(name: "WeChatMacAgent", targets: ["WeChatMacAgent"])
    ],
    targets: [
        .target(name: "CourierCore"),
        .executableTarget(name: "FugeWeChat", dependencies: ["CourierCore"]),
        .executableTarget(name: "WeChatMacAgent", dependencies: ["CourierCore"]),
        .testTarget(name: "CourierCoreTests", dependencies: ["CourierCore"]),
        .testTarget(name: "CourierAppTests", dependencies: ["FugeWeChat", "CourierCore"])
    ]
)
